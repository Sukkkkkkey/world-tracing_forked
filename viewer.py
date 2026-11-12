"""Browser viewer for an image, predicted points, optional mesh, ground truth and TRELLIS output.

Uses a single-port Viser web viewer; no GPU or model weights are needed.
Example (in the project environment):
    python viewer.py --image input.png --points prediction.rrd --mesh mesh.glb
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import json
import signal
import threading
import time
import textwrap

import numpy as np
from PIL import Image
import trimesh
import viser
from viewer_utils.glb import GRAY, depth_colors, prepare_glb, UnsupportedGLB
from viewer_utils.mesh import (LocalResolver, obj_stream, is_mesh_file,
                         split_materials, resource_signature, prepare_export_textures)
from viewer_utils.gso import gso_display_source
from viewer_utils.experiments import experiment_layout, scan_viewer_experiment, seed_options

from wt.experiment import resolve_reference


# Display budgets only: exported results and evaluation data are never modified.
QUALITY = {'fast': (20_000, 50_000, 512), 'balanced': (50_000, None, 1024),
           'full': (0, None, None)}  # points (0=all), mesh preview threshold, texture edge
COLOR_MODES = {'灰色': 'gray', '表面颜色': 'surface', '深度': 'depth'}
COLOR_HINT = ('灰色保留已有纹理，无纹理填灰；表面颜色仅将输入 RGB 映射到 WT layer-0，'
              '后层灰色。深度：各结果按显示坐标 −Z 独立归一化，近蓝远红；不随视角旋转改变。')
SELECT_SAMPLE = '(select a sample)'


class LoadCancelled(Exception):
    pass


class ProgressFile:
    """Report actual bytes read; the caller separately reports parsing/packing stages."""
    def __init__(self, stream, size, progress):
        self.stream, self.size, self.progress = stream, max(size, 1), progress
        self.read_bytes = 0

    def read(self, size=-1):
        chunks = []
        remaining = self.size if size < 0 else size
        while remaining:
            block = self.stream.read(min(remaining, 4 * 1024 * 1024))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
            self.read_bytes += len(block)
            self.progress(0.05 + 0.4 * min(self.read_bytes / self.size, 1),
                          'Reading mesh bytes' if self.read_bytes < self.size else 'Decoding mesh (read complete)')
        return b''.join(chunks)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def read_rrd(path: Path, entity: str | None = None):
    """Read the latest snapshot of one point entity, preferring WT's combined cloud."""
    import rerun.dataframe as rdf

    recording = rdf.load_recording(path)
    schema = recording.schema()
    positions = [c for c in schema.component_columns() if c.component_name.endswith('.Position3D')]
    candidates = [c for c in positions if c.entity_path.endswith('/pointcloud/all')] or positions
    if entity:
        candidates = [c for c in positions if c.entity_path == '/' + entity.strip('/')]
    if len(candidates) != 1:
        raise ValueError(f"Choose an RRD entity with --entity / --gt-entity / --trellis-entity: {[c.entity_path for c in candidates]}")
    position = candidates[0]
    color = schema.column_for(position.entity_path, 'Color')
    columns = [position] + ([color] if color is not None else [])
    indexes = [c.name for c in schema.index_columns()]
    index = 'log_time' if 'log_time' in indexes else (indexes[0] if indexes else 'log_time')
    view = recording.view(index=index, contents=position.entity_path).fill_latest_at()
    table = (view.select_static(*columns) if position.is_static else view.select(*columns)).read_all()
    if not table.num_rows or not table.column(0)[-1].is_valid:
        raise ValueError(f"No points in {path}: {position.entity_path}")
    xyz = np.asarray(table.column(0)[-1].as_py(), dtype=np.float32)
    colors = None
    if color is not None and table.column(1)[-1].is_valid:
        packed = np.asarray(table.column(1)[-1].as_py(), dtype=np.uint32)
        colors = ((packed[:, None] >> np.array([24, 16, 8, 0])) & 255).astype(np.uint8)
    print(f"RRD: {position.entity_path}, latest snapshot ({len(xyz):,} points)", flush=True)
    return xyz, colors, None


def read_points(path: Path, entity: str | None = None):
    """NPZ keys: xyz/xyz_pred/points, optional mask/mask_pred and colors/rgb."""
    suffix = path.suffix.lower()
    if suffix == '.rrd':
        return read_rrd(path, entity)
    if suffix == '.npy':
        return np.load(path, allow_pickle=False), None, None
    if suffix == '.npz':
        with np.load(path, allow_pickle=False) as data:
            xyz_key = next((key for key in ('xyz', 'xyz_pred', 'points') if key in data), None)
            if xyz_key is None:
                raise ValueError(f"{path}: expected xyz, xyz_pred or points")
            color = next((data[key] for key in ('colors', 'rgb') if key in data), None)
            mask = next((data[key] for key in ('mask', 'mask_pred') if key in data), None)
            return data[xyz_key], color, mask
    if suffix == '.ply':
        cloud = trimesh.load(path, process=False)
        if isinstance(cloud, trimesh.points.PointCloud):
            color = cloud.colors
        elif cloud.visual.kind == 'texture' and cloud.visual.uv is not None:
            color = cloud.visual.material.to_color(cloud.visual.uv)
        else:
            color = cloud.visual.vertex_colors
        return np.asarray(cloud.vertices), color, None
    raise ValueError(f"Unsupported point file: {path.suffix}; use .rrd/.npy/.npz/.ply")


