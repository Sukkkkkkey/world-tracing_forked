#!/usr/bin/env python3
"""Build and install the reviewed Viser GUI lifecycle patch in the project env."""
import datetime
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path, data):
    """Publish complete files on CPFS, retaining the previous file on failure."""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(0o644)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def install():
    expected_env = Path(os.environ.get("WT_ENV_ROOT", ROOT / ".venv")).resolve()
    if Path(sys.prefix).resolve() != expected_env:
        raise RuntimeError("Load scripts/env.sh and use the project Python environment")

    lock = json.loads((ROOT / "configs/viser_client_patch.json").read_text())
    distribution = importlib.metadata.distribution("viser")
    if distribution.version != lock["viser_version"]:
        raise RuntimeError(f"Review the GUI patch for Viser {distribution.version}")
    client = Path(distribution.locate_file("viser/client")).resolve()
    if not client.is_relative_to(expected_env):
        raise RuntimeError(f"Viser is outside the project environment: {client}")
    source = client / "src/MessageHandler.tsx"
    package_lock = client / "package-lock.json"
    bundle = client / "build/index.html"
    patch = ROOT / "scripts/patches/viser-gui-lifecycle.patch"
    regression = ROOT / "tests/viser_gui_lifecycle.test.ts"
    source_hash = sha256(source)
    if source_hash not in (
        lock["original_source_sha256"],
        lock["patched_source_sha256"],
    ):
        raise RuntimeError("Unrecognized Viser GUI source. Preserve and review its changes")
    if sha256(package_lock) != lock["package_lock_sha256"]:
        raise RuntimeError("Viser frontend dependency lock has changed")

    inputs = {
        "viser_version": distribution.version,
        "source_sha256": lock["patched_source_sha256"],
        "package_lock_sha256": lock["package_lock_sha256"],
        "patch_sha256": sha256(patch),
        "regression_sha256": sha256(regression),
    }
    manifest = client / "build/wt-gui-lifecycle.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        if (
            source_hash == lock["patched_source_sha256"]
            and all(previous.get(key) == value for key, value in inputs.items())
            and previous.get("build_sha256") == sha256(bundle)
        ):
            print("Viser GUI lifecycle patch already verified", flush=True)
            return

    if (
        source_hash == lock["original_source_sha256"]
        and sha256(bundle) != lock["original_build_sha256"]
    ):
        raise RuntimeError("Unrecognized Viser frontend build. Preserve and review it")
    node = os.environ.get("WT_NODE_BINARY") or shutil.which("node")
    npm_cli = os.environ.get("WT_NPM_CLI") or shutil.which("npm")
    if not node or not npm_cli:
        raise RuntimeError("Building the Viser patch requires Node.js >=24 and npm")
    node = str(Path(node).resolve())
    node_version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(node_version.lstrip("v").split(".", 1)[0]) < 24:
        raise RuntimeError(f"Viser frontend requires Node.js >=24, found {node_version}")
    npm = [node, str(Path(npm_cli).resolve())]
    npm_version = subprocess.check_output(npm + ["--version"], text=True).strip()

    work = ROOT / ".runtime/build/viser-client"
    work.mkdir(parents=True, exist_ok=True)
    build_client = work / "client"
    shutil.copytree(
        client, build_client, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("build", "node_modules"),
    )
    shutil.copytree(client.parent / "_assets", work / "_assets", dirs_exist_ok=True)
    if source_hash == lock["original_source_sha256"]:
        apply = [
            "git", "apply", "--unidiff-zero", "--directory", str(build_client.relative_to(ROOT)),
            str(patch),
        ]
        subprocess.run(apply[:2] + ["--check"] + apply[2:], cwd=ROOT, check=True)
        subprocess.run(apply, cwd=ROOT, check=True)
    if sha256(build_client / "src/MessageHandler.tsx") != lock["patched_source_sha256"]:
        raise RuntimeError("Patched Viser source does not match the reviewed version")
    shutil.copy2(regression, build_client / "src/viser_gui_lifecycle.test.ts")
    env = dict(os.environ)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    env.setdefault("npm_config_cache", str(ROOT / ".runtime/cache/npm"))
    subprocess.run(npm + ["ci", "--no-audit", "--no-fund"], cwd=build_client, env=env, check=True)
    subprocess.run(npm + ["run", "test"], cwd=build_client, env=env, check=True)
    subprocess.run(npm + ["run", "build"], cwd=build_client, env=env, check=True)

    built = build_client / "build/index.html"
    if not built.is_file() or built.stat().st_size == 0:
        raise RuntimeError("Viser frontend build is missing")
    backup = ROOT / ".runtime/cache/viser-client-original"
    backup.mkdir(parents=True, exist_ok=True)
    for original in (source, bundle):
        destination = backup / (sha256(original) + "-" + original.name)
        if not destination.exists():
            atomic_write(destination, original.read_bytes())

    result = {
        **inputs,
        "build_sha256": sha256(built),
        "node_version": node_version,
        "npm_version": npm_version,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    # Publish only after all frontend tests, type checking and bundling succeed.
    # A retry validates the installed hashes before deciding to skip rebuilding.
    atomic_write(source, (build_client / "src/MessageHandler.tsx").read_bytes())
    atomic_write(bundle, built.read_bytes())
    atomic_write(manifest, (json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps(result, indent=2), flush=True)


def main():
    lock_path = ROOT / ".runtime/locks/setup-viser-client.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        install()


if __name__ == "__main__":
    main()
