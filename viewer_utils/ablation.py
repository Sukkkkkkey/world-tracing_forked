"""Adapter for WT ablations saved as <sample>/<config>/prediction.npz.

Indexing reads JSON only. This layout's point maps use WT camera RDF coordinates;
it is not a general convention for arbitrary model outputs.
"""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class AblationRun:
    directory: Path
    sample_id: str
    method: str
    config_id: str
    seed: int | str
    data: dict

    @property
    def label(self):
        return f'{self.config_id} / seed {self.seed}'


def is_ablation(root):
    root = Path(root)
    return (next(root.glob('*/*/prediction.npz'), None) is not None
            or next(root.glob('*/*/metrics.json'), None) is not None)


def configuration_details(record):
    names = {'steps': 'Steps', 'center_crop': 'Center crop',
             'object_ratio': 'Object ratio', 'bg_color': 'Background RGB',
             'erode': 'Alpha erosion', 'crop_y_x_side': 'Crop (y, x, side)'}
    rows = [f'| {label} | {record[key]} |' for key, label in names.items() if key in record]
    return '| Parameter | Value |\n| --- | --- |\n' + '\n'.join(rows) if rows else 'No configuration parameters recorded.'


def scan_ablation(root):
    """Adapt sparse/incomplete configurations without rewriting experiment files."""
    root = Path(root).resolve()
    samples, runs, errors = {}, [], []
    directories = {p.parent for pattern in ('*/*/prediction.npz', '*/*/metrics.json')
                   for p in root.glob(pattern)}
    for directory in sorted(directories, key=lambda p: (p.parent.name, p.name != 'baseline', p.name)):
        sample_id, config_id = directory.parent.name, directory.name
        record = {}
        metrics = directory / 'metrics.json'
        try:
            record = json.loads(metrics.read_text())
            if not isinstance(record, dict):
                raise ValueError('expected a JSON object')
            if record.get('sample', sample_id) != sample_id or record.get('variant', config_id) != config_id:
                raise ValueError('sample/variant disagrees with directory')
        except (OSError, ValueError) as exc:
            errors.append(f'{sample_id}/{config_id}: metrics unavailable: {exc}')
            record = {}
        seed = record.get('seed', 'unknown')
        if not isinstance(seed, int) or isinstance(seed, bool):
            seed = 'unknown'
        data = {
            'status': 'complete' if (directory / 'prediction.npz').is_file() else 'missing prediction.npz',
            'artifacts': {'points': {'path': 'prediction.npz', 'kind': 'points', 'frame': 'camera_rdf'}},
            'display_input': {'path': str(directory / 'input.png'), 'details': configuration_details(record)},
        }
        runs.append(AblationRun(directory, sample_id, 'wt', config_id, seed, data))
        if sample_id not in samples:
            sample = {'image_path': directory / 'input.png',
                      'display_notice': 'Ablation: WT camera RDF; original scale, no registration. '
                                        'No full ground-truth geometry declared for this sample.'}
            # Optional sample-level metadata uses the standard input.json contract.
            # Resolve references here, not against samples/ in the GUI.
            metadata = directory.parent / 'input.json'
            if metadata.is_file():
                try:
                    extra = json.loads(metadata.read_text())
                    if not isinstance(extra, dict):
                        raise ValueError('expected a JSON object')
                    for key in ('image', 'evaluation_dir'):
                        if key in extra:
                            path = Path(extra[key]).expanduser()
                            extra[key] = str(path if path.is_absolute() else metadata.parent / path)
                    if 'ground_truth' in extra:
                        gt = dict(extra['ground_truth'])
                        path = Path(gt['path']).expanduser()
                        gt['path'] = str(path if path.is_absolute() else metadata.parent / path)
                        extra['ground_truth'] = gt
                        sample['display_notice'] = 'Ablation: original scale, no registration.'
                    sample.update(extra)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    errors.append(f'{sample_id}: input metadata unavailable: {exc}')
            samples[sample_id] = sample
    return samples, runs, errors
