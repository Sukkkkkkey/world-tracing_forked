"""Viewer file compatibility and point/color selection, without a browser or GPU."""
from pathlib import Path
import importlib.util
import sys

import numpy as np
import pytest
import rerun as rr

spec = importlib.util.spec_from_file_location('viewer', Path(__file__).resolve().parents[1] / 'viewer.py')
viewer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = viewer
spec.loader.exec_module(viewer)


def test_layered_npz_masks_and_colors_stay_aligned(tmp_path):
    xyz = np.arange(36, dtype=np.float32).reshape(2, 2, 3, 3)
    xyz[0, 0, 0] = np.nan
    mask = np.ones((2, 2, 3), dtype=bool)
    mask[1, 0, 0] = False
    rgb = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    path = tmp_path / 'prediction.npz'
    np.savez(path, xyz_pred=xyz, mask_pred=mask, rgb=rgb)
    points, colors = viewer.prepare_points(*viewer.read_points(path))
    valid = mask & np.isfinite(xyz).all(axis=-1)
    np.testing.assert_array_equal(points, xyz[valid])
    expected = np.full(xyz.shape, viewer.GRAY, dtype=np.uint8)
    expected[0] = rgb
    np.testing.assert_array_equal(colors, expected[valid])
    assert len(points) == 10


@pytest.mark.parametrize('static', [False, True])
def test_rrd_reads_positions_and_packed_colors(tmp_path, static):
    path = tmp_path / 'cloud.rrd'
    rec = rr.new_recording('viewer-test')
    rr.save(path, recording=rec)
    rr.log('world/pointcloud/all', rr.Points3D([[1, 2, 3], [4, 5, 6]],
           colors=[[255, 0, 0], [0, 255, 0]]), static=static, recording=rec)
    rec.flush()
    rr.disconnect(recording=rec)
    xyz, colors, _ = viewer.read_rrd(path)
    np.testing.assert_array_equal(xyz, [[1, 2, 3], [4, 5, 6]])
    np.testing.assert_array_equal(colors, [[255, 0, 0, 255], [0, 255, 0, 255]])


def test_invalid_cloud_and_ambiguous_video_shape_are_rejected():
    with pytest.raises(ValueError, match='No finite'):
        viewer.prepare_points([[np.nan, 0, 0]])
    with pytest.raises(ValueError, match='select a batch/frame'):
        viewer.prepare_points(np.zeros((2, 2, 2, 2, 3)))


def test_point_cap_is_deterministic_and_keeps_color_correspondence():
    xyz = np.arange(300, dtype=np.float32).reshape(100, 3)
    colors = np.arange(100, dtype=np.uint8)[:, None].repeat(3, axis=1)
    first = viewer.prepare_points(xyz, colors, max_points=7)
    second = viewer.prepare_points(xyz, colors, max_points=7)
    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1][:, 0], first[0][:, 0] / 3)


def test_geometry_orientation_and_mesh_scene_transforms(tmp_path):
    import trimesh

    path = tmp_path / 'points.npy'
    np.save(path, [[1, 2, 3], [4, 5, 6]])
    points = viewer.read_geometry('Points', path)
    np.testing.assert_array_equal(points.points, [[1, -2, -3], [4, -5, -6]])
    mesh = trimesh.Scene()
    transform = np.eye(4)
    transform[:3, 3] = [10, 20, 30]
    mesh.add_geometry(trimesh.creation.box(), transform=transform)
    path = tmp_path / 'mesh.glb'
    mesh.export(path)
    original = path.read_bytes()
    loaded = viewer.read_geometry('Mesh', path)
    np.testing.assert_allclose(loaded.bounds, mesh.bounds)
    assert loaded.glb[:4] == b'glTF'
    assert path.read_bytes() == original


