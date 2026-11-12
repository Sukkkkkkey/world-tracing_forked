"""Fetch and audit the official AlexNet backbone used by LPIPS."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import urllib.request

from wt.artifacts import atomic_artifact
from wt.experiment import atomic_json, file_digest
from wt.paths import CACHE_ROOT, WEIGHTS_ROOT, configure_cache_paths

URL = "https://download.pytorch.org/models/alexnet-owt-7be5be79.pth"
SIZE = 244408911
CHECKSUM = "7be5be791159472b1fbf3c69796f7cb30dca7ad8466c2df70058c37116cdee02"


def main():
    configure_cache_paths()
    target = WEIGHTS_ROOT / "torch/hub/checkpoints/alexnet-owt-7be5be79.pth"
    if not target.exists():
        print(f"Downloading {URL}, {SIZE} bytes to {target}", flush=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with atomic_artifact(target) as temporary:
            checksum = hashlib.sha256()
            length = 0
            with opener.open(URL, timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    checksum.update(chunk)
                    length += len(chunk)
            if length != SIZE or checksum.hexdigest() != CHECKSUM:
                raise ValueError("AlexNet download failed size/SHA256 verification")
    checksum = file_digest(target)
    if target.stat().st_size != SIZE or checksum != CHECKSUM:
        raise ValueError("Installed AlexNet checkpoint failed verification")
    import lpips
    lpips.LPIPS(net="alex", version="0.1", verbose=False).eval()
    linear = Path(lpips.__file__).parent / "weights/v0.1/alex.pth"
    audit = {
        "alexnet": {"source": URL, "path": str(target), "bytes": SIZE, "sha256": checksum},
        "lpips_linear": {"path": str(linear), "sha256": file_digest(linear)},
        "versions": {name: importlib.metadata.version(name)
                     for name in ("torch", "torchvision", "lpips", "numpy", "scipy", "trimesh")},
    }
    atomic_json(CACHE_ROOT / "multiview_environment.json", audit)
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
