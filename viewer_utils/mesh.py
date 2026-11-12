"""Local mesh formats, material resources and export preparation (read-only)."""
import io
from pathlib import Path
import shlex
from urllib.parse import unquote, urlsplit

import numpy as np
from PIL import Image
import trimesh


def resource_signature(paths):
    result = []
    for path in sorted({Path(p).resolve() for p in paths}):
        try:
            stat = path.stat()
            result.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            result.append((str(path), None, None))
    return tuple(result)


class LocalResolver(trimesh.resolvers.Resolver):
    """Resolve explicit local references, including ../, and report missing files.

    No basename guessing: two texture.png files in different folders must not
    silently substitute for one another. Never fetch network resources.
    """
    def __init__(self, path, paths=None, errors=None, virtual=None, decode_uris=None):
        self.parent = Path(path).resolve().parent
        self.file_name = Path(path).name
        self.paths = set() if paths is None else paths
        self.errors = [] if errors is None else errors
        self.virtual = {} if virtual is None else virtual
        self.decode_uris = Path(path).suffix.lower() in ('.glb', '.gltf') if decode_uris is None else decode_uris

    def keys(self):
        return self.virtual.keys()

    def namespaced(self, namespace):
        return LocalResolver(self.parent / namespace / '_resource', self.paths, self.errors, self.virtual, self.decode_uris)

    def get(self, name):
        name = str(name).strip().strip('"').replace('\\', '/')
        if self.decode_uris:
            name = unquote(name)
        if name in self.virtual:
            return self.virtual[name]
        if urlsplit(name).scheme:
            self.errors.append(f'Unsupported non-local resource: {name}')
            raise ValueError(self.errors[-1])
        path = Path(name)
        if not path.is_absolute():
            path = self.parent / path
        path = path.resolve()
        self.paths.add(path)
        try:
            return path.read_bytes()
        except OSError as exc:
            self.errors.append(f'Missing mesh resource: {path}')
            raise OSError(self.errors[-1]) from exc

    def write(self, name, data):
        raise OSError('Viewer resources are read-only')


def obj_stream(stream, resolver):
    """Combine OBJ material libraries; resolve map_Kd relative to its MTL.

    Trimesh reads one mtllib and otherwise resolves textures against the OBJ.
    Rewrite only the in-memory resource references; preserve geometry and UVs.
    """
    text = stream.read().decode('utf-8-sig').replace('\\\n', '')
    obj, materials = [], []
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if not parts or parts[0] != 'mtllib' or len(parts) != 2:
            obj.append(line)
            continue
        reference = parts[1].strip().replace('\\', '/')
        # An unquoted filename containing spaces is also common in exported OBJ.
        names = [reference] if (resolver.parent / reference).is_file() else shlex.split(reference, comments=True)
        for name in names:
            try:
                mtl = resolver.get(name).decode('utf-8-sig')
            except OSError:
                continue
            mtl_parent = (resolver.parent / name).resolve().parent
            for material_line in mtl.splitlines():
                tokens = material_line.strip().split(maxsplit=1)
                if tokens and tokens[0].lower() == 'map_kd' and len(tokens) == 2:
                    image_name = tokens[1].strip().strip('"').replace('\\', '/')
                    if image_name.startswith('-'):
                        resolver.errors.append(f'Unsupported MTL map_Kd options in {name}: {image_name}')
                        continue
                    image_path = (mtl_parent / image_name).resolve()
                    # Some exporters use paths relative to the OBJ instead of MTL.
                    resolver.paths.add(image_path)
                    if not image_path.is_file():
                        alternative = (resolver.parent / image_name).resolve()
                        if alternative.is_file():
                            image_path = alternative
                    material_line = f'map_Kd {image_path}'
                materials.append(material_line)
    if materials:
        resolver.virtual['__viewer_materials__.mtl'] = '\n'.join(materials).encode()
        obj.insert(0, 'mtllib __viewer_materials__.mtl')
    return io.BytesIO('\n'.join(obj).encode())


def is_mesh_file(path):
    suffix = path.suffix.lower()
    if suffix != '.ply':
        return suffix in ('.glb', '.gltf', '.obj', '.stl', '.off')
    with path.open('rb') as stream:
        for line in stream:
            parts = line.strip().split()
            if parts == [b'end_header']:
                break
            if parts[:2] == [b'element', b'face'] and len(parts) == 3:
                return int(parts[2]) > 0
    return False


def split_materials(scene):
    if not any(isinstance(getattr(g.visual, 'material', None), trimesh.visual.material.MultiMaterial)
               for g in scene.geometry.values()):
        return scene
    result = trimesh.Scene()
    for node in scene.graph.nodes_geometry:
        pose, key = scene.graph[node]
        geometry = scene.geometry[key]
        visual = geometry.visual
        if isinstance(getattr(visual, 'material', None), trimesh.visual.material.MultiMaterial):
            if visual.face_materials is None:
                raise ValueError(f'Multi-material mesh {key} has no face material assignments')
            for index in np.unique(visual.face_materials):
                faces = np.flatnonzero(np.asarray(visual.face_materials) == index)
                part = geometry.submesh([faces], append=True, repair=False)
                part.visual.material = visual.material.materials[int(index)]
                result.add_geometry(part, transform=pose)
        else:
            result.add_geometry(geometry, transform=pose)
    return result


class _ExportTexture:
    """PIL-compatible export proxy; preserve original PNG/JPEG bytes when possible.

    Scoped to a loaded scene, never patches Pillow or trimesh globals. Material
    hashing still sees the actual pixels through the delegated array interface.
    """
    def __init__(self, image):
        self.image = image
        self.encoded = None
        self.original_format = image.format
        stream = getattr(image, 'fp', None)
        if stream is not None and image.format in ('PNG', 'JPEG'):
            position = stream.tell()
            stream.seek(0)
            self.encoded = stream.read()
            stream.seek(position)

    def __getattr__(self, name):
        return getattr(self.image, name)

    def save(self, stream, format=None, **kwargs):
        if self.encoded is not None and str(format).upper() == self.original_format:
            stream.write(self.encoded)
        else:
            if str(format).upper() == 'PNG':
                kwargs.setdefault('compress_level', 1)
            self.image.save(stream, format=format, **kwargs)


def prepare_export_textures(scene):
    """Avoid expensive recompression of full-resolution external textures."""
    textures = {}
    for geometry in scene.geometry.values():
        material = getattr(geometry.visual, 'material', None)
        for field in ('image', 'baseColorTexture', 'normalTexture', 'metallicRoughnessTexture',
                      'occlusionTexture', 'emissiveTexture'):
            image = getattr(material, field, None)
            if isinstance(image, Image.Image):
                if id(image) not in textures:
                    textures[id(image)] = _ExportTexture(image)
                setattr(material, field, textures[id(image)])

