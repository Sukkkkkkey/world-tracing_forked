"""Project storage defaults. Raw inputs are never created or modified here."""

import os
from pathlib import Path


def _path(variable: str, default: str | Path) -> Path:
    return Path(os.environ.get(variable, default)).expanduser().resolve()


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = _path("WT_DATA_ROOT", "/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data")
RAW_ROOT = DATA_ROOT / "raw"
PROCESSED_ROOT = _path("WT_PROCESSED_ROOT", DATA_ROOT / "processed/world_tracing")
OUTPUT_ROOT = _path("WT_OUTPUT_ROOT", "/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing")
WEIGHTS_ROOT = _path("WT_WEIGHTS_ROOT", OUTPUT_ROOT / "weights")
CACHE_ROOT = _path("WT_CACHE_ROOT", REPO_ROOT / ".runtime/cache")
TRELLIS2_ROOT = _path("WT_TRELLIS2_ROOT", REPO_ROOT / "dependencies/TRELLIS.2")


def configure_cache_paths() -> None:
    """Set defaults before HF libraries import; preserve explicit overrides."""
    os.environ.setdefault("HF_HOME", str(WEIGHTS_ROOT / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(WEIGHTS_ROOT / "torch"))
    os.environ.setdefault("HF_MODULES_CACHE", str(CACHE_ROOT / "hf_modules"))
    os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))
    os.environ.setdefault("TORCH_EXTENSIONS_DIR", str(CACHE_ROOT / "torch_extensions"))
    os.environ.setdefault("FLEX_GEMM_AUTOTUNE_CACHE_PATH", str(CACHE_ROOT / "flex_gemm/autotune_cache.json"))
    os.environ.setdefault("TRITON_CACHE_DIR", str(CACHE_ROOT / "triton"))


def output_path(name: str) -> Path:
    return OUTPUT_ROOT / name