def prepare_points(xyz, colors=None, mask=None, max_points=50_000, *, color_mode='surface', wt=False):
    """Flatten one static cloud/layer stack, filter invalid points, then sample deterministically."""
    xyz = np.asarray(xyz, dtype=np.float32)
    if xyz.ndim not in (2, 3, 4) or xyz.shape[-1] != 3:
        raise ValueError('Expected points [N,3], [H,W,3] or [L,H,W,3]; select a batch/frame first')
    valid = np.isfinite(xyz).all(axis=-1)
    if mask is not None:
        valid &= np.broadcast_to(np.asarray(mask, dtype=bool), valid.shape)
    # An HxW RGB image is observation of layer 0, never texture for hidden layers.
    if color_mode == 'depth' or (wt and (color_mode != 'surface' or xyz.ndim < 3)):
        colors = None
    if colors is None:
        colors = np.array(GRAY, dtype=np.uint8)
    colors = np.asarray(colors)
    if colors.ndim == 0 or colors.shape[-1] not in (3, 4):
        raise ValueError('Colors must end in RGB or RGBA channels')
    if xyz.ndim == 4 and (wt or colors.ndim == 3):
        layer_colors = np.full((*xyz.shape[:-1], 3), GRAY, dtype=np.uint8)
        first = colors[0] if colors.ndim == 4 else colors
        if np.issubdtype(first.dtype, np.floating) and first.size and first.max() <= 1:
            first = first * 255
        if not np.isfinite(first).all():
            raise ValueError('Colors contain NaN or infinity')
        layer_colors[0] = np.clip(first[..., :3], 0, 255).astype(np.uint8)
        colors = layer_colors[valid]
    else:
        colors = np.broadcast_to(colors, (*xyz.shape[:-1], colors.shape[-1]))[valid]
    if not np.isfinite(colors).all():
        raise ValueError('Colors contain NaN or infinity')
    if np.issubdtype(colors.dtype, np.floating) and colors.size and colors.max() <= 1:
        colors = colors * 255
    colors = np.clip(colors, 0, 255).astype(np.uint8)
    points = xyz[valid]
    if not len(points):
        raise ValueError('No finite, unmasked points to display')
    if max_points and len(points) > max_points:
        sample = np.random.default_rng(42).choice(len(points), max_points, replace=False)
        points, colors = points[sample], colors[sample]
    return points, colors


@dataclass
class Geometry:
    name: str
    bounds: np.ndarray
    points: np.ndarray | None = None
    colors: np.ndarray | None = None
    glb: bytes | None = None
    resources: tuple = ()
    notices: tuple = ()


def display_transform(frame):
    rotations = {'camera_rdf': np.diag([1., -1., -1.]),
                 'pixal3d_yup': np.diag([-1., 1., -1.]),
                 'canonical_zup': np.array([[1., 0, 0], [0, 0, 1.], [0, -1., 0]]),
                 'gltf_yup': np.eye(3)}
    if frame not in rotations:
        raise ValueError(f'Unknown coordinate frame: {frame}')
    result = np.eye(4)
    result[:3, :3] = rotations[frame]
    return result


