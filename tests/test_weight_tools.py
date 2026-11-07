"""Inspecting remote metadata must preserve local reproducibility records."""
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


def test_metadata_inspection_does_not_replace_download_manifest(monkeypatch, tmp_path):
    module = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/fetch_weights.py'))
    manifest = tmp_path / 'download-manifest.json'
    original = '{"trellis2":{"revision":"pinned","snapshot":"/local/weights","status":"downloaded"}}\n'
    manifest.write_text(original)
    monkeypatch.setenv('WT_WEIGHTS_ROOT', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['fetch_weights.py', '--inspect', '--public', '--models', 'trellis2'])
    fake_api = SimpleNamespace(model_info=lambda *args, **kwargs:
                               SimpleNamespace(sha='new-remote-revision', gated=False, siblings=[]))
    monkeypatch.setitem(module['main'].__globals__, 'HfApi', lambda **kwargs: fake_api)
    with pytest.raises(SystemExit) as result:
        module['main']()
    assert result.value.code == 0
    assert manifest.read_text() == original
