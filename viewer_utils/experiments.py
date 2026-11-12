"""Select an input-layout adapter without changing the batch runner's contract."""
from pathlib import Path

from wt.experiment import scan_experiment
from .ablation import is_ablation, scan_ablation


def experiment_layout(root):
    root = Path(root)
    if (root / 'experiment.json').is_file():
        return 'Experiment'
    if is_ablation(root):
        return 'Ablation'
    raise ValueError('Expected experiment.json + samples/, or WT ablation <sample>/<config>/prediction.npz')


def scan_viewer_experiment(root):
    return scan_experiment(root) if experiment_layout(root) == 'Experiment' else scan_ablation(root)


def seed_options(runs):
    seeds = {r.seed for r in runs}
    return tuple(str(x) for x in sorted(seeds, key=lambda x: (not isinstance(x, int), x)))
