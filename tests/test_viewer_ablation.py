"""WT ablation indexing, lazy selection and per-configuration input controls."""
import json
import time

import numpy as np
from PIL import Image
import viser

import viewer
from viewer_utils.experiments import scan_viewer_experiment, seed_options


def make_run(root, sample, config, seed=42):
    directory = root / sample / config
    directory.mkdir(parents=True)
    xyz = np.arange(24, dtype=np.float32).reshape(2, 2, 2, 3) / 20
    rgb = np.full((2, 2, 3), 220 if config == 'baseline' else 40, dtype=np.uint8)
    np.savez(directory / 'prediction.npz', xyz=xyz, rgb=rgb, mask=np.ones((2, 2, 2), bool))
    Image.fromarray(rgb).save(directory / 'input.png')
    (directory / 'metrics.json').write_text(json.dumps(
        dict(sample=sample, variant=config, seed=seed, object_ratio=0.5 if config == 'crop50' else 2 / 3)))
    return directory


def wait_ready(browser):
    deadline = time.monotonic() + 10
    while 'Prepared 100%' not in browser.status.content and time.monotonic() < deadline:
        assert 'Loading failed' not in browser.status.content, browser.status.content
        time.sleep(0.02)
    assert 'Prepared 100%' in browser.status.content, browser.status.content


def test_ablation_index_is_metadata_only_and_handles_incomplete_runs(tmp_path, monkeypatch):
    make_run(tmp_path, 'a', 'baseline')
    bad = make_run(tmp_path, 'b', 'crop50')
    (bad / 'metrics.json').write_text('not JSON')
    missing = make_run(tmp_path, 'a', 'pending')
    (missing / 'prediction.npz').unlink()
    (tmp_path / 'a' / 'input.json').write_text(json.dumps({'ground_truth': {
        'path': 'gt.ply', 'kind': 'mesh', 'frame': 'camera_rdf'}}))
    def forbidden(*args, **kwargs):
        raise AssertionError('Indexing must not read geometry/images')
    monkeypatch.setattr(np, 'load', forbidden)
    monkeypatch.setattr(Image, 'open', forbidden)
    samples, runs, errors = scan_viewer_experiment(tmp_path)
    assert set(samples) == {'a', 'b'} and len(runs) == 3
    assert samples['a']['ground_truth']['path'] == str(tmp_path / 'a' / 'gt.ply')
    assert seed_options(runs) == ('42', 'unknown') and len(errors) == 1
    assert next(r for r in runs if r.config_id == 'pending').data['status'] == 'missing prediction.npz'
    args = viewer.parse_args(['--experiment', str(tmp_path)])
    assert args.quality == 'full' and args.color_mode == 'surface'


def test_ablation_lazy_config_comparison_and_input_switch(tmp_path, monkeypatch):
    for sample in ('a', 'b'):
        for config in ('baseline', 'crop50'):
            make_run(tmp_path, sample, config)
    loaded, previews = [], []
    original, populate = viewer.read_run_geometry, viewer.populate_viewer
    controls = {}
    server = viser.ViserServer(host='127.0.0.1', port=0, verbose=False)
    add_dropdown, add_image, add_markdown = server.gui.add_dropdown, server.gui.add_image, server.gui.add_markdown
    def dropdown(label, *args, **kwargs):
        handle = add_dropdown(label, *args, **kwargs)
        controls[label] = handle
        return handle
    def image(*args, **kwargs):
        handle = add_image(*args, **kwargs)
        controls['last_image'] = handle
        return handle
    def markdown(content, *args, **kwargs):
        handle = add_markdown(content, *args, **kwargs)
        if content.startswith('| Parameter'):
            controls['details'] = handle
        return handle
    def load(run, **kwargs):
        loaded.append((run.sample_id, run.config_id))
        return original(run, **kwargs)
    def show(server, image, geometries, input_views=None):
        previews.append(input_views)
        return populate(server, image, geometries, input_views)
    monkeypatch.setattr(server.gui, 'add_dropdown', dropdown)
    monkeypatch.setattr(server.gui, 'add_image', image)
    monkeypatch.setattr(server.gui, 'add_markdown', markdown)
    monkeypatch.setattr(viewer, 'read_run_geometry', load)
    monkeypatch.setattr(viewer, 'populate_viewer', show)
    browser = viewer.ExperimentViewer(server, tmp_path)
    try:
        assert not loaded and browser.show_gt.value
        browser.sample.value = 'a'
        wait_ready(browser)
        assert set(loaded) == {('a', 'baseline'), ('a', 'crop50')}
        assert '2 geometries / 2 matching runs' in browser.status.content
        assert set(previews[-1]) == {'baseline / seed 42', 'crop50 / seed 42'}
        assert (controls['last_image'].image[..., :3] == 220).all()
        controls['Input / configuration'].value = 'crop50 / seed 42'
        deadline = time.monotonic() + 5
        while controls['last_image'].label != 'crop50 / seed 42' and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (controls['last_image'].image[..., :3] == 40).all()
        assert '| Object ratio | 0.5 |' in controls['details'].content
        assert len(loaded) == 2  # Image selection does not reload geometry.
        browser.config.value = ('crop50',)
        wait_ready(browser)
        assert tuple(previews[-1]) == ('crop50 / seed 42',)
        assert '1 geometries / 1 matching runs' in browser.status.content
        browser.sample.value = 'b'
        wait_ready(browser)
        assert loaded[-1] == ('b', 'crop50')
        browser.config.value = ()
        wait_ready(browser)
        assert previews[-1] == {} and '0 geometries / 0 matching runs' in browser.status.content
        browser.refresh()
        assert browser.config.value == ()
    finally:
        browser.close()
        server.stop()
