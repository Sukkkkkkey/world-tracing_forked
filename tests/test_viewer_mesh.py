"""External texture resources, mesh format detection and GT camera placement."""
import io
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
import trimesh
import viser

import viewer
from viewer_utils.mesh import split_materials
from viewer_utils.gso import gso_display_source


def textured_obj(root):
    (root / 'materials').mkdir(parents=True)
    (root / 'images').mkdir()
    Image.new('RGB', (16, 16), (240, 20, 30)).save(root / 'images/red swatch.png')
    Image.new('RGB', (16, 16), (20, 40, 230)).save(root / 'images/blue.png')
    (root / 'materials/red.mtl').write_text('newmtl red\nKd 1 1 1\nmap_Kd "../images/red swatch.png"\n')
    (root / 'materials/blue.mtl').write_text('newmtl blue\nKd 1 1 1\nmap_Kd ../images/blue.png\n')
    path = root / 'model.obj'
    path.write_text('mtllib materials/red.mtl materials/blue.mtl\n'
        'v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n'
        'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n'
        'usemtl red\nf 1/1 2/2 3/3\nusemtl blue\nf 1/1 3/3 4/4\n')
    return path


def unpack(geometry):
    return trimesh.load(io.BytesIO(geometry.glb), file_type='glb', force='scene', process=False)


def texture_colors(scene):
    return {tuple(np.asarray(g.visual.material.baseColorTexture)[0, 0, :3])
            for g in scene.geometry.values()}


def test_obj_material_libraries_relative_textures_and_cache_refresh(tmp_path):
    path = textured_obj(tmp_path)
    source = path.read_bytes()
    first = viewer.read_geometry('OBJ', path, color_mode='surface')
    assert not first.notices
    scene = unpack(first)
    assert sum(len(g.faces) for g in scene.geometry.values()) == 2
    assert texture_colors(scene) == {(240, 20, 30), (20, 40, 230)}
    assert len(first.resources) == 4  # two MTLs and two textures
    assert path.read_bytes() == source
    # Reuse the real cache without starting a server or loading a dataset.
    browser = viewer.ExperimentViewer.__new__(viewer.ExperimentViewer)
    browser.lock = viewer.threading.RLock()
    browser.cache = viewer.OrderedDict()
    calls = []
    def load():
        calls.append(1)
        return viewer.read_geometry('OBJ', path)
    cached = lambda: browser._cached([path], ('obj',), load, lambda *_: None)
    cached()
    cached()
    assert len(calls) == 1
    Image.new('RGB', (16, 16), (10, 200, 20)).save(tmp_path / 'images/blue.png')
    changed = cached()
    assert len(calls) == 2
    assert (10, 200, 20) in texture_colors(unpack(changed))
    (tmp_path / 'images/blue.png').unlink()
    missing = cached()
    assert any('blue.png' in message for message in missing.notices)
    assert missing.glb is not None  # missing texture doesn't discard the geometry
    assert any(stamp[1] is None for stamp in missing.resources)


def test_gltf_external_buffers_and_url_encoded_images(tmp_path):
    path = textured_obj(tmp_path)
    scene = unpack(viewer.read_geometry('OBJ', path))
    exported = scene.export(file_type='gltf')
    tree = json.loads(exported.pop('model.gltf'))
    (tmp_path / 'buffers').mkdir()
    for i, buffer in enumerate(tree['buffers']):
        data = exported[buffer['uri']]
        name = f'buffer {i}.bin'
        (tmp_path / 'buffers' / name).write_bytes(data)
        buffer['uri'] = f'buffers/buffer%20{i}.bin'
    # Replace embedded images with explicit external URI references.
    for i, image in enumerate(tree['images']):
        view = tree['bufferViews'][image.pop('bufferView')]
        data = (tmp_path / 'buffers' / f'buffer {view["buffer"]}.bin').read_bytes()
        begin = view.get('byteOffset', 0)
        name = f'image {i}.png'
        (tmp_path / 'images' / name).write_bytes(data[begin:begin + view['byteLength']])
        image['uri'] = f'images/image%20{i}.png'
    target = tmp_path / 'scene.gltf'
    target.write_text(json.dumps(tree))
    result = viewer.read_geometry('GLTF', target, quality='full', color_mode='surface')
    assert not result.notices
    assert texture_colors(unpack(result)) == {(240, 20, 30), (20, 40, 230)}
    assert any('image 0.png' in path for path, _, _ in result.resources)


def test_ply_faces_texturefile_and_point_cloud_detection(tmp_path):
    Image.new('RGB', (8, 8), (20, 200, 40)).save(tmp_path / 'texture.png')
    path = tmp_path / 'textured.ply'
    path.write_text('ply\nformat ascii 1.0\ncomment TextureFile texture.png\n'
        'element vertex 3\nproperty float x\nproperty float y\nproperty float z\n'
        'property float texture_u\nproperty float texture_v\n'
        'element face 1\nproperty list uchar int vertex_indices\nend_header\n'
        '0 0 0 0 0\n1 0 0 1 0\n0 1 0 0 1\n3 0 1 2\n')
    mesh = viewer.read_geometry('PLY', path, color_mode='surface')
    assert mesh.glb is not None
    assert texture_colors(unpack(mesh)) == {(20, 200, 40)}
    point_path = tmp_path / 'points.ply'
    trimesh.points.PointCloud([[1, 2, 3]], colors=[[20, 30, 40]]).export(point_path)
    points = viewer.read_geometry('PLY points', point_path)
    assert points.glb is None
    np.testing.assert_allclose(points.points, [[1, -2, -3]])
    # --points still explicitly reads WT geometry as points, even with face data.
    assert viewer.read_geometry('WT', path, wt=True).glb is None