def read_geometry(name: str, path: Path, *, entity=None, max_points=50_000, mesh=None,
                  frame=None, transform=None, quality='balanced', progress=None,
                  color_mode='gray', wt=False, input_rgb=None):
    """Read geometry in display Y-up coordinates; never modify the source file."""
    progress = progress or (lambda *_: None)
    progress(0, f'Opening {path.name} ({path.stat().st_size / 2**20:.1f} MiB)')
    _, max_faces, texture_edge = QUALITY[quality]
    if color_mode not in COLOR_MODES.values():
        raise ValueError(f'Unknown color mode: {color_mode}')
    if mesh is True or (mesh is None and not wt and is_mesh_file(path)):
        transform = display_transform(frame or 'gltf_yup') if transform is None else transform
        if path.suffix.lower() == '.glb' and max_faces is None:
            with path.open('rb') as stream:
                data = ProgressFile(stream, path.stat().st_size, progress).read()
            try:
                bounds, glb = prepare_glb(data, transform, texture_edge, color_mode, progress)
                progress(1, 'Mesh ready (original topology)')
                return Geometry(name, bounds, glb=glb)
            except UnsupportedGLB:
                pass  # Other formats/layouts use the general loader below.
        resolver = LocalResolver(path)
        with path.open('rb') as stream:
            source = ProgressFile(stream, path.stat().st_size, progress)
            if path.suffix.lower() == '.obj' and color_mode != 'depth':
                source = obj_stream(source, resolver)
            scene = trimesh.load(source,
                file_type=path.suffix[1:].lower(), resolver=resolver,
                force='scene', process=False, skip_materials=color_mode == 'depth')
        scene = split_materials(scene)
        resources = resource_signature(resolver.paths)
        notices = tuple(dict.fromkeys(resolver.errors))
        progress(0.55, 'Preparing mesh geometry')
        if not scene.geometry or not any(len(getattr(g, 'faces', [])) for g in scene.geometry.values()):
            raise ValueError(f"No mesh faces in {path}")
        scene.apply_transform(transform)
        bounds = np.asarray(scene.bounds)
        if not np.isfinite(bounds).all():
            raise ValueError(f"Non-finite mesh bounds in {path}")
        face_count = sum(len(getattr(scene.geometry[scene.graph[node][1]], 'faces', []))
                         for node in scene.graph.nodes_geometry)
        if max_faces is not None and face_count > max_faces:
            # Bounded vertex preview avoids transferring millions of faces. Keep
            # UV colors and scene-node poses; do not randomly drop mesh triangles.
            progress(0.65, f'Creating vertex preview ({face_count:,} faces)')
            nodes = list(scene.graph.nodes_geometry)
            counts = np.array([len(scene.geometry[scene.graph[n][1]].vertices) for n in nodes])
            picks = np.sort(np.random.default_rng(42).choice(int(counts.sum()),
                min(max_points or int(counts.sum()), int(counts.sum())), replace=False))
            vertices, colors, start = [], [], 0
            for node, count in zip(nodes, counts):
                pose, key = scene.graph[node]
                geometry = scene.geometry[key]
                indices = picks[(picks >= start) & (picks < start + count)] - start
                start += count
                if not len(indices):
                    continue
                vertices.append(trimesh.transform_points(geometry.vertices[indices], pose))
                visual = geometry.visual
                if color_mode == 'depth':
                    color = depth_colors(-vertices[-1][:, 2], (-bounds[1, 2], -bounds[0, 2]))
                elif visual.kind == 'texture' and visual.uv is not None:
                    color = visual.material.to_color(visual.uv[indices])[:, :3]
                elif visual.kind in ('vertex', 'face'):
                    color = visual.vertex_colors[indices, :3]
                else:
                    color = np.tile(GRAY, (len(indices), 1))
                colors.append(color)
            progress(1, 'Vertex preview ready')
            return Geometry(name + f' [vertex preview; {face_count:,} faces]', bounds,
                            np.vstack(vertices), np.vstack(colors), resources=resources, notices=notices)
        if color_mode == 'depth':
            colored = trimesh.Scene()
            for node in scene.graph.nodes_geometry:
                pose, key = scene.graph[node]
                geometry = scene.geometry[key].copy()
                depth = -(geometry.vertices @ pose[2, :3] + pose[2, 3])
                geometry.visual = trimesh.visual.ColorVisuals(geometry,
                    vertex_colors=depth_colors(depth, (-bounds[1, 2], -bounds[0, 2])))
                colored.add_geometry(geometry, transform=pose, node_name=node)
            scene = colored
        else:
            for geometry in scene.geometry.values():
                visual = geometry.visual
                if visual.kind is None or (visual.kind == 'texture' and not any(
                    isinstance(getattr(visual.material, f, None), Image.Image) for f in ('image', 'baseColorTexture'))):
                    geometry.visual = trimesh.visual.ColorVisuals(geometry, vertex_colors=GRAY)
        if texture_edge is not None and color_mode != 'depth':
            for geometry in scene.geometry.values():
                material = getattr(geometry.visual, 'material', None)
                for field in ('image', 'baseColorTexture', 'normalTexture', 'metallicRoughnessTexture',
                              'occlusionTexture', 'emissiveTexture'):
                    texture = getattr(material, field, None)
                    if isinstance(texture, Image.Image) and max(texture.size) > texture_edge:
                        texture = texture.copy()
                        texture.thumbnail((texture_edge, texture_edge), Image.Resampling.LANCZOS)
                        setattr(material, field, texture)
        progress(0.85, 'Packing mesh and textures')
        # Preserve scene-node transforms and repack WebP textures as PNG in memory.
        def material_policy(tree):
            if color_mode == 'depth':
                tree['extensionsUsed'] = sorted(set(tree.get('extensionsUsed', [])) | {'KHR_materials_unlit'})
                tree['materials'] = [{'pbrMetallicRoughness': {'baseColorFactor': [1, 1, 1, 1],
                    'metallicFactor': 0, 'roughnessFactor': 1}, 'doubleSided': True,
                    'extensions': {'KHR_materials_unlit': {}}}]
                for mesh in tree.get('meshes', []):
                    for primitive in mesh['primitives']:
                        primitive['material'] = 0
        prepare_export_textures(scene)
        result = Geometry(name, bounds, glb=scene.export(file_type='glb', extension_webp=False,
                                                       tree_postprocessor=material_policy),
                          resources=resources, notices=notices)
        progress(1, 'Mesh ready')
        return result
    progress(0.1, 'Reading point arrays')
    xyz, colors, mask = read_points(path, entity)
    if wt and colors is None and input_rgb is not None and xyz.ndim in (3, 4):
        # Only use exact pixel correspondence; never resize/crop an unregistered image.
        if input_rgb.shape[:2] == xyz.shape[-3:-1]:
            colors = input_rgb[..., :3]
    if wt and color_mode == 'surface' and (xyz.ndim < 3 or colors is None):
        name += ' [no layer-0 RGB correspondence; gray]'
    points, colors = prepare_points(xyz, colors, mask, max_points=max_points, color_mode=color_mode, wt=wt)
    progress(0.8, 'Preparing point colors and coordinates')
    transform = display_transform(frame or 'camera_rdf') if transform is None else transform
    points = points @ transform[:3, :3].T + transform[:3, 3]
    if color_mode == 'depth':
        valid = np.isfinite(xyz).all(axis=-1)
        if mask is not None:
            valid &= np.broadcast_to(np.asarray(mask, dtype=bool), valid.shape)
        raw_depth = -(xyz[valid] @ transform[2, :3] + transform[2, 3])
        colors = depth_colors(-points[:, 2], (raw_depth.min(), raw_depth.max()))
    print(f'{name}: displaying {len(points):,} points', flush=True)
    result = Geometry(name, np.stack((points.min(0), points.max(0))), points, colors[:, :3])
    progress(1, 'Points ready')
    return result


