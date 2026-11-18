"""Compatibility entry point for GSO textured ground truth."""
from .ground_truth import textured_gt_source


def gso_display_source(sample, sample_dir):
    """Resolve GSO source geometry using the shared frozen-metadata adapter."""
    if sample.get("dataset") != "gso-v1":
        return None
    return textured_gt_source(sample, sample_dir)