def test_glb_external_image_full_quality_is_embedded(tmp_path):
    import struct
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)),
        image=Image.new('RGB', (8, 8), (40, 80, 160)))
    data = mesh.export(file_type='glb')
    length = struct.unpack_from('<I', data, 12)[0]
    tree = json.loads(data[20:20 + length])
    binary = data[28 + length:]
    for image in tree['images']:
        view = tree['bufferViews'][image.pop('bufferView')]
        begin = view.get('byteOffset', 0)
        (tmp_path / 'external image.png').write_bytes(binary[begin:begin + view['byteLength']])
        image['uri'] = 'external%20image.png'
    header = json.dumps(tree).encode()
    header += b' ' * (-len(header) % 4)
    path = tmp_path / 'external.glb'
    path.write_bytes(b''.join([struct.pack('<4sII', b'glTF', 2, 28 + len(header) + len(binary)),
        struct.pack('<II', len(header), 0x4E4F534A), header,
        struct.pack('<II', len(binary), 0x004E4942), binary]))
    result = viewer.read_geometry('GLB', path, quality='full')
    assert not result.notices
    assert texture_colors(unpack(result)) == {(40, 80, 160)}
    size = struct.unpack_from('<I', result.glb, 12)[0]
    assert all('uri' not in image for image in json.loads(result.glb[20:20 + size])['images'])


def test_multi_material_faces_keep_textures_and_pose():
    mesh = trimesh.creation.box()
    red = trimesh.visual.material.SimpleMaterial(image=Image.new('RGB', (8, 8), (255, 0, 0)))
    blue = trimesh.visual.material.SimpleMaterial(image=Image.new('RGB', (8, 8), (0, 0, 255)))
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.MultiMaterial([red, blue]),
        face_materials=np.arange(len(mesh.faces)) % 2)
    pose = np.eye(4)
    pose[:3, 3] = [5, 7, 9]
    scene = trimesh.Scene()
    scene.add_geometry(mesh, transform=pose)
    split = split_materials(scene)
    assert sum(len(g.faces) for g in split.geometry.values()) == len(mesh.faces)
    np.testing.assert_allclose(split.bounds, scene.bounds)
    packed = viewer.Geometry('Multi', split.bounds, glb=split.export(file_type='glb'))
    assert texture_colors(unpack(packed)) == {(255, 0, 0), (0, 0, 255)}


def test_gso_source_coordinates_and_missing_source_fallback(tmp_path):
    from wt.experiment import atomic_json
    source = textured_obj(tmp_path / 'source')
    dataset = tmp_path / 'dataset'
    evaluation = dataset / 'samples' / 'a'
    evaluation.mkdir(parents=True)
    (dataset / 'inventory.jsonl').write_text(json.dumps({'asset_id': 'a', 'mesh': str(source)}) + '\n')
    asset_to_world = np.diag([2., 2., 2., 1.])
    world_to_camera = np.eye(4)
    world_to_camera[:3, 3] = [1, 2, 3]
    atomic_json(evaluation / 'camera.json', {'T_asset_to_world': asset_to_world.tolist(),
                                           'T_world_to_camera': world_to_camera.tolist()})
    sample = dict(dataset='gso-v1', asset_id='a', evaluation_dir=str(evaluation))
    path, transform, metadata = gso_display_source(sample, tmp_path)
    geometry = viewer.read_geometry('GT', path, transform=viewer.display_transform('camera_rdf') @ transform)
    np.testing.assert_allclose(geometry.bounds, [[1, -4, -3], [3, -2, -3]])
    assert len(metadata) == 2
    gt = evaluation / 'gt_camera.ply'
    trimesh.creation.box().export(gt)
    image = evaluation / 'input.png'
    Image.new('RGB', (8, 8)).save(image)
    root = tmp_path / 'experiment'
    atomic_json(root / 'experiment.json', {'schema_version': 1})
    atomic_json(root / 'samples/a/input.json', dict(sample, image=str(image),
        ground_truth=dict(path=str(gt), kind='mesh', frame='camera_rdf')))
    before = gt.read_bytes()
    server = viser.ViserServer(host='127.0.0.1', port=0, verbose=False)
    browser = viewer.ExperimentViewer(server, root)
    try:
        browser.sample.value = 'a'
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(.05)
        assert '1 geometries / 0 matching runs' in browser.status.content
        assert any('textured source' in g.name for g in browser.cache.values())
        source.unlink()
        browser.refresh()
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(.05)
        assert 'Using evaluation geometry' in browser.status.content
        assert '1 geometries / 0 matching runs' in browser.status.content
        assert gt.read_bytes() == before
    finally:
        browser.close()
        server.stop()
