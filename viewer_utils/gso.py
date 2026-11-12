"""Resolve textured GT from the GSO dataset's frozen metadata."""
import json
from pathlib import Path

import numpy as np


def gso_display_source(sample, sample_dir):
    """Find the original mesh and asset→camera transform without rewriting data."""
    if sample.get('dataset') != 'gso-v1':
        return None
    evaluation_dir = Path(sample['evaluation_dir'])
    if not evaluation_dir.is_absolute():
        evaluation_dir = sample_dir / evaluation_dir
    inventory_path = evaluation_dir.parent.parent / 'inventory.jsonl'
    camera_path = evaluation_dir / 'camera.json'
    asset_id = sample['asset_id']
    with inventory_path.open() as stream:
        asset = next((record for line in stream if line.strip()
                      if (record := json.loads(line))['asset_id'] == asset_id), None)
    if asset is None:
        raise ValueError(f'GT asset {asset_id} not found in {inventory_path}')
    path = Path(asset['mesh'])
    if not path.is_absolute():
        path = inventory_path.parent / path
    camera = json.loads(camera_path.read_text())
    matrices = [np.asarray(camera[k], dtype=float) for k in ('T_world_to_camera', 'T_asset_to_world')]
    if any(m.shape != (4, 4) or not np.isfinite(m).all()
           or not np.allclose(m[3], [0, 0, 0, 1]) for m in matrices):
        raise ValueError('Invalid GT asset/camera transform')
    return path, matrices[0] @ matrices[1], [inventory_path, camera_path]
