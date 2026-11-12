"""Storage correctness when the final filesystem rejects backward write seeks."""
from pathlib import Path

import numpy as np
import pytest

from wt import artifacts


def test_npz_roundtrip_to_nonseekable_destination(tmp_path, monkeypatch):
    target_dir = tmp_path / 'mounted'
    target_dir.mkdir()
    monkeypatch.setattr(artifacts, 'STAGING_ROOT', tmp_path / 'staging')
    original_open = Path.open
    class SequentialWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, value):
            return self.stream.write(value)
        def seek(self, *args):
            raise OSError(22, 'Filesystem does not support write seeks')
    def open_path(path, mode='r', *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return SequentialWriter(stream) if path.parent == target_dir and mode == 'wb' else stream
    monkeypatch.setattr(Path, 'open', open_path)
    expected = np.random.default_rng(42).normal(size=(3, 4, 5)).astype(np.float32)
    path = target_dir / 'prediction.npz'
    artifacts.save_npz(path, xyz=expected, mask=expected[..., 0] > 0)
    with np.load(path, allow_pickle=False) as actual:
        np.testing.assert_array_equal(actual['xyz'], expected)
        np.testing.assert_array_equal(actual['mask'], expected[..., 0] > 0)
    assert not list((tmp_path / 'staging').iterdir())


def test_failed_artifact_writer_preserves_previous_result(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, 'STAGING_ROOT', tmp_path / 'staging')
    path = tmp_path / 'prediction.npz'
    path.write_bytes(b'previous complete result')
    with pytest.raises(RuntimeError, match='interrupted'):
        with artifacts.atomic_artifact(path) as staged:
            staged.write_bytes(b'incomplete replacement')
            raise RuntimeError('interrupted')
    assert path.read_bytes() == b'previous complete result'
    assert not list((tmp_path / 'staging').iterdir())
    assert not list(tmp_path.glob('*.partial'))
