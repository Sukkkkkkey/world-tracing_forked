"""Offscreen pinhole rasterization with explicit RDF, pixel-center and texture conventions."""
import numpy as np
import trimesh


def load_mesh_parts(path):
    scene = trimesh.load(path, force='scene', process=False)
    parts = []
    for node in sorted(scene.graph.nodes_geometry):
        transform, name = scene.graph[node]
        mesh = scene.geometry[name].copy()
        mesh.apply_transform(transform)
        parts.append(mesh)
    if not parts:
        raise ValueError(f'No meshes: {path}')
    return parts


def normalize_parts(parts, asset_up):
    if asset_up not in ('y', 'z'):
        raise ValueError('An explicit asset up axis is required')
    vertices = np.concatenate([m.vertices for m in parts])
    lower, upper = vertices.min(0), vertices.max(0)
    diagonal = float(np.linalg.norm(upper-lower))
    if not np.isfinite(vertices).all() or diagonal <= 0:
        raise ValueError('Invalid asset bounds')
    rotation = np.eye(3) if asset_up == 'z' else np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
    transform = np.eye(4)
    transform[:3, :3] = rotation/diagonal
    transform[:3, 3] = -rotation@((lower+upper)/2)/diagonal
    normalized = [m.copy() for m in parts]
    for mesh in normalized:
        mesh.apply_transform(transform)
    return normalized, transform, diagonal


def make_camera(azimuth, elevation=20., resolution=1024, fov=40., radius=.5):
    azimuth, elevation = np.deg2rad([azimuth, elevation])
    # Bounding sphere radius <= 0.5 after asset-space diagonal normalization.
    distance = radius / np.sin(np.deg2rad(fov/2)) * 1.2
    eye = distance*np.array([np.cos(elevation)*np.cos(azimuth), np.cos(elevation)*np.sin(azimuth), np.sin(elevation)])
    forward = -eye/np.linalg.norm(eye)
    right = np.cross(forward, [0, 0, 1]); right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    transform = np.eye(4)
    transform[:3, :3] = np.stack([right, down, forward])
    transform[:3, 3] = -transform[:3, :3]@eye
    focal = resolution/(2*np.tan(np.deg2rad(fov/2)))
    intrinsics = np.array([[focal, 0, resolution/2], [0, focal, resolution/2], [0, 0, 1]])
    return dict(K=intrinsics.tolist(), T_world_to_camera=transform.tolist(), resolution=resolution,
                near=.01, far=10., distance=float(distance), horizontal_fov_degrees=fov,
                azimuth_degrees=float(np.rad2deg(azimuth)), elevation_degrees=float(np.rad2deg(elevation)),
                camera_frame='right-down-forward', pixel_centers='x+0.5,y+0.5')