def add_camera_controls(server):
    """Persistent canvas-corner controls, scoped to each browser's camera."""
    @server.on_client_connect
    def connected(client):
        panel = client.gui.add_panel()
        with panel.add_tab('视角控制'):
            zoom = client.gui.add_button_group('缩放', ('−', '＋'), hint='放大 / 缩小，每次约 20%')
            pan = client.gui.add_button_group('平移', ('←', '→', '↑', '↓'), hint='沿当前屏幕方向移动视点')
            orbit = client.gui.add_button_group('旋转', ('←', '→', '↑', '↓'), hint='绕观察中心旋转，每次 15°')
        panel.float(x=12, y=12, width=260)

        # Handle clicks on the event loop so rapid button values cannot overtake
        # their callbacks in Viser's worker pool. No blocking work or awaits here.
        async def move(event):
            from viser.transforms import SO3

            with client.atomic():
                camera = client.camera
                position = camera.position.copy()
                target = camera.look_at.copy()
                offset = position - target
                distance = float(np.linalg.norm(offset))
                if distance < 1e-10:
                    return
                basis = SO3(camera.wxyz).as_matrix()
                right, up = basis[:, 0], -basis[:, 1]
                direction = event.target.value
                if event.target is zoom:
                    minimum = max(camera.near * 2, camera.min_orbit_distance, 1e-6)
                    maximum = max(minimum, min(camera.far * 0.8, camera.max_orbit_distance))
                    next_distance = np.clip(distance * (0.8 if direction == '＋' else 1.25), minimum, maximum)
                    camera.position = target + offset * (next_distance / distance)
                    # Viser's position setter also translates look_at: restore the pivot.
                    camera.look_at = target
                elif event.target is pan:
                    shift = {'←': -right, '→': right, '↑': up, '↓': -up}[direction] * distance * 0.1
                    camera.position = position + shift
                    camera.look_at = target + shift
                else:
                    axis = up if direction in ('←', '→') else right
                    angle = np.deg2rad(15 if direction in ('←', '↓') else -15)
                    rotation = SO3.exp(axis * angle).as_matrix()
                    camera.position = target + rotation @ offset
                    camera.look_at = target
                    camera.up_direction = rotation @ up
            client.flush()

        for buttons in (zoom, pan, orbit):
            buttons.on_click(move)


def scene_caption(name):
    """Keep full provenance in View; wrap only the canvas annotation."""
    title = name.split(' [', 1)[0]
    return '\n'.join(line for part in title.split(' / ')
                     for line in textwrap.wrap(part, width=24))


def fitted_camera(bounds, fov, aspect):
    """Fit a front view to the display bounds using the client's actual frustum."""
    bounds = np.asarray(bounds, dtype=float)
    target = bounds.mean(axis=0)
    half = (bounds[1] - bounds[0]) / 2
    tangent = np.tan(fov / 2)
    distance = max(float(half[2] + 1.15 * max(half[1] / tangent,
                                             half[0] / (tangent * aspect))), 0.1)
    return target, target + np.array([0., 0., distance]), distance


def populate_viewer(server, image, geometries, input_views=None):
    """Arrange results in a centered grid at original scale, with a single-result selector."""
    server.scene.set_up_direction('+y')
    server.scene.world_axes.visible = False
    if input_views:
        input_choice = server.gui.add_dropdown('Input / configuration', options=tuple(input_views))
        preview, details = input_views[input_choice.value]
        input_image = server.gui.add_image(preview, label=input_choice.value, format='png')
        input_details = server.gui.add_markdown(details)

        @input_choice.on_update
        def change_input(_):
            preview, details = input_views[input_choice.value]
            input_image.image = preview
            input_image.label = input_choice.value
            input_details.content = details
    elif image is not None:
        server.gui.add_image(image, label='Input image', format='png')
    selection = server.gui.add_dropdown('View', options=['All', *(g.name for g in geometries)])
    size = server.gui.add_slider('Point size', min=0.25, max=4.0, step=0.25, initial_value=1.0)
    server.gui.add_markdown('Results are arranged in a grid at original scale; no registration is applied.')
    if not geometries:
        server.gui.add_markdown('No completed geometry for this selection.')
        return
    extents = np.array([g.bounds[1] - g.bounds[0] for g in geometries])
    gap = max(float(extents.max()) * 0.25, 0.01)
    captions = [scene_caption(g.name) for g in geometries]
    font_height = max(float(extents.max()) * 0.055, 1e-5)
    caption_heights = [(caption.count('\n') + 1) * font_height * 1.3 for caption in captions]
    columns = int(np.ceil(np.sqrt(len(geometries))))
    rows = (len(geometries) + columns - 1) // columns
    # Uniform cells retain original scale and leave room for labels. Center an
    # incomplete final row instead of leaving all its empty cells on one side.
    cell_width, cell_height = extents[:, :2].max(axis=0) + gap
    cell_height += max(caption_heights)
    entries = []
    clouds = []
    for i, (geometry, extent) in enumerate(zip(geometries, extents)):
        row, column = divmod(i, columns)
        row_count = min(columns, len(geometries) - row * columns)
        center = np.array([(column - (row_count - 1) / 2) * cell_width,
                           ((rows - 1) / 2 - row) * cell_height, 0.0])
        root = f'/result_{i}'
        frame = server.scene.add_frame(root, show_axes=False, position=center)
        offset = -geometry.bounds.mean(0)
        if geometry.glb is not None:
            server.scene.add_glb(f'{root}/mesh', geometry.glb, position=offset)
        else:
            base_size = max(float(extent.max()) / 300, 1e-5)
            cloud = server.scene.add_point_cloud(f'{root}/points', geometry.points + offset,
                colors=geometry.colors, point_size=base_size, precision='float32', point_shape='circle')
            clouds.append((cloud, base_size))
        server.scene.add_label(f'{root}/label', captions[i],
            position=(0, extent[1] / 2 + gap / 3, 0), anchor='bottom-center',
            font_size_mode='scene', font_scene_height=font_height)
        # Include the annotation in framing, not just the geometry underneath.
        label_width = max(map(len, captions[i].splitlines()), default=0) * font_height * 0.7
        half_width = max(extent[0], label_width) / 2
        display_bounds = center + np.array([
            [-half_width, -extent[1] / 2, -extent[2] / 2],
            [half_width, extent[1] / 2 + gap / 3 + caption_heights[i], extent[2] / 2]])
        entries.append((geometry.name, frame, display_bounds))

    def fit_view(_=None):
        visible_bounds = []
        for name, frame, bounds in entries:
            frame.visible = selection.value in ('All', name)
            if frame.visible:
                visible_bounds.extend(bounds)
        visible_bounds = np.asarray(visible_bounds)
        bounds = np.stack((visible_bounds.min(0), visible_bounds.max(0)))

        def apply(camera, aspect):
            target, position, distance = fitted_camera(bounds, camera.fov, aspect)
            camera.position = position
            camera.look_at = target
            camera.up_direction = (0, 1, 0)
            camera.near = max(distance / 10000, 1e-5)
            camera.far = max(distance * 10, 100)

        apply(server.initial_camera, 1.0)
        for client in server.get_clients().values():
            with client.atomic():
                apply(client.camera, client.camera.aspect)

    @size.on_update
    def resize_points(_):
        for cloud, base_size in clouds:
            cloud.point_size = base_size * size.value

    selection.on_update(fit_view)
    server.gui.add_button('Reset view').on_click(fit_view)
    fit_view()