def test_batch_hybrid_restoration_and_unknown_frames(tmp_path):
    import trimesh
    from wt.experiment import RunRecord, atomic_json
    from wt.textured_mesh.canon import CanonicalTransform, glb_to_camera

    scene = trimesh.Scene()
    transform = np.eye(4)
    transform[:3, 3] = [1, 2, 3]
    scene.add_geometry(trimesh.creation.box(), transform=transform)
    scene.export(tmp_path / 'mesh.glb')
    tf = CanonicalTransform([0.5, 1., -0.25], 2)
    atomic_json(tmp_path / 'mesh.json', {'canonical_transform': tf.to_dict()})
    run = RunRecord(tmp_path, 'a', 'wt_trellis2', 'defaults-v1', 42,
        {'artifacts': {'mesh': {'path': 'mesh.glb', 'kind': 'mesh', 'frame': 'gltf_yup', 'metadata': 'mesh.json'}}})
    loaded = viewer.read_run_geometry(run)
    expected = glb_to_camera(scene.to_geometry().vertices, tf) * [1, -1, -1]
    np.testing.assert_allclose(loaded.bounds, [expected.min(0), expected.max(0)], atol=1e-6)
    np.testing.assert_allclose(viewer.read_run_geometry(run, restore_camera=False).bounds, scene.bounds)
    # Native TRELLIS must never inherit the WT pose even with an adjacent metadata file.
    run.method = 'trellis2'
    np.testing.assert_allclose(viewer.read_run_geometry(run).bounds, scene.bounds)
    run.data['artifacts']['mesh']['frame'] = 'unknown'
    with pytest.raises(ValueError, match='Unknown coordinate frame'):
        viewer.read_run_geometry(run)


def test_mesh_preview_budget_texture_and_transforms(monkeypatch, tmp_path):
    import io
    import trimesh
    from PIL import Image

    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)),
        image=Image.new('RGB', (128, 128), (230, 40, 20)))
    scene = trimesh.Scene()
    pose = np.eye(4)
    pose[:3, 3] = [10, 20, 30]
    scene.add_geometry(mesh, transform=pose)
    path = tmp_path / 'textured.glb'
    scene.export(path)
    original = path.read_bytes()
    monkeypatch.setitem(viewer.QUALITY, 'fast', (5, 1, 32))
    progress = []
    preview = viewer.read_geometry('Test', path, max_points=5, quality='fast', progress=lambda value, _: progress.append(value))
    assert preview.glb is None and len(preview.points) == 5
    assert 'vertex preview' in preview.name
    np.testing.assert_allclose(preview.bounds, scene.bounds)
    np.testing.assert_array_equal(preview.colors, np.tile([230, 40, 20], (5, 1)))
    assert all(a <= b for a, b in zip(progress, progress[1:])) and progress[-1] == 1
    monkeypatch.setitem(viewer.QUALITY, 'balanced', (5, None, 32))
    packed = viewer.read_geometry('Test', path)
    reloaded = trimesh.load(io.BytesIO(packed.glb), file_type='glb', force='scene')
    assert max(next(iter(reloaded.geometry.values())).visual.material.baseColorTexture.size) == 32
    full = viewer.read_geometry('Test', path, quality='full')
    reloaded = trimesh.load(io.BytesIO(full.glb), file_type='glb', force='scene')
    assert max(next(iter(reloaded.geometry.values())).visual.material.baseColorTexture.size) == 128
    assert path.read_bytes() == original


