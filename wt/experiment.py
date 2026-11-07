"""Versioned, model-independent batch output contract shared by runner and viewer."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import uuid

SCHEMA_VERSION = 1
WT_METHODS = ('wt', 'trellis2', 'wt_trellis2')
METHODS = (*WT_METHODS, 'pixal3d')

# Pixal3D estimates FoV, but its distance uses a normalized object cube. The
# existing native-camera protocol requires scale and pose in the original view.
CAMERA_NA = {
    'trellis2': 'Native TRELLIS has no input-camera pose',
    'pixal3d': 'MoGe FoV and normalized cube distance; original-view metric pose is not established',
}


def identifier(value: str) -> str:
    # Keep original Unicode asset IDs (e.g. Pokémon) without permitting paths.
    if (not isinstance(value, str) or not value or not value[0].isalnum()
            or any(not (char.isalnum() or char in '_.-') for char in value)):
        raise ValueError(f'Invalid directory ID: {value!r}')
    return value


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_reference(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def run_directory(root: Path, sample: str, method: str, config: str, seed: int) -> Path:
    if method not in METHODS or seed < 0:
        raise ValueError('Unknown method or negative seed')
    return root / 'samples' / identifier(sample) / method / identifier(config) / f'seed-{seed:04d}'


@dataclass
class RunRecord:
    directory: Path
    sample_id: str
    method: str
    config_id: str
    seed: int
    data: dict

    @property
    def label(self):
        return f'{self.method} / {self.config_id} / seed {self.seed}'


def scan_experiment(root: Path):
    """Read only small JSON indexes, including unfinished runs; never load geometry."""
    header = read_json(root / 'experiment.json')
    if not isinstance(header, dict) or header.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Unsupported experiment schema_version')
    samples, runs, errors = {}, [], []
    for path in sorted((root / 'samples').glob('*/input.json')):
        try:
            data = read_json(path)
            data['image_path'] = resolve_reference(path.parent, data['image'])
            samples[path.parent.name] = data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f'{path}: {exc}')
    for path in sorted((root / 'samples').glob('*/*/*/seed-*/run.json')):
        try:
            data = read_json(path)
            if not isinstance(data, dict):
                raise ValueError('run.json must contain an object')
            sample, method, config, seed_dir = path.relative_to(root / 'samples').parts[:4]
            if method not in METHODS:
                raise ValueError(f'Unknown method {method}')
            runs.append(RunRecord(path.parent, sample, method, config, int(seed_dir[5:]), data))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f'{path}: {exc}')
    return samples, runs, errors