class Rasterizer:
    def __init__(self, device='cuda', max_faces_per_pass=1_000_000):
        import torch
        import nvdiffrast.torch as dr
        self.torch, self.dr, self.device = torch, dr, device
        self.context = dr.RasterizeCudaContext(device=device)
        if max_faces_per_pass <= 0:
            raise ValueError('max_faces_per_pass must be positive')
        self.max_faces_per_pass = max_faces_per_pass

    def render(self, parts, K, world_to_camera, resolution, near=.01, far=10., texture=True, normal_mode="vertex"):
        """Row 0 is the top of the saved image. Depth is camera Z, never NDC/ray length.

        Rasterize both face orientations. No scene light: stored texture RGB under
        constant unit ambient illumination, no tone mapping or color-space conversion.
        Alpha/mask and depth use center samples; no depth interpolation across edges.
        """
        if normal_mode not in ("vertex", "face"):
            raise ValueError("normal_mode must be vertex or face")
        torch, dr = self.torch, self.dr
        K = np.asarray(K, dtype=np.float64)
        T = np.asarray(world_to_camera, dtype=np.float64)
        rgba = np.zeros((resolution, resolution, 4), np.uint8)
        depth = np.full((resolution, resolution), np.inf, np.float32)
        normals = np.zeros((resolution, resolution, 3), np.float32)
        for mesh in parts:
            xyz = np.asarray(mesh.vertices)@T[:3, :3].T+T[:3, 3]
            z = xyz[:, 2]
            clip = np.stack([2*K[0, 0]/resolution*xyz[:, 0]+(2*K[0, 2]/resolution-1)*z,
                             2*K[1, 1]/resolution*xyz[:, 1]+(2*K[1, 2]/resolution-1)*z,
                             (far+near)/(far-near)*z-2*far*near/(far-near), z], axis=-1)
            vertices = torch.as_tensor(clip, dtype=torch.float32, device=self.device)[None].contiguous()
            attr = xyz[:, 2:3]
            if normal_mode == "vertex":
                attr = np.concatenate([attr, np.asarray(mesh.vertex_normals)@T[:3, :3].T], axis=1)
            attributes = torch.as_tensor(attr, dtype=torch.float32, device=self.device)[None].contiguous()
            uv = pixels_gpu = colors_gpu = None
            if texture and hasattr(mesh.visual, 'uv') and mesh.visual.uv is not None:
                material = mesh.visual.material
                image = getattr(material, 'image', None)
                if image is None:
                    image = getattr(material, 'baseColorTexture', None)
                if image is None:
                    raise ValueError('Textured mesh has no readable base color image')
                # OBJ UV v=0 is bottom; tensor row zero follows the image array.
                pixels = np.asarray(image.convert('RGB'), dtype=np.float32)[::-1].copy()/255
                uv = torch.as_tensor(np.array(mesh.visual.uv), dtype=torch.float32, device=self.device)[None].contiguous()
                pixels_gpu = torch.as_tensor(pixels, device=self.device)[None]
            elif texture and hasattr(mesh.visual, 'vertex_colors'):
                colors = np.asarray(mesh.visual.vertex_colors)[:, :3].astype(np.float32)/255
                colors_gpu = torch.as_tensor(colors, device=self.device)[None].contiguous()
            # Dense decoder outputs may exceed CUDA rasterizer triangle limits.
            # Render every face in bounded passes and merge by nearest camera Z;
            # no simplification, changed camera, or dropped geometry is involved.
            for start in range(0, len(mesh.faces), self.max_faces_per_pass):
                faces = torch.as_tensor(np.array(mesh.faces[start:start+self.max_faces_per_pass]),
                                        dtype=torch.int32, device=self.device).contiguous()
                rast, _ = dr.rasterize(self.context, vertices, faces, resolution=[resolution, resolution])
                interpolated, _ = dr.interpolate(attributes, rast, faces)
                values = interpolated[0].cpu().numpy()
                mask = (rast[0, ..., 3] > 0).cpu().numpy() & (values[..., 0] < depth)
                if pixels_gpu is not None:
                    uv_image, _ = dr.interpolate(uv, rast, faces)
                    color = dr.texture(pixels_gpu, uv_image, filter_mode='linear', boundary_mode='wrap')[0].cpu().numpy()
                elif colors_gpu is not None:
                    color, _ = dr.interpolate(colors_gpu, rast, faces)
                    color = color[0].cpu().numpy()
                else:
                    color = np.full((resolution, resolution, 3), .7, np.float32)
                depth[mask] = values[..., 0][mask]
                rgba[mask, :3] = np.clip(color[mask]*255, 0, 255).astype(np.uint8)
                rgba[mask, 3] = 255
                if normal_mode == "face":
                    triangle_ids = rast[0, ..., 3].cpu().numpy()[mask].astype(np.int64) - 1 + start
                    triangles = xyz[np.asarray(mesh.faces)[triangle_ids]]
                    n = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
                else:
                    n = values[..., 1:4][mask]
                n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-12)
                normals[mask] = n
        mask = np.isfinite(depth)
        depth[~mask] = 0
        return rgba, depth, mask, normals