def test_wt_color_modes_layer_provenance_and_depth_sampling(tmp_path):
    xyz = np.arange(54, dtype=np.float32).reshape(3, 2, 3, 3)
    mask = np.ones(xyz.shape[:-1], dtype=bool)
    mask[1, 0, 0] = False
    rgb = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    path = tmp_path / 'wt.npz'
    np.savez(path, xyz=xyz, rgb=rgb, mask=mask)
    gray = viewer.read_geometry('WT', path, wt=True)
    np.testing.assert_array_equal(gray.colors, np.tile(viewer.GRAY, (mask.sum(), 1)))
    surface = viewer.read_geometry('WT', path, wt=True, color_mode='surface')
    expected = np.full(xyz.shape, viewer.GRAY, dtype=np.uint8)
    expected[0] = rgb
    np.testing.assert_array_equal(surface.colors, expected[mask])
    depth = viewer.read_geometry('WT', path, wt=True, color_mode='depth', max_points=5)
    full = viewer.read_geometry('WT', path, wt=True, color_mode='depth', max_points=0)
    assert len(full.points) == mask.sum()
    for p, c in zip(depth.points, depth.colors):
        np.testing.assert_array_equal(c, full.colors[np.all(full.points == p, axis=1)][0])
    assert len(np.unique(full.colors, axis=0)) > 5
    # A flat export has lost layer/pixel correspondence: never guess the front layer.
    np.savez(path, xyz=xyz[mask], rgb=expected[mask])
    flat = viewer.read_geometry('WT', path, wt=True, color_mode='surface')
    assert 'no layer-0 RGB correspondence' in flat.name
    np.testing.assert_array_equal(flat.colors, np.tile(viewer.GRAY, (mask.sum(), 1)))
    np.save(path.with_suffix('.npy'), xyz)
    mapped = viewer.read_geometry('WT', path.with_suffix('.npy'), wt=True,
                                  color_mode='surface', input_rgb=rgb)
    np.testing.assert_array_equal(mapped.colors[:6], rgb.reshape(-1, 3))


def glb_parts(data):
    import json
    import struct
    size = struct.unpack_from('<I', data, 12)[0]
    return json.loads(data[20:20 + size]), data[28 + size:]


def accessor_bytes(tree, binary, index):
    a = tree['accessors'][index]
    v = tree['bufferViews'][a['bufferView']]
    return binary[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']]


@pytest.mark.parametrize('mode', ['gray', 'surface', 'depth'])
def test_glb_preserves_topology_normals_uvs_and_instance_depth(tmp_path, mode):
    import io
    import trimesh
    from PIL import Image

    mesh = trimesh.creation.icosphere(subdivisions=2)
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)),
        image=Image.new('RGBA', (128, 128), (230, 40, 20, 128)))
    scene = trimesh.Scene()
    scene.add_geometry(mesh, geom_name='shared', node_name='a')
    pose = trimesh.transformations.rotation_matrix(0.7, [0, 1, 0])
    pose[:3, 3] = [3, 2, 10]
    scene.graph.update(frame_to='b', matrix=pose, geometry='shared')
    path = tmp_path / 'mesh.glb'
    path.write_bytes(scene.export(file_type='glb', include_normals=True, extension_webp=True))
    original = path.read_bytes()
    old_tree, old_bin = glb_parts(original)
    transform = viewer.display_transform('camera_rdf')
    result = viewer.read_geometry('Mesh', path, color_mode=mode, transform=transform)
    tree, binary = glb_parts(result.glb)
    for old in old_tree['meshes']:
        for primitive in old['primitives']:
            # Original index, position, UV and normal accessor buffers are bit-identical.
            for index in [primitive['indices'], *primitive['attributes'].values()]:
                assert accessor_bytes(tree, binary, index) == accessor_bytes(old_tree, old_bin, index)
    reloaded = trimesh.load(io.BytesIO(result.glb), file_type='glb', force='scene', process=False)
    expected = scene.copy()
    expected.apply_transform(transform)
    np.testing.assert_allclose(result.bounds, expected.bounds, atol=1e-6)
    np.testing.assert_allclose(reloaded.bounds, expected.bounds, atol=1e-6)
    assert sum(len(reloaded.geometry[reloaded.graph[n][1]].faces) for n in reloaded.graph.nodes_geometry) == 2 * len(mesh.faces)
    if mode == 'depth':
        assert not tree.get('textures') and not tree.get('images')
        assert 'KHR_materials_unlit' in tree['materials'][0]['extensions']
        for node in tree['nodes']:
            if 'mesh' not in node:
                continue
            primitive = tree['meshes'][node['mesh']]['primitives'][0]
            assert 'COLOR_0' in primitive['attributes']
        for node in reloaded.graph.nodes_geometry:
            pose, key = reloaded.graph[node]
            geometry = reloaded.geometry[key]
            world = trimesh.transform_points(geometry.vertices, pose)
            expected_colors = viewer.depth_colors(-world[:, 2], (-result.bounds[1, 2], -result.bounds[0, 2]))
            node_json = next(n for n in tree['nodes'] if n.get('name') == node)
            primitive = tree['meshes'][node_json['mesh']]['primitives'][0]
            color_accessor = primitive['attributes']['COLOR_0']
            colors = np.frombuffer(accessor_bytes(tree, binary, color_accessor), dtype=np.uint8).reshape(-1, 3)
            np.testing.assert_allclose(colors, expected_colors, atol=1)
    else:
        assert tree['textures']  # Existing real texture retained, including alpha.
    assert path.read_bytes() == original


