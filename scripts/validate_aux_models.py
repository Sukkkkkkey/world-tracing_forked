"""Offline GPU validation of ModelScope weights through TRELLIS.2's wrappers."""
import gc
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from trellis2.modules.image_feature_extractor import DinoV3FeatureExtractor
from trellis2.pipelines.rembg import BiRefNet


def main():
    torch.manual_seed(42)
    torch.set_num_threads(8)
    root = Path(os.environ['WT_WEIGHTS_ROOT']) / 'modelscope'
    manifest = json.loads((root / 'download-manifest.json').read_text())
    if any(record['status'] != 'verified' for record in manifest.values()):
        raise ValueError('Complete and verify both downloads before inference')
    image_path = Path(__file__).resolve().parents[1] / 'examples/test_images/object/obj014_leather_briefcase.png'
    image = Image.open(image_path).convert('RGB')
    model = DinoV3FeatureExtractor(manifest['dinov3']['directory'], image_size=512)
    model.cuda()
    with torch.inference_mode():
        features = model([image])
    assert features.shape == (1, 1029, 1024)
    assert torch.isfinite(features).all() and features.std() > 0
    report = dict(image=str(image_path), seed=42, gpu=torch.cuda.get_device_name(),
                  dinov3=dict(path=manifest['dinov3']['directory'], shape=list(features.shape),
                              finite=True, std=features.std().item()))
    print(json.dumps(report['dinov3']), flush=True)
    del model, features
    gc.collect()
    torch.cuda.empty_cache()

    model = BiRefNet(manifest['rmbg']['directory'])
    model.cuda()
    logits_report = {}

    def check_logits(module, inputs, outputs):
        logits = outputs[-1]
        assert logits.shape == (1, 1, 1024, 1024)
        assert torch.isfinite(logits).all()
        logits_report.update(shape=list(logits.shape), finite=True)

    hook = model.model.register_forward_hook(check_logits)
    with torch.inference_mode():
        rgba = model(image.copy())
    hook.remove()
    alpha = np.asarray(rgba.getchannel('A'))
    assert rgba.size == image.size and alpha.max() > alpha.min()
    output = Path(os.environ['WT_OUTPUT_ROOT']) / 'validation'
    output.mkdir(parents=True, exist_ok=True)
    rgba.save(output / 'rmbg-object.png')
    report['rmbg'] = dict(path=manifest['rmbg']['directory'], logits=logits_report,
                          size=list(rgba.size), alpha_min=int(alpha.min()), alpha_max=int(alpha.max()),
                          output=str(output / 'rmbg-object.png'))
    (output / 'modelscope-aux-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['rmbg']), flush=True)


if __name__ == '__main__':
    main()