def read_run_geometry(run, *, max_points=50_000, restore_camera=True, artifact_key='mesh',
                      quality='balanced', progress=None, color_mode='gray'):
    """A complete run declares its coordinate frame; never infer hybrid pose from a filename."""
    artifacts = run.data.get('artifacts', {})
    key = 'points' if run.method == 'wt' else artifact_key
    artifact = artifacts[key]
    frame = artifact['frame']
    transform = display_transform(frame)
    label = f'{run.label} [{frame}]'
    if restore_camera and run.method == 'wt_trellis2':
        if 'metadata' not in artifact:
            raise ValueError('Hybrid is missing coordinate metadata; disable Restore WT frame to view native output')
        metadata = json.loads(resolve_reference(run.directory, artifact['metadata']).read_text())
        from wt.textured_mesh.canon import CanonicalTransform, canon_inverse, glb_to_camera
        tf = CanonicalTransform(**metadata['canonical_transform'])
        basis = np.vstack((np.zeros(3), np.eye(3)))
        if frame == 'gltf_yup':
            camera = glb_to_camera(basis, tf)
        elif frame == 'canonical_zup':
            camera = canon_inverse(basis, tf)
        else:
            raise ValueError(f'Hybrid restoration not defined for {frame}')
        inverse = np.eye(4)
        inverse[:3, :3] = (camera[1:] - camera[0]).T
        inverse[:3, 3] = camera[0]
        transform = display_transform('camera_rdf') @ inverse
        label = f'{run.label} [WT camera; own upstream]'
    return read_geometry(label, resolve_reference(run.directory, artifact['path']),
                         mesh=artifact['kind'] == 'mesh', max_points=max_points,
                         frame=frame, transform=transform, quality=quality, progress=progress,
                         color_mode=color_mode, wt=run.method == 'wt')


class MultiSelect:
    """Collapsible checkbox selection using Viser's public GUI API."""
    def __init__(self, gui, label, options, lock, initial_value=None):
        self.gui, self.label, self.lock = gui, label, lock
        self.checkboxes = {}
        self.callbacks = []
        self.updating = False
        self.follow_all = initial_value is None
        self.folder = gui.add_folder(label, expand_by_default=False)
        with self.folder:
            actions = gui.add_button_group('选择', ('全选', '清空'))
        actions.on_click(self._choose)
        self.set_options(options)
        if initial_value is not None:
            self.value = initial_value

    @property
    def options(self):
        return tuple(self.checkboxes)

    @property
    def value(self):
        with self.lock:
            return tuple(key for key, checkbox in self.checkboxes.items() if checkbox.value)

    @value.setter
    def value(self, selected):
        if isinstance(selected, str):
            raise ValueError('Multi-select value must be a sequence of options, not a string')
        selected = set(selected)
        with self.lock:
            if not selected.issubset(self.options):
                raise ValueError(f'Unknown {self.label} options: {selected.difference(self.options)}')
            self.updating = True
            try:
                for key, checkbox in self.checkboxes.items():
                    checkbox.value = key in selected
            finally:
                self.updating = False
            self._changed()

    def on_update(self, callback):
        self.callbacks.append(callback)

    def _changed(self, event=None):
        with self.lock:
            if self.updating:
                return
            self.follow_all = bool(self.options) and len(self.value) == len(self.options)
            self.folder.label = f'{self.label}（多选 {len(self.value)}/{len(self.options)}）'
            for callback in self.callbacks:
                callback(event)

    def _choose(self, event):
        with self.lock:
            self.value = self.options if event.target.value == '全选' else ()
            self.follow_all = event.target.value == '全选'

    def set_options(self, options):
        """Keep subsets/empty selections; an all-selection includes new options."""
        with self.lock:
            selected, follow_all = set(self.value), self.follow_all
            for checkbox in self.checkboxes.values():
                checkbox.remove()
            with self.folder:
                self.checkboxes = {key: self.gui.add_checkbox(key,
                    initial_value=follow_all or key in selected) for key in options}
            for checkbox in self.checkboxes.values():
                checkbox.on_update(self._changed)
            self._changed()
            if not self.options:
                self.follow_all = follow_all


