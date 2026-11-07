"""Stage seek-based archives on CPFS, then publish sequentially to mounted storage."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from wt.paths import CACHE_ROOT

STAGING_ROOT = CACHE_ROOT / 'artifact-staging'


@contextmanager
def atomic_artifact(destination):
    """Keep the previous artifact intact unless writing and transfer both succeed."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='wt-', suffix=destination.suffix,
                                     dir=STAGING_ROOT, delete=False) as stream:
        staged = Path(stream.name)
    partial = destination.with_name('.' + destination.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        yield staged
        size = staged.stat().st_size
        if not size:
            raise ValueError('Artifact writer produced an empty file')
        with staged.open('rb') as source, partial.open('wb') as output:
            shutil.copyfileobj(source, output, 4 * 1024 * 1024)
        if partial.stat().st_size != size:
            raise OSError('Published artifact size differs from its staged source')
        os.replace(partial, destination)
    finally:
        staged.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)


def save_npz(destination, **arrays):
    """Write the same compressed NumPy archive without seeking on the destination."""
    import numpy as np
    destination = Path(destination)
    if not str(destination).endswith('.npz'):
        destination = Path(str(destination) + '.npz')
    with atomic_artifact(destination) as staged:
        np.savez_compressed(staged, **arrays)


def save_torch(value, destination):
    """Write a PyTorch ZIP archive through the same storage boundary."""
    import torch
    with atomic_artifact(destination) as staged:
        torch.save(value, staged)
