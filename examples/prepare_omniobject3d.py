"""Freeze a category-balanced OmniObject3D subset and render inputs with the GSO camera protocol."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from examples.prepare_gso_views import prepare
from wt.experiment import atomic_json, file_digest, identifier, read_json
from wt.paths import PROCESSED_ROOT


def asset_rank(value):
    return hashlib.sha256(("20261111:asset:" + value).encode()).hexdigest()


def inspect_archive(root, entry, *, archive_path=None):
    archive_path = Path(archive_path) if archive_path is not None else root / "source_archives" / Path(entry["path"]).name
    category = archive_path.name.removesuffix(".tar.gz")
    index_path = root / "archive_indexes" / (category + ".json")
    if archive_path.stat().st_size != entry["size"]:
        raise ValueError(f"Archive size changed: {archive_path}")
    if file_digest(archive_path) != entry["sha256"]:
        raise ValueError(f"Archive SHA-256 changed: {archive_path}")
    if index_path.exists():
        index = read_json(index_path)
        if index["sha256"] != entry["sha256"]:
            raise ValueError("Archive index refers to another source")
        return index
    meshes = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError(f"Unsafe archive member: {member.name}")
            if member.isfile() and path.suffix.lower() == ".obj":
                if path.parent.name != "Scan":
                    raise ValueError(f"Unexpected mesh layout: {member.name}")
                asset_id = identifier(path.parent.parent.name)
                if asset_id in meshes:
                    raise ValueError(f"Multiple meshes for one asset: {asset_id}")
                meshes[asset_id] = str(path)
    index = {"category": category, "archive": str(archive_path), "sha256": entry["sha256"],
             "assets": [{"source_id": key, "mesh_member": meshes[key]}
                        for key in sorted(meshes, key=asset_rank)]}
    atomic_json(index_path, index)
    print(f"INDEX {category} {len(meshes)} assets", flush=True)
    return index


def freeze_selection(root, indexes):
    selection_path = root / "selection.json"
    source_digest = file_digest(root / "download_plan.json")
    if selection_path.exists():
        selection = read_json(selection_path)
        if (selection["download_plan_sha256"] != source_digest or
                selection["download_complete_sha256"] != file_digest(root / "download_complete.json")):
            raise ValueError("Frozen download plan changed")
        return selection
    by_category = [[dict(asset, category=index["category"], archive=index["archive"],
                         archive_sha256=index["sha256"]) for asset in index["assets"]]
                   for index in indexes]
    pilot = []
    for group in by_category:
        if group and len(pilot) < 10:
            pilot.append(group.pop(0))
    formal = []
    while len(formal) < 100 and any(by_category):
        for group in by_category:
            if group and len(formal) < 100:
                formal.append(group.pop(0))
    if len(pilot) != 10 or len(formal) != 100:
        raise ValueError("Frozen categories contain fewer than 110 distinct assets")
    for split, samples in (("pilot", pilot), ("eval100", formal)):
        for asset in samples:
            asset["asset_id"] = "omni_" + asset["source_id"]
            asset["split"] = split
    selection = {
        "dataset": "omniobject3d-ood-v1",
        "download_plan_sha256": source_digest,
        "download_complete_sha256": file_digest(root / "download_complete.json"),
        "selection_rule": ("Within each frozen category rank IDs by SHA256('20261111:asset:' + ID); "
                           "pilot takes the first ID from the first 10 nonempty categories; "
                           "formal takes 100 remaining IDs round-robin across available categories; "
                           "source acquisition exclusions are frozen before inference"),
        "selection_uses_model_outputs": False,
        "source_category_counts": {index["category"]: len(index["assets"]) for index in indexes},
        "samples": pilot + formal,
    }
    atomic_json(selection_path, selection)
    atomic_json(root / "split.json", {
        "dataset": selection["dataset"],
        "selection_sha256": file_digest(selection_path),
        "splits": {split: [asset["asset_id"] for asset in selection["samples"] if asset["split"] == split]
                   for split in ("pilot", "eval100")},
    })
    return selection


def extract_selected(root, index, samples):
    selected = {sample["source_id"]: sample for sample in samples
                if sample["category"] == index["category"]}
    extracted = {key: {} for key in selected}
    destination = root / "source_scans" / index["category"]
    with tarfile.open(index["archive"], "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if not member.isfile() or len(path.parts) < 3 or path.parts[0] not in selected:
                continue
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member: {member.name}")
            if path.parts[1] != "Scan":
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            existing = target.exists()
            writer = None if existing else partial.open("wb")
            checksum = hashlib.sha256()
            try:
                with archive.extractfile(member) as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        checksum.update(block)
                        if writer is not None:
                            writer.write(block)
            finally:
                if writer is not None:
                    writer.close()
            actual = checksum.hexdigest()
            if existing:
                if file_digest(target) != actual:
                    raise ValueError(f"Existing extracted source changed: {target}")
            else:
                partial.replace(target)
            extracted[path.parts[0]][str(path)] = actual
    inventory = []
    for source_id, sample in selected.items():
        mesh = destination / sample["mesh_member"]
        files = extracted[source_id]
        if not mesh.is_file() or not any(name.lower().endswith((".jpg", ".jpeg", ".png"))
                                        for name in files):
            raise ValueError(f"Missing source mesh or texture: {source_id}")
        inventory.append({
            **sample, "mesh": str(mesh), "source_units": "unknown", "valid": True,
            "source_files_sha256": files, "source_mesh_sha256": file_digest(mesh),
        })
    print(f"EXTRACT {index['category']} {len(inventory)} selected", flush=True)
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROCESSED_ROOT / "omniobject3d/ood-v1")
    parser.add_argument("--stage", choices=("assets", "pilot", "eval100"), required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    root = args.dataset.resolve()
    if not root.is_relative_to(PROCESSED_ROOT.resolve()):
        parser.error("Dataset must be under the project processed-data directory")
    if args.stage == "assets":
        plan = read_json(root / "download_plan.json")
        complete = read_json(root / "download_complete.json")
        if complete["plan_sha256"] != file_digest(root / "download_plan.json"):
            raise ValueError("Verified download plan changed")
        excluded_paths = {entry["path"] for entry in complete.get("acquisition_exclusions", [])}
        archives = [entry for entry in plan["archives"] if entry["path"] not in excluded_paths]
        if len(archives) != complete["verified_archives"]:
            raise ValueError("Verified archive count changed")
        with ThreadPoolExecutor(args.workers) as pool:
            indexes = list(pool.map(lambda entry: inspect_archive(root, entry), archives))
        selection = freeze_selection(root, indexes)
        with ThreadPoolExecutor(args.workers) as pool:
            groups = list(pool.map(lambda index: extract_selected(root, index, selection["samples"]), indexes))
        inventory = [asset for group in groups for asset in group]
        payload = "".join(json.dumps(asset, sort_keys=True) + "\n"
                          for asset in sorted(inventory, key=lambda row: row["asset_id"]))
        inventory_path = root / "inventory.jsonl"
        if inventory_path.exists() and inventory_path.read_text() != payload:
            raise ValueError("Frozen source inventory changed")
        inventory_path.write_text(payload)
        atomic_json(root / "assets_complete.json", {
            "selection_sha256": file_digest(root / "selection.json"),
            "inventory_sha256": file_digest(inventory_path), "asset_count": len(inventory),
        })
    else:
        complete = read_json(root / "assets_complete.json")
        if complete["inventory_sha256"] != file_digest(root / "inventory.jsonl"):
            raise ValueError("Source inventory changed")
        print(prepare(root, args.stage, "y", dataset_name="omniobject3d-ood-v1",
                      render_protocol="omniobject3d-render-v1"))


if __name__ == "__main__":
    main()