def test_balanced_resizes_webp_preserving_alpha_and_gray_fallback(monkeypatch, tmp_path):
    import io
    import trimesh
    from PIL import Image

    monkeypatch.setitem(viewer.QUALITY, 'balanced', (5, None, 32))
    scene = trimesh.Scene()
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)),
        image=Image.new('RGBA', (128, 128), (230, 40, 20, 128)))
    scene.add_geometry(mesh)
    scene.add_geometry(trimesh.creation.box())
    path = tmp_path / 'mixed.glb'
    path.write_bytes(scene.export(file_type='glb', extension_webp=True))
    result = viewer.read_geometry('Mesh', path)
    tree, binary = glb_parts(result.glb)
    assert 'EXT_texture_webp' not in tree.get('extensionsRequired', [])
    assert 'EXT_texture_webp' not in tree.get('extensionsUsed', [])
    for image in tree['images']:
        view = tree['bufferViews'][image['bufferView']]
        texture = Image.open(io.BytesIO(binary[view['byteOffset']:view['byteOffset'] + view['byteLength']]))
        assert texture.size == (32, 32)
        assert texture.getextrema()[3] == (128, 128)
    gray = tree['materials'][tree['meshes'][1]['primitives'][0]['material']]
    np.testing.assert_allclose(gray['pbrMetallicRoughness']['baseColorFactor'][:3], np.array(viewer.GRAY) / 255)


def test_ply_mesh_depth_replaces_authored_colors_with_unlit_material(tmp_path):
    import io
    import trimesh

    mesh = trimesh.creation.box()
    mesh.visual.vertex_colors = [255, 0, 0, 255]
    path = tmp_path / 'gt.ply'
    mesh.export(path)
    original = path.read_bytes()
    result = viewer.read_geometry('GT', path, mesh=True, frame='camera_rdf', color_mode='depth')
    tree, _ = glb_parts(result.glb)
    assert 'KHR_materials_unlit' in tree['materials'][0]['extensions']
    reloaded = trimesh.load(io.BytesIO(result.glb), file_type='glb', force='scene', process=False)
    geometry = next(iter(reloaded.geometry.values()))
    assert len(geometry.faces) == len(mesh.faces)
    colors = (geometry.visual.vertex_attributes['color'] if geometry.visual.kind == 'texture'
              else geometry.visual.vertex_colors)
    assert len(np.unique(colors, axis=0)) == 2
    assert path.read_bytes() == original


