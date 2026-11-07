"""Create local TRELLIS.2 pipeline descriptors from verified model snapshots.

Only writes derived configurations under the output weights directory; downloaded
upstream files and WT integration code remain untouched.
"""
import json
import os
from pathlib import Path


def main():
    root = Path(os.environ['WT_WEIGHTS_ROOT'])
    hf = json.loads((root / 'download-manifest.json').read_text())
    aux = json.loads((root / 'modelscope/download-manifest.json').read_text())
    if any(record['status'] != 'verified' for record in aux.values()):
        raise ValueError('Auxiliary downloads must pass checksum verification first')
    trellis = Path(hf['trellis2']['snapshot'])
    structure = Path(hf['structure_decoder']['snapshot'])
    destination = root / 'local-pipelines/TRELLIS.2'
    destination.mkdir(parents=True, exist_ok=True)
    for filename in ('pipeline.json', 'texturing_pipeline.json'):
        config = json.loads((trellis / filename).read_text())
        args = config['args']
        for name, reference in args['models'].items():
            if reference.startswith('microsoft/TRELLIS-image-large/'):
                path = structure / reference.removeprefix('microsoft/TRELLIS-image-large/')
            elif reference.startswith('ckpts/'):
                path = trellis / reference
            else:
                raise ValueError(f'Unrecognised upstream model reference: {reference}')
            for suffix in ('.json', '.safetensors'):
                if not path.with_suffix(suffix).is_file():
                    raise FileNotFoundError(str(path) + suffix)
            args['models'][name] = str(path)
        args['image_cond_model']['args']['model_name'] = aux['dinov3']['directory']
        args['rembg_model']['args']['model_name'] = aux['rmbg']['directory']
        output = destination / filename
        output.write_text(json.dumps(config, indent=2) + '\n')
        print(output, flush=True)


if __name__ == '__main__':
    main()
