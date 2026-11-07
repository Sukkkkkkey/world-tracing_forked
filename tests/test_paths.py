"""Storage routing must respect overrides and must never create raw data."""
import os
from pathlib import Path
import runpy

MODULE = Path(__file__).resolve().parents[1] / 'wt/paths.py'
CACHE_KEYS = ('HF_HOME', 'TORCH_HOME', 'XDG_CACHE_HOME', 'TORCH_EXTENSIONS_DIR',
              'FLEX_GEMM_AUTOTUNE_CACHE_PATH', 'TRITON_CACHE_DIR', 'HF_MODULES_CACHE')


def test_storage_overrides_separate_weights_from_executable_caches(monkeypatch, tmp_path):
    for key in CACHE_KEYS + ('WT_WEIGHTS_ROOT', 'WT_PROCESSED_ROOT',):
        monkeypatch.delenv(key, raising=False)
    data = tmp_path / 'inputs'
    output = tmp_path / 'runs'
    cache = tmp_path / 'local-cache'
    monkeypatch.setenv('WT_CACHE_ROOT', str(cache))
    monkeypatch.setenv('WT_DATA_ROOT', str(data))
    monkeypatch.setenv('WT_OUTPUT_ROOT', str(output))
    paths = runpy.run_path(str(MODULE))
    paths['configure_cache_paths']()
    assert paths['RAW_ROOT'] == data / 'raw'
    assert paths['output_path']('sample.rrd') == output / 'sample.rrd'
    assert paths['PROCESSED_ROOT'] == data / 'processed/world_tracing'
    assert all(Path(os.environ[key]).is_relative_to(output) for key in ('HF_HOME', 'TORCH_HOME'))
    assert all(Path(os.environ[key]).is_relative_to(cache) for key in CACHE_KEYS if key not in ('HF_HOME', 'TORCH_HOME'))
    assert not data.exists() and not output.exists() and not cache.exists()


def test_explicit_cache_override_is_preserved(monkeypatch, tmp_path):
    explicit = str(tmp_path / 'shared-hf')
    monkeypatch.setenv('HF_HOME', explicit)
    paths = runpy.run_path(str(MODULE))
    paths['configure_cache_paths']()
    assert os.environ['HF_HOME'] == explicit


def test_default_cli_output_is_independent_of_working_directory(monkeypatch, tmp_path):
    for key in ('WT_DATA_ROOT', 'WT_OUTPUT_ROOT', 'WT_TRELLIS2_ROOT'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    paths = runpy.run_path(str(MODULE))
    assert paths['output_path']('infer_rgba.rrd') == Path('/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/infer_rgba.rrd')
    assert paths['TRELLIS2_ROOT'] == MODULE.parents[1] / 'dependencies/TRELLIS.2'