def test_experiment_loads_only_selected_sample_without_run_limit(monkeypatch, tmp_path):
    import threading
    import time
    import viser
    from PIL import Image
    from wt.experiment import atomic_json, run_directory

    root = tmp_path / 'experiment'
    atomic_json(root / 'experiment.json', {'schema_version': 1})
    image, points = tmp_path / 'image.png', tmp_path / 'points.npy'
    Image.new('RGB', (8, 8)).save(image)
    np.save(points, [[1, 2, 3]])
    for sample in ('a', 'b'):
        sample_points = tmp_path / f'{sample}.npy'
        np.save(sample_points, [[1, 2, 3]])
        atomic_json(root / 'samples' / sample / 'input.json', {'image': str(image),
            'ground_truth': {'path': str(points), 'kind': 'points', 'frame': 'camera_rdf'}})
        for seed in range(13):
            directory = run_directory(root, sample, 'wt', 'defaults-v1', seed)
            atomic_json(directory / 'run.json', {'status': 'complete', 'artifacts': {
                'points': {'path': str(sample_points), 'kind': 'points', 'frame': 'camera_rdf'}}})
        for method in ('trellis2', 'pixal3d'):
            for config in ('defaults-v1', 'extra-v1'):
                for seed in (1, 3):
                    directory = run_directory(root, sample, method, config, seed)
                    atomic_json(directory / 'run.json', {'status': 'complete', 'artifacts': {
                        'mesh': {'path': str(sample_points), 'kind': 'points', 'frame': 'camera_rdf'}}})
    calls = []
    loaded = []
    loading_b, release_b = threading.Event(), threading.Event()
    original = viewer.read_run_geometry
    def load(run, **kwargs):
        calls.append(run.sample_id)
        loaded.append((run.method, run.config_id, str(run.seed)))
        if run.sample_id == 'b':
            loading_b.set()
            assert release_b.wait(10)
        return original(run, **kwargs)
    monkeypatch.setattr(viewer, 'read_run_geometry', load)
    server = viser.ViserServer(host='127.0.0.1', port=0, verbose=False)
    browser = viewer.ExperimentViewer(server, root)
    try:
        assert not calls and browser.show_gt.value
        assert browser.quality.value == 'full' and browser.color.value == '表面颜色'
        assert set(browser.method.value) == {'wt', 'trellis2', 'pixal3d'}
        assert set(browser.config.value) == {'defaults-v1', 'extra-v1'}
        assert browser.seed.value == ('0',)
        browser.method.value = ('wt',)
        browser.config.value = ('defaults-v1',)
        browser.seed.value = browser.seed.options
        browser.sample.value = 'a'
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(0.05)
        assert '14 geometries / 13 matching runs' in browser.status.content
        assert calls == ['a'] * 13
        # Refresh reuses bounded prepared previews without reading geometry again.
        browser.refresh()
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(0.05)
        assert calls == ['a'] * 13
        # A slow obsolete request must not publish its scene after switching back.
        browser.sample.value = 'b'
        assert loading_b.wait(10)
        old_version = browser.version
        browser.sample.value = 'a'
        deadline = time.monotonic() + 10
        while browser.version == old_version and time.monotonic() < deadline:
            time.sleep(0.01)
        assert browser.version > old_version
        release_b.set()
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(0.05)
        assert '14 geometries / 13 matching runs' in browser.status.content
        assert calls[:13] == ['a'] * 13
        assert calls[13:] in (['b'], ['b', 'b'])  # At most two in flight; others never read.
        # OR within each multi-selection; AND across method/config/seed.
        browser.method.value = ('wt', 'pixal3d')
        browser.config.value = ('defaults-v1', 'extra-v1')
        browser.seed.value = ('1', '3')
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(0.05)
        assert '7 geometries / 6 matching runs' in browser.status.content
        assert not any(method == 'trellis2' for method, _, _ in loaded)
        # Refresh preserves the subset; an empty selection means zero runs, not all.
        browser.refresh()
        assert browser.method.value == ('pixal3d', 'wt')
        assert browser.seed.value == ('1', '3')
        browser.method.value = ()
        deadline = time.monotonic() + 10
        while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
            time.sleep(0.05)
        assert '1 geometries / 0 matching runs' in browser.status.content  # GT remains enabled.
        browser.refresh()
        assert browser.method.value == ()
    finally:
        release_b.set()
        browser.close()
        server.stop()