class ExperimentViewer:
    """One shared browser selection, small manifest index, bounded on-demand geometry loading."""
    def __init__(self, server, root, max_points=None, quality='full', color_mode='surface'):
        self.server, self.root, self.max_points = server, Path(root), max_points
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.version = 0
        self.pending = None
        self.closed = False
        self.cache = OrderedDict()
        self.folder = None
        self.samples, self.runs, self.errors = scan_viewer_experiment(self.root)
        server.gui.add_markdown(f'**{experiment_layout(self.root)}:** {self.root.name}')
        self.sample = server.gui.add_dropdown('Sample', options=(SELECT_SAMPLE, *self.samples))
        self.method = MultiSelect(server.gui, 'Method', sorted({r.method for r in self.runs}), self.lock)
        config_ids = sorted({r.config_id for r in self.runs})
        self.config = MultiSelect(server.gui, 'Config', config_ids, self.lock)
        seeds = seed_options(self.runs)
        self.seed = MultiSelect(server.gui, 'Seed', seeds, self.lock, initial_value=seeds[:1] if seeds else None)
        self.restore = server.gui.add_checkbox('Restore WT frame', initial_value=True)
        self.show_gt = server.gui.add_checkbox('Show ground truth', initial_value=True)
        self.quality = server.gui.add_dropdown('Display quality', options=tuple(QUALITY), initial_value=quality)
        self.color = server.gui.add_dropdown('Color mode', options=tuple(COLOR_MODES),
            initial_value=next(label for label, value in COLOR_MODES.items() if value == color_mode))
        server.gui.add_markdown(COLOR_HINT)
        self.artifact = server.gui.add_dropdown('Mesh representation', options=('Exported GLB', 'Decoded mesh'))
        self.progress = server.gui.add_progress_bar(0)
        self.status = server.gui.add_markdown('')
        server.gui.add_markdown('Selections are shared across connected browsers. TRELLIS stays in its native frame; no GT alignment is performed.')
        server.gui.add_button('Previous sample').on_click(lambda _: self.move(-1))
        server.gui.add_button('Next sample').on_click(lambda _: self.move(1))
        server.gui.add_button('Refresh results').on_click(self.refresh)
        for control in (self.sample, self.method, self.config, self.seed, self.restore, self.show_gt, self.artifact, self.quality, self.color):
            control.on_update(self.render)
        self.worker = threading.Thread(target=self._worker, name='viewer-loader', daemon=True)
        self.worker.start()
        self.render()

    def close(self):
        with self.condition:
            self.closed = True
            self.version += 1
            self.condition.notify_all()
        self.worker.join(timeout=2)

    def move(self, offset):
        # Viser dispatches synchronous button callbacks on multiple threads.
        # Keep read/advance/write atomic with refresh and other navigation.
        with self.lock:
            options = tuple(self.samples)
            if not options:
                return
            current = self.sample.value
            if current == SELECT_SAMPLE:
                self.sample.value = options[0 if offset > 0 else -1]
                return
            self.sample.value = options[(options.index(current) + offset) % len(options)]

    def refresh(self, _=None):
        with self.lock:
            try:
                self.samples, self.runs, self.errors = scan_viewer_experiment(self.root)
            except (OSError, ValueError) as exc:
                self.status.content = f'Refresh failed: {exc}'
                return
            value = self.sample.value
            self.sample.options = (SELECT_SAMPLE, *self.samples)
            self.sample.value = value if value in self.sample.options else SELECT_SAMPLE
            self.method.set_options(sorted({r.method for r in self.runs}))
            self.config.set_options(sorted({r.config_id for r in self.runs}))
            self.seed.set_options(seed_options(self.runs))
            self.render()

    def render(self, _=None):
        """Snapshot controls quickly; one worker loads only the newest request."""
        with self.condition:
            if self.closed:
                return
            self.version += 1
            if self.sample.value == SELECT_SAMPLE:
                self.pending = None
                self.server.scene.reset()
                if self.folder is not None:
                    self.folder.remove()
                    self.folder = None
                self.progress.value = 0
                self.progress.animated = False
                self.status.content = 'Select a sample to load its image, matching results and ground truth. No geometry is loaded yet.'
                self.server.flush()
                return
            selected = [r for r in self.runs if r.sample_id == self.sample.value
                        and r.method in self.method.value
                        and r.config_id in self.config.value
                        and str(r.seed) in self.seed.value]
            self.pending = (self.version, self.sample.value, dict(self.samples.get(self.sample.value, {})),
                            selected, self.restore.value, self.show_gt.value, self.artifact.value,
                            self.quality.value, list(self.errors), COLOR_MODES[self.color.value])
            self.progress.value = 0
            self.progress.animated = True
            self.status.content = 'Preparing 0% — queued (latest selection only)'
            # Never leave the previous sample visible under a new selection.
            self.server.scene.reset()
            if self.folder is not None:
                self.folder.remove()
                self.folder = None
            self.server.flush()
            self.condition.notify()

    def _worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                request, self.pending = self.pending, None
            try:
                self._load(request)
            except LoadCancelled:
                pass
            except Exception as exc:
                with self.lock:
                    if not self.closed and request[0] == self.version:
                        self.progress.animated = False
                        self.status.content = f'Loading failed: {exc}'

    def _cached(self, paths, options, loader, report):
        key = (tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths), options)
        with self.lock:
            if key in self.cache:
                cached = self.cache[key]
                if cached.resources == resource_signature([p for p, _, _ in cached.resources]):
                    self.cache.move_to_end(key)
                    report(1, 'Reusing prepared preview')
                    return cached
                del self.cache[key]
        geometry = loader()
        def size(g):
            return len(g.glb or b'') + sum(a.nbytes for a in (g.points, g.colors) if a is not None)
        with self.lock:
            report(1, 'Prepared')  # Cancel before caching an obsolete request.
            self.cache[key] = geometry
            while sum(size(g) for g in self.cache.values()) > 256 * 2**20:
                self.cache.popitem(last=False)
        return geometry

    def _load(self, request):
        version, sample_id, sample, selected, restore, show_gt, representation, quality, messages, color_mode = request
        started, last_update = time.monotonic(), [0.0]

        def report(fraction, stage):
            with self.lock:
                if self.closed or version != self.version:
                    raise LoadCancelled()
                now = time.monotonic()
                if now - last_update[0] >= 0.08 or fraction in (0, 1):
                    percent = min(99, int(fraction * 100))
                    self.progress.value = percent
                    self.status.content = f'Preparing {percent}% — {stage} ({now - started:.1f}s)'
                    self.server.flush()
                    last_update[0] = now

        geometries = []
        if sample.get('display_notice'):
            messages.append(sample['display_notice'])
        max_points = QUALITY[quality][0] if self.max_points is None else self.max_points
        complete = [r for r in selected if r.data.get('status') == 'complete']
        messages.extend(f'{r.label}: {r.data.get("status", "unknown")}' for r in selected if r not in complete)
        gt = sample.get('ground_truth') if show_gt else None
        total = len(complete) + bool(gt) + 2  # input image and scene assembly
        report(0, 'Reading input image')
        def read_preview(path):
            try:
                with Image.open(path) as source:
                    source.thumbnail((1024, 1024))
                    return np.asarray(source.convert('RGBA'))
            except (OSError, TypeError, AttributeError) as exc:
                messages.append(f'Input unavailable ({path}): {exc}')
                return np.zeros((8, 8, 4), dtype=np.uint8)

        input_views = {}
        per_run_inputs = any('display_input' in r.data for r in self.runs if r.sample_id == sample_id)
        if per_run_inputs:
            for run in selected:
                report(0, f'Reading input: {run.label}')
                entry = run.data.get('display_input')
                if entry:
                    input_views[run.label] = (read_preview(entry['path']), entry.get('details', ''))
            image = next(iter(input_views.values()))[0] if input_views else None
        else:
            image = read_preview(sample.get('image_path'))
        with self.lock:
            report(1 / total, 'Input image ready')
            self.folder = self.server.gui.add_folder('Selected results')
            with self.folder:
                if image is not None:
                    self.server.gui.add_image(image, label=next(iter(input_views), 'Input image'), format='png')
        fractions = [0.0] * len(complete)
        def load_run(item):
            index, run = item
            def step(fraction, stage):
                with self.lock:
                    fractions[index] = max(fractions[index], fraction)
                    report((1 + sum(fractions)) / total, f'{run.method}: {stage}')
            step(0, 'Opening selected result')
            try:
                key = 'points' if run.method == 'wt' else ('mesh' if representation == 'Exported GLB' else 'decoded_mesh')
                artifact = run.data['artifacts'][key]
                paths = [resolve_reference(run.directory, artifact['path'])]
                if 'metadata' in artifact:
                    paths.append(resolve_reference(run.directory, artifact['metadata']))
                cache_mode = 'native' if run.method != 'wt' and color_mode != 'depth' else color_mode
                geometry = self._cached(paths, (run.label, artifact['frame'], key, restore, quality, max_points, cache_mode),
                    lambda: read_run_geometry(run, max_points=max_points, restore_camera=restore,
                        artifact_key=key, quality=quality, progress=step, color_mode=color_mode), step)
                return geometry, None
            except LoadCancelled:
                raise
            except Exception as exc:
                return None, f'{run.label}: {exc}'
            finally:
                step(1, 'Prepared')
        # Only results of the current sample; bounded concurrency overlaps image
        # decoding/IO without eagerly loading other samples or limiting comparisons.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='viewer-result') as pool:
            for geometry, error in pool.map(load_run, enumerate(complete)):
                if geometry is not None:
                    geometries.append(geometry)
                    messages.extend(geometry.notices)
                if error:
                    messages.append(error)
        if gt:
            def gt_step(fraction, stage):
                report((total - 2 + fraction) / total, f'Ground truth: {stage}')
            try:
                sample_dir = self.root / 'samples' / sample_id
                path = resolve_reference(sample_dir, gt['path'])
                cache_mode = 'depth' if color_mode == 'depth' else 'native'
                geometry = None
                try:
                    source = gso_display_source(sample, sample_dir)
                    if source is not None:
                        mesh_path, asset_to_camera, metadata_paths = source
                        geometry = self._cached([mesh_path, *metadata_paths],
                            ('GT source', quality, max_points, cache_mode),
                            lambda: read_geometry('Ground truth [textured source; camera_rdf]', mesh_path,
                                mesh=True, transform=display_transform('camera_rdf') @ asset_to_camera,
                                max_points=max_points, quality=quality, progress=gt_step, color_mode=color_mode), gt_step)
                except LoadCancelled:
                    raise
                except Exception as exc:
                    messages.append(f'Textured GT unavailable: {exc}. Using evaluation geometry.')
                if geometry is None:
                    geometry = self._cached([path], ('GT', gt['frame'], gt['kind'], quality, max_points, cache_mode),
                        lambda: read_geometry(f'Ground truth [{gt["frame"]}]', path, mesh=gt['kind'] == 'mesh',
                            frame=gt['frame'], max_points=max_points, quality=quality, progress=gt_step,
                            color_mode=color_mode), gt_step)
                geometries.append(geometry)
                messages.extend(geometry.notices)
            except LoadCancelled:
                raise
            except Exception as exc:
                messages.append(f'Ground truth: {exc}')
        with self.lock:
            report((total - 1) / total, 'Sending prepared scene')
            if self.folder is not None:
                self.folder.remove()
            self.folder = self.server.gui.add_folder('Selected results')
            with self.folder:
                populate_viewer(self.server, image, geometries, input_views)
            self.progress.value = 100
            self.progress.animated = False
            self.status.content = (f'Prepared 100% in {time.monotonic() - started:.1f}s — {len(geometries)} geometries / '
                f'{len(selected)} matching runs. Data queued; browser transfer/rendering may continue.\n\n'
                + '\n\n'.join(messages))
            self.server.flush()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
        epilog='Choose --experiment DIR, OR --image FILE --points FILE. Display limits never change saved results.')
    batch = parser.add_argument_group('Experiment / WT ablation browser (layout detected automatically)')
    batch.add_argument('--experiment', type=Path, help='experiment.json + samples/, or WT ablation <sample>/<config>/prediction.npz')
    files = parser.add_argument_group('Single-sample files (do not combine with --experiment)')
    files.add_argument('--image', type=Path, help='Required input image')
    files.add_argument('--points', type=Path, help='Required WT prediction: .rrd/.npy/.npz/.ply')
    files.add_argument('--mesh', type=Path, help='Optional main mesh (e.g. hybrid); does not run inference')
    files.add_argument('--gt', type=Path, help='Optional ground truth points/mesh; PLY with faces is a mesh')
    files.add_argument('--trellis', type=Path, help='Optional separate TRELLIS result for comparison')
    rrd = parser.add_argument_group('RRD entity selectors (single-sample .rrd files only; normally omit)')
    rrd.add_argument('--entity', help='Point entity inside --points, not a file path')
    rrd.add_argument('--gt-entity', help='Point entity inside --gt')
    rrd.add_argument('--trellis-entity', help='Point entity inside --trellis')
    display = parser.add_argument_group('Display quality (both modes)')
    display.add_argument('--quality', choices=tuple(QUALITY), default='full', help='fast: 20k points/50k-face preview threshold/512px; balanced: 50k points/original mesh/1024px; full (default): all points/original mesh and textures')
    display.add_argument('--max-points', type=int, help='Override per-result point limit; 0 means all points')
    display.add_argument('--color-mode', choices=tuple(COLOR_MODES.values()), default='surface',
        help='gray: existing textures or gray; surface (default): also input RGB on WT layer-0; depth: near-blue/far-red for all geometry')
    service = parser.add_argument_group('Local web service')
    service.add_argument('--port', type=int, default=8080, help='HTTP + WebSocket port (default 8080); 0 chooses a free port')
    args = parser.parse_args(argv)
    if args.max_points is not None and args.max_points < 0:
        parser.error('--max-points must be nonnegative')
    if not 0 <= args.port < 65536:
        parser.error('--port must be in 0..65535')
    if args.experiment:
        if any((args.image, args.points, args.mesh, args.gt, args.trellis,
                args.entity, args.gt_entity, args.trellis_entity)):
            parser.error('--experiment cannot be combined with single-sample files or RRD entity selectors')
        try:
            experiment_layout(args.experiment)
        except ValueError as exc:
            parser.error(str(exc))
    elif not args.image or not args.points:
        parser.error('Provide --experiment, or both --image and --points')
    for path in (args.image, args.points, args.mesh, args.gt, args.trellis):
        if path is not None and not path.is_file():
            parser.error(f'File not found: {path}')
    for entity, path in ((args.entity, args.points), (args.gt_entity, args.gt), (args.trellis_entity, args.trellis)):
        if entity and (path is None or path.suffix.lower() != '.rrd'):
            parser.error('RRD entity selectors require the corresponding .rrd file')
    return args


