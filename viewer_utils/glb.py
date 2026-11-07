"""Static GLB display preparation, preserving mesh accessors and topology.

The common exported-GLB path avoids decoding/re-exporting millions of triangles.
Unsupported layouts fall back to the general mesh loader in viewer.py.
"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import struct

import numpy as np
from PIL import Image
from viser.transforms import SO3

GRAY = (180, 180, 180)


def depth_colors(depth, limits=None):
    """Fixed blue → cyan → yellow → red palette; near → far in display -Z."""
    depth = np.asarray(depth)
    low, high = (float(depth.min()), float(depth.max())) if limits is None else limits
    value = np.clip((depth - low) / (high - low), 0, 1) if high > low else np.full(depth.shape, 0.5)
    palette = np.array([[49, 54, 149], [69, 180, 220], [255, 255, 191], [244, 109, 67], [165, 0, 38]])
    return np.stack([np.interp(value, np.linspace(0, 1, len(palette)), palette[:, c])
                     for c in range(3)], axis=-1).astype(np.uint8)


class UnsupportedGLB(ValueError):
    pass


def prepare_glb(data, transform, texture_edge, color_mode, progress):
    magic, version, length = struct.unpack_from('<4sII', data)
    if magic != b'glTF' or version != 2 or length != len(data):
        raise UnsupportedGLB('Expected GLB 2.0')
    chunks, offset = {}, 12
    while offset < length:
        size, kind = struct.unpack_from('<II', data, offset)
        chunks[kind] = memoryview(data)[offset + 8:offset + 8 + size]
        offset += size + 8
    tree = json.loads(bytes(chunks[0x4E4F534A]))
    if any('uri' in image for image in tree.get('images', [])):
        raise UnsupportedGLB('External images need embedding by the general mesh loader')
    binary = chunks.get(0x004E4942, memoryview(b''))
    if (len(tree.get('buffers', [])) != 1 or 'uri' in tree['buffers'][0]
            or tree.get('skins') or tree.get('animations')):
        raise UnsupportedGLB('Requires one embedded buffer and static geometry')
    views = tree.get('bufferViews', [])
    if any(v.get('buffer', 0) != 0 or v.get('extensions') for v in views):
        raise UnsupportedGLB('External or compressed buffer views')
    buffers = [binary[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']] for v in views]
    nodes, meshes = tree.get('nodes', []), tree.get('meshes', [])
    instances = []
    seen = set()

    def visit(index, parent):
        if index in seen:
            raise UnsupportedGLB('Repeated scene node')
        seen.add(index)
        node = nodes[index]
        if 'matrix' in node:
            local = np.asarray(node['matrix']).reshape(4, 4).T
        else:
            local = np.eye(4)
            x, y, z, w = node.get('rotation', (0, 0, 0, 1))
            local[:3, :3] = SO3(np.array([w, x, y, z])).as_matrix() @ np.diag(node.get('scale', (1, 1, 1)))
            local[:3, 3] = node.get('translation', (0, 0, 0))
        pose = parent @ local
        if 'mesh' in node:
            mesh = meshes[node['mesh']]
            for primitive in mesh['primitives']:
                if primitive.get('mode', 4) != 4 or primitive.get('targets') or primitive.get('extensions'):
                    raise UnsupportedGLB('Only static, uncompressed triangle primitives')
                accessor = tree['accessors'][primitive['attributes']['POSITION']]
                if accessor.get('sparse') or accessor['componentType'] != 5126 or accessor['type'] != 'VEC3':
                    raise UnsupportedGLB('Unsupported position accessor')
                view = views[accessor['bufferView']]
                positions = np.ndarray((accessor['count'], 3), dtype='<f4',
                    buffer=buffers[accessor['bufferView']], offset=accessor.get('byteOffset', 0),
                    strides=(view.get('byteStride', 12), 4))
                world = positions @ pose[:3, :3].T + pose[:3, 3]
                if not len(world) or not np.isfinite(world).all():
                    raise ValueError('Empty or non-finite mesh positions')
                instances.append((index, primitive, world))
        for child in node.get('children', []):
            visit(child, pose)

    scene = tree['scenes'][tree.get('scene', 0)]
    for root in scene.get('nodes', []):
        visit(root, transform)
    if not instances:
        raise UnsupportedGLB('No triangle mesh')
    bounds = np.array([np.min([p.min(0) for _, _, p in instances], axis=0),
                       np.max([p.max(0) for _, _, p in instances], axis=0)])
    progress(0.55, 'Mesh topology retained; preparing display colors')
    if color_mode == 'depth':
        # A shared mesh can have multiple poses: give each instance its own colors.
        clones = {}
        for index, primitive, world in instances:
            if index not in clones:
                clones[index] = deepcopy(meshes[nodes[index]['mesh']])
                meshes.append(clones[index])
                nodes[index]['mesh'] = len(meshes) - 1
            source_primitives = [p for n, p, _ in instances if n == index]
            primitive_index = next(i for i, p in enumerate(source_primitives) if p is primitive)
            target = clones[index]['primitives'][primitive_index]
            colors = depth_colors(-world[:, 2], (-bounds[1, 2], -bounds[0, 2]))
            buffers.append(colors.tobytes())
            views.append({'buffer': 0, 'byteLength': colors.nbytes, 'target': 34962})
            tree['accessors'].append({'bufferView': len(views) - 1, 'componentType': 5121,
                'count': len(colors), 'type': 'VEC3', 'normalized': True})
            target['attributes']['COLOR_0'] = len(tree['accessors']) - 1
            target['material'] = 0
        # Also replace materials on unused source meshes so all references stay valid.
        for mesh in meshes:
            for primitive in mesh['primitives']:
                primitive['material'] = 0
        tree['materials'] = [{'pbrMetallicRoughness': {'baseColorFactor': [1, 1, 1, 1],
            'metallicFactor': 0, 'roughnessFactor': 1}, 'doubleSided': True,
            'extensions': {'KHR_materials_unlit': {}}}]
        tree['extensionsUsed'] = sorted(set(tree.get('extensionsUsed', [])) | {'KHR_materials_unlit'})
        for image in tree.get('images', []):
            if 'bufferView' in image:
                buffers[image['bufferView']] = b'\0' * 4  # Unreferenced, valid nonempty view.
        tree.pop('images', None)
        tree.pop('textures', None)
        for field in ('extensionsUsed', 'extensionsRequired'):
            tree[field] = [e for e in tree.get(field, []) if e != 'EXT_texture_webp']
    else:
        materials = tree.setdefault('materials', [])
        for mesh in meshes:
            for primitive in mesh['primitives']:
                material = materials[primitive['material']] if 'material' in primitive else {}
                pbr = material.get('pbrMetallicRoughness', {})
                if 'baseColorTexture' not in pbr and 'COLOR_0' not in primitive['attributes']:
                    replacement = deepcopy(material)
                    replacement['pbrMetallicRoughness'] = dict(pbr, baseColorFactor=[*(c / 255 for c in GRAY), 1],
                                                              metallicFactor=0, roughnessFactor=0.8)
                    materials.append(replacement)
                    primitive['material'] = len(materials) - 1
        # Preserve native WebP for full quality. For previews, re-encode only
        # images that need resizing; geometry buffers are copied verbatim.
        if texture_edge is not None:
            images = tree.get('images', [])
            def resize_image(image):
                if 'bufferView' not in image:
                    raise UnsupportedGLB('External texture image')
                view_index = image['bufferView']
                with Image.open(io.BytesIO(buffers[view_index])) as source:
                    if max(source.size) > texture_edge:
                        # Opaque RGBA textures need no alpha premultiplication on resize.
                        if source.mode == 'RGBA' and source.getextrema()[3] == (255, 255):
                            source = source.convert('RGB')
                        source.thumbnail((texture_edge, texture_edge), Image.Resampling.BILINEAR, reducing_gap=2)
                        output = io.BytesIO()
                        source.save(output, format='PNG', compress_level=1)
                        return output.getvalue(), 'image/png'
                return buffers[view_index], image['mimeType']

            # Bound decoding concurrency to two textures of this selected mesh.
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix='viewer-texture') as pool:
                for i, (image, (buffer, mime)) in enumerate(zip(images, pool.map(resize_image, images))):
                    buffers[image['bufferView']] = buffer
                    image['mimeType'] = mime
                    progress(0.55 + 0.3 * (i + 1) / max(len(images), 1), 'Preparing texture images')
            # Resized WebP sources now contain PNG; route them through core glTF.
            for texture in tree.get('textures', []):
                extension = texture.get('extensions', {}).get('EXT_texture_webp')
                if extension and images[extension['source']].get('mimeType') == 'image/png':
                    texture['source'] = extension['source']
                    del texture['extensions']['EXT_texture_webp']
            if not any('EXT_texture_webp' in t.get('extensions', {}) for t in tree.get('textures', [])):
                for field in ('extensionsUsed', 'extensionsRequired'):
                    tree[field] = [e for e in tree.get(field, []) if e != 'EXT_texture_webp']
    # A parent node expresses display/camera restoration without rewriting vertices.
    nodes.append({'matrix': np.asarray(transform).T.ravel().tolist(), 'children': scene.get('nodes', [])})
    scene['nodes'] = [len(nodes) - 1]
    parts, offset = [], 0
    for view, buffer in zip(views, buffers):
        view.update(byteOffset=offset, byteLength=len(buffer))
        padding = b'\0' * (-len(buffer) % 4)
        parts.extend((buffer, padding))
        offset += len(buffer) + len(padding)
    tree['buffers'] = [{'byteLength': offset}]
    for field in ('extensionsUsed', 'extensionsRequired'):
        if not tree.get(field):
            tree.pop(field, None)
    for texture in tree.get('textures', []):
        if not texture.get('extensions'):
            texture.pop('extensions', None)
    header = json.dumps(tree, separators=(',', ':')).encode()
    header += b' ' * (-len(header) % 4)
    progress(0.95, 'Packing original mesh buffers')
    result = b''.join([struct.pack('<4sII', b'glTF', 2, 28 + len(header) + offset),
                      struct.pack('<II', len(header), 0x4E4F534A), header,
                      struct.pack('<II', offset, 0x004E4942), *parts])
    return bounds, result