def test_parser_rejects_ignored_entity_arguments(tmp_path):
    (tmp_path / 'experiment.json').write_text('{"schema_version": 1}')
    with pytest.raises(SystemExit):
        viewer.parse_args(['--experiment', str(tmp_path), '--entity', '/cloud'])
    args = viewer.parse_args(['--experiment', str(tmp_path)])
    assert args.quality == 'full' and args.color_mode == 'surface' and args.max_points is None
    args = viewer.parse_args(['--experiment', str(tmp_path), '--quality', 'balanced', '--color-mode', 'gray'])
    assert args.quality == 'balanced' and args.color_mode == 'gray'


@pytest.mark.parametrize('stop_signal,batch', [('SIGINT', False), ('SIGTERM', False),
                                               ('SIGHUP', False), ('SIGTERM', True)])
def test_single_port_http_websocket_controls_and_shutdown(tmp_path, stop_signal, batch):
    import os
    import re
    import signal
    import socket
    import subprocess
    import time
    import urllib.request

    import msgspec
    from PIL import Image
    import trimesh
    import viser
    from websockets.sync.client import connect
    import zstandard

    image = tmp_path / 'image.png'
    points = tmp_path / 'points.npy'
    mesh = tmp_path / 'mesh.glb'
    Image.new('RGB', (8, 8)).save(image)
    np.save(points, np.array([[1, 2, 3]], dtype=np.float32))
    trimesh.creation.box().export(mesh)
    log = tmp_path / 'server.log'
    command = [sys.executable, '-u', str(Path(viewer.__file__)), '--image', str(image),
        '--points', str(points), '--mesh', str(mesh), '--gt', str(points), '--trellis', str(mesh), '--port', '0']
    if batch:
        from wt.experiment import atomic_json, run_directory
        root = tmp_path / 'batch'
        atomic_json(root / 'experiment.json', {'schema_version': 1})
        for sample in ('a', 'b'):
            atomic_json(root / 'samples' / sample / 'input.json', {'image': str(image)})
            directory = run_directory(root, sample, 'wt', 'defaults-v1', 42)
            atomic_json(directory / 'run.json', {'status': 'complete' if sample == 'a' else 'failed',
                'artifacts': {'points': {'path': str(points), 'kind': 'points', 'frame': 'camera_rdf'}}})
        command = [sys.executable, '-u', str(Path(viewer.__file__)), '--experiment', str(root), '--port', '0']
    env = dict(os.environ)
    env.pop('_VISER_PORT_OVERRIDE', None)

    def receive(ws):
        payload = ws.recv(timeout=10)
        length = int.from_bytes(payload[8:16], 'little')
        packed = zstandard.ZstdDecompressor().decompress(payload[16:16 + length])
        return msgspec.msgpack.decode(packed)['messages']

    with log.open('w') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            output = log.read_text()
            match = re.search(r'Viewer: (http://127.0.0.1:(\d+))', output)
            if match or process.poll() is not None:
                break
            time.sleep(0.1)
        assert match, log.read_text()
        url, port = match[1], int(match[2])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            html = response.read().decode()
            assert response.status == 200 and 'viser' in html.lower()
        with connect(url.replace('http:', 'ws:'), subprotocols=[f'viser-v{viser.__version__}'],
                     proxy=None, max_size=32 * 1024 * 1024) as ws:
            # Like the browser, announce a camera before sending GUI events.
            ws.send(msgspec.msgpack.encode({'type': 'ViewerCameraMessage', 'wxyz': [0, 1, 0, 0],
                'position': [0, 0, 5], 'fov': 1.0, 'near': 0.01, 'far': 1000.0,
                'image_height': 800, 'image_width': 1200, 'look_at': [0, 0, 0], 'up_direction': [0, 1, 0]}))
            messages = []
            while not any(m['type'] == 'ReplayDoneMessage' for m in messages):
                messages.extend(receive(ws))
            if batch:
                assert not any(m['type'] in ('PointCloudMessage', 'GlbMessage', 'GuiImageMessage') for m in messages)
                assert next(m for m in messages if m['type'] == 'GuiCheckboxMessage'
                            and m['props']['label'] == 'Show ground truth')['value'] is True
                sample_selector = next(m for m in messages if m['type'] == 'GuiDropdownMessage'
                                       and m['props']['label'] == 'Sample')
                ws.send(msgspec.msgpack.encode({'type': 'GuiUpdateMessage', 'uuid': sample_selector['uuid'],
                                               'updates': {'value': 'a'}}))
                while not any(m['type'] == 'GuiUpdateMessage'
                              and 'Prepared 100%' in m.get('updates', {}).get('_markdown', '') for m in messages):
                    messages.extend(receive(ws))
            clouds = {m['name'] for m in messages if m['type'] == 'PointCloudMessage'}
            meshes = {m['name'] for m in messages if m['type'] == 'GlbMessage'}
            assert clouds == ({'/result_0/points'} if batch else {'/result_0/points', '/result_2/points'})
            assert meshes == (set() if batch else {'/result_1/mesh', '/result_3/mesh'})
            assert any(m['type'] == 'GuiImageMessage' for m in messages)
            if batch:
                quality = next(m for m in messages if m['type'] == 'GuiDropdownMessage'
                               and m['props']['label'] == 'Display quality')
                assert quality['value'] == 'full'
                for label in ('wt', 'defaults-v1', '42'):
                    checkbox = next(m for m in messages if m['type'] == 'GuiCheckboxMessage'
                                    and m['props']['label'] == label)
                    for value in (False, True):
                        ws.send(msgspec.msgpack.encode({'type': 'GuiUpdateMessage', 'uuid': checkbox['uuid'],
                                                       'updates': {'value': value}}))
                        changes = []
                        expected = f'{int(value)} matching runs'
                        while not any(m['type'] == 'GuiUpdateMessage'
                                      and expected in m.get('updates', {}).get('_markdown', '') for m in changes):
                            changes.extend(receive(ws))
                        assert any(m['type'] == 'PointCloudMessage' for m in changes) == value
            selector = next(m for m in messages if m['type'] == 'GuiDropdownMessage'
                            and m['props']['label'] == ('Sample' if batch else 'View'))
            ws.send(msgspec.msgpack.encode({'type': 'GuiUpdateMessage', 'uuid': selector['uuid'],
                                           'updates': {'value': 'b' if batch else 'TRELLIS output'}}))
            updates = []
            if batch:
                while not any(m['type'] == 'GuiUpdateMessage'
                              and 'failed' in m.get('updates', {}).get('_markdown', '') for m in updates):
                    updates.extend(receive(ws))
                assert any(m['type'] == 'RemoveSceneNodeMessage' for m in updates)
                # Complete b on disk while the viewer stays open, then refresh.
                atomic_json(directory / 'run.json', {'status': 'complete', 'artifacts': {
                    'points': {'path': str(points), 'kind': 'points', 'frame': 'camera_rdf'}}})
                refresh = next(m for m in messages if m['type'] == 'GuiButtonMessage'
                               and m['props']['label'] == 'Refresh results')
                ws.send(msgspec.msgpack.encode({'type': 'GuiUpdateMessage', 'uuid': refresh['uuid'],
                                               'updates': {'value': True}}))
                updates = []
                while not any(m['type'] == 'PointCloudMessage' for m in updates):
                    updates.extend(receive(ws))
            else:
                while not any(m['type'] == 'SetSceneNodeVisibilityMessage' and m['name'] == '/result_0'
                              and not m['visible'] for m in updates):
                    updates.extend(receive(ws))
            color_selector = next(m for m in messages if m['type'] == 'GuiDropdownMessage'
                                  and m['props']['label'] == 'Color mode')
            assert color_selector['value'] == '表面颜色'
            ws.send(msgspec.msgpack.encode({'type': 'GuiUpdateMessage', 'uuid': color_selector['uuid'],
                                           'updates': {'value': '深度'}}))
            updates = []
            while not any(m['type'] == 'PointCloudMessage' for m in updates):
                updates.extend(receive(ws))
        process.send_signal(getattr(signal, stop_signal))
        assert process.wait(timeout=10) == 0, log.read_text()
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0, 'Viewer port leaked after shutdown'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