def main():
    args = parse_args()
    limits = dict(max_points=QUALITY[args.quality][0] if args.max_points is None else args.max_points,
                  quality=args.quality)

    stopped = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: stopped.set())
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    server = None
    experiment = None
    try:
        server = viser.ViserServer(host='127.0.0.1', port=args.port, label='World Tracing', verbose=False)
        # Docking reserves space and resizes the canvas; floating panels overlay it.
        server.gui.main_panel.dock_right()
        server.gui.main_panel.set_width(420)
        add_camera_controls(server)
        if args.experiment:
            experiment = ExperimentViewer(server, args.experiment, args.max_points, args.quality, args.color_mode)
        else:
            with Image.open(args.image) as image:
                image_data = np.asarray(image.convert('RGBA'))
            color = server.gui.add_dropdown('Color mode', options=tuple(COLOR_MODES),
                initial_value=next(label for label, value in COLOR_MODES.items() if value == args.color_mode))
            server.gui.add_markdown(COLOR_HINT)
            progress = server.gui.add_progress_bar(0)
            status = server.gui.add_markdown('')
            folder = None
            load_lock = threading.Lock()
            files = [('WT points', args.points, dict(entity=args.entity, wt=True, input_rgb=image_data)),
                     ('Mesh', args.mesh, dict(mesh=True)),
                     ('Ground truth', args.gt, dict(entity=args.gt_entity)),
                     ('TRELLIS output', args.trellis, dict(entity=args.trellis_entity))]
            files = [(name, path, opts) for name, path, opts in files if path is not None]

            def load_single(_=None):
                nonlocal folder
                selected = color.value
                with load_lock:
                    if selected != color.value or stopped.is_set():
                        return
                    started = time.monotonic()
                    server.scene.reset()
                    if folder is not None:
                        folder.remove()
                        folder = None
                    progress.animated = True
                    geometries = []
                    try:
                        for index, (name, path, options) in enumerate(files):
                            def report(fraction, stage):
                                if selected != color.value or stopped.is_set():
                                    raise LoadCancelled()
                                percent = min(99, int(100 * (index + fraction) / len(files)))
                                progress.value = percent
                                status.content = f'Preparing {percent}% — {name}: {stage}'
                            geometries.append(read_geometry(name, path, **options, **limits,
                                color_mode=COLOR_MODES[selected], progress=report))
                        report(1, 'Sending prepared scene')
                        folder = server.gui.add_folder('Selected results')
                        with folder:
                            populate_viewer(server, image_data, geometries)
                        progress.value = 100
                        progress.animated = False
                        status.content = f'Prepared 100% in {time.monotonic() - started:.1f}s. Browser transfer/rendering may continue.'
                        notices = [notice for geometry in geometries for notice in geometry.notices]
                        if notices:
                            status.content += '\n\n' + '\n\n'.join(dict.fromkeys(notices))
                        server.flush()
                    except LoadCancelled:
                        pass
                    except Exception as exc:
                        progress.animated = False
                        status.content = f'Loading failed: {exc}'

            color.on_update(load_single)
            load_single()
        port = server.get_port()
        if args.port and port != args.port:
            print(f'Port {args.port} unavailable; using {port}.', flush=True)
        print(f'Viewer: http://127.0.0.1:{port}', flush=True)
        print(f'Remote access: ssh -L {port}:127.0.0.1:{port} ali-dsw', flush=True)
        print('Ctrl-C to stop.', flush=True)
        stopped.wait()
    finally:
        if experiment is not None:
            experiment.close()
        if server is not None:
            server.stop()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
