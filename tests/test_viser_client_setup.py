"""Installer guards and publication failure behavior, without downloading tools."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import setup_viser_client as installer


@pytest.fixture
def installed_client(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "ROOT", tmp_path)
    environment = tmp_path / ".venv"
    monkeypatch.setattr(installer, "sys", SimpleNamespace(prefix=str(environment)))
    monkeypatch.setenv("WT_ENV_ROOT", str(environment))
    client = environment / "viser/client"
    for directory in (client / "src", client / "build", tmp_path / "configs",
                      tmp_path / "scripts/patches", tmp_path / "tests"):
        directory.mkdir(parents=True)
    source = client / "src/MessageHandler.tsx"
    source.write_bytes(b"patched source")
    (client / "package-lock.json").write_bytes(b"dependency lock")
    bundle = client / "build/index.html"
    bundle.write_bytes(b"patched build")
    patch = tmp_path / "scripts/patches/viser-gui-lifecycle.patch"
    patch.write_bytes(b"reviewed patch")
    regression = tmp_path / "tests/viser_gui_lifecycle.test.ts"
    regression.write_bytes(b"regression")
    lock = {
        "viser_version": "1.1.1",
        "original_source_sha256": hashlib.sha256(b"original source").hexdigest(),
        "patched_source_sha256": installer.sha256(source),
        "package_lock_sha256": installer.sha256(client / "package-lock.json"),
        "original_build_sha256": hashlib.sha256(b"original build").hexdigest(),
    }
    (tmp_path / "configs/viser_client_patch.json").write_text(json.dumps(lock))
    manifest = {
        "viser_version": "1.1.1",
        "source_sha256": lock["patched_source_sha256"],
        "package_lock_sha256": lock["package_lock_sha256"],
        "patch_sha256": installer.sha256(patch),
        "regression_sha256": installer.sha256(regression),
        "build_sha256": installer.sha256(bundle),
    }
    (client / "build/wt-gui-lifecycle.json").write_text(json.dumps(manifest))
    distribution = SimpleNamespace(
        version="1.1.1", locate_file=lambda path: environment / path,
    )
    monkeypatch.setattr(installer.importlib.metadata, "distribution", lambda _: distribution)
    return client


def test_verified_install_is_reusable_without_build_tools(installed_client, monkeypatch):
    monkeypatch.setenv("WT_NODE_BINARY", "/missing-node")
    monkeypatch.setenv("WT_NPM_CLI", "/missing-npm")
    bundle = installed_client / "build/index.html"
    before = (bundle.read_bytes(), bundle.stat().st_mtime_ns)
    installer.install()
    assert (bundle.read_bytes(), bundle.stat().st_mtime_ns) == before


@pytest.mark.parametrize("path,contents,error", [
    ("src/MessageHandler.tsx", b"custom source", "Unrecognized Viser GUI source"),
    ("package-lock.json", b"different dependencies", "dependency lock has changed"),
])
def test_unrecognized_inputs_preserve_installed_build(
    installed_client, path, contents, error,
):
    (installed_client / path).write_bytes(contents)
    with pytest.raises(RuntimeError, match=error):
        installer.install()
    assert (installed_client / "build/index.html").read_bytes() == b"patched build"


def test_unrecognized_original_build_is_preserved(installed_client):
    (installed_client / "src/MessageHandler.tsx").write_bytes(b"original source")
    with pytest.raises(RuntimeError, match="Unrecognized Viser frontend build"):
        installer.install()
    assert (installed_client / "build/index.html").read_bytes() == b"patched build"


def test_failed_atomic_publish_preserves_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "index.html"
    target.write_bytes(b"previous build")

    def fail_replace(source, destination):
        raise OSError("publication failed")

    monkeypatch.setattr(installer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failed"):
        installer.atomic_write(target, b"new build")
    assert target.read_bytes() == b"previous build"
    assert list(tmp_path.iterdir()) == [target]
