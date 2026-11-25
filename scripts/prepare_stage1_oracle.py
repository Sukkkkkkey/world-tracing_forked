"""Freeze the two GT surface supports for the B1.5 oracle."""
import ctypes
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
import trimesh

from wt.experiment import atomic_json, digest, file_digest, read_json, run_directory
from wt.textured_mesh.canon import CanonicalTransform

REPO = Path(__file__).resolve().parents[1]
FORMAL = REPO / ".runtime/logs/hybrid-formal-b1-20261121-bs48"
CONTROL = REPO / ".runtime/logs/trellis-stage1-oracle-20261124"
NATIVE = read_json(FORMAL / "plan.json")
BASE = Path(NATIVE["output"])
OUTPUT = BASE.parent / "20261124-trellis-stage1-oracle"
CPP = REPO / "wt/textured_mesh/oracle_surface.cpp"


def load_raster():
    CONTROL.mkdir(parents=True, exist_ok=True)
    lib = CONTROL / ("surface-" + file_digest(CPP)[:16] + ".so")
    if not lib.exists():
        tmp = lib.with_suffix(f".{os.getpid()}.so")
        subprocess.run(["c++", "-std=c++17", "-O3", "-shared", "-fPIC", str(CPP), "-o", str(tmp)], check=True)
        os.replace(tmp, lib)
    func = ctypes.CDLL(str(lib)).raster
    func.argtypes = [np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"), ctypes.c_int64,
                     np.ctypeslib.ndpointer(np.uint8, flags="C_CONTIGUOUS"),
                     np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS")]
    func.restype = None
    return func


def normalize_gt(vertices, faces, axis):
    mapped = CanonicalTransform([0,0,0], 1, axis).apply(vertices)
    total = 0.
    moment = np.zeros(3)
    for group in np.array_split(faces, max(1, (len(faces)+65535)//65536)):
        tri = mapped[group]
        weights = np.linalg.norm(np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0]), axis=1)
        moment += (weights[:,None] * tri.mean(axis=1)).sum(axis=0)
        total += weights.sum()
    if not total > 0:
        raise ValueError("GT has zero surface area")
    centroid = moment / total
    return CanonicalTransform(centroid, .45 / np.abs(mapped-centroid).max(), axis)


def voxelize(raster, vertices, faces, transform):
    mask = np.zeros((32,32,32), np.uint8)
    areas = np.zeros(2)
    mapped = transform.apply(vertices)
    for start in range(0,len(faces),65536):
        tri = np.ascontiguousarray(mapped[faces[start:start+65536]], dtype=np.float64)
        raster(tri,len(tri),mask,areas)
    if areas[0] <= 0 or areas[1] > areas[0]*(1+1e-8):
        raise ValueError(f"Invalid triangle areas {areas}")
    coords = np.ascontiguousarray(np.argwhere(mask), dtype=np.int32)
    return coords, max(0., 1-areas[1]/areas[0])


def prepare(item, raster):
    ds,sid,native,hybrid,ev = item
    nd,hd = (Path(x["directory"]) for x in (native,hybrid))
    sample = read_json(nd.parents[2]/"input.json")
    gt = Path(sample["ground_truth"]["path"])
    assert gt.name=="gt_camera.ply" and sample["ground_truth"]["frame"]=="camera_rdf"
    assert sample["sha256"]==sample["artifact_sha256"]["input.png"]==file_digest(Path(sample["image"]))
    gt_hash = file_digest(gt)
    assert gt_hash==sample["artifact_sha256"][gt.name]
    mesh = trimesh.load(gt, process=False)
    vertices,faces=mesh.vertices.view(np.ndarray),mesh.faces.view(np.ndarray)
    assert len(faces) and np.isfinite(vertices).all()
    tf = CanonicalTransform(**read_json(hd/"mesh.json")["canonical_transform"])
    configs = read_json(nd/"config.json")["parameters"]
    assert configs["pipeline_type"]=="1024_cascade" and configs["method"]=="trellis2"
    jobs=[]
    for mode,transform in [("A",tf),("B",normalize_gt(vertices,faces,tf.axis_map))]:
        coords,clipped=voxelize(raster,vertices,faces,transform)
        archive=CONTROL/"supports"/ds/sid/(mode+".npy")
        archive.parent.mkdir(parents=True,exist_ok=True)
        if archive.exists():
            assert np.array_equal(np.load(archive,allow_pickle=False),coords)
        else:
            with archive.with_suffix(".tmp").open("wb") as f: np.save(f,coords,allow_pickle=False)
            os.replace(archive.with_suffix(".tmp"),archive)
        if mode=="B": assert clipped<1e-7
        cfg=dict(configs,config_id="oracle-"+mode.lower())
        root=OUTPUT/ds
        jobs.append(dict(input=sample,dataset=ds,mode=mode,parameters=cfg,root=str(root),
            dest=str(run_directory(root,sid,"trellis2",cfg["config_id"],42)),support=str(archive),
            support_sha256=file_digest(archive),count=len(coords),outside_area_fraction=clipped,
            transform=transform.to_dict(),gt_sha256=gt_hash,native_result=native["row"],native_dir=str(nd),
            wt_transform_source=str(hd/"mesh.json"),eval_config=ev["config"],revision=ev["revision"]))
    return jobs


def main():
    raster=load_raster()
    ix=read_json(BASE/"metrics-index.json")
    lookup={(x["dataset"],x["sid"],x["role"]):x for x in ix}
    ev={(x["dataset"],x["sid"]):x for x in read_json(FORMAL/"eval-jobs.json") if x["role"]=="TRELLIS.2/B1.5"}
    items=[(ds,sid,lookup[ds,sid,"TRELLIS.2/B1.5"],lookup[ds,sid,"surface/shared-wt-v1"],ev[ds,sid])
        for ds,spec in NATIVE["datasets"].items() for sid in spec["ids"]]
    with ThreadPoolExecutor(4) as pool:
        jobs=[j for pair in pool.map(partial(prepare,raster=raster),items) for j in pair]
    assert len(jobs)==len({j["dest"] for j in jobs})==400
    plan=dict(jobs=jobs,seed=42,baseline_index_sha256=file_digest(BASE/"metrics-index.json"),
              raster_sha256=file_digest(CPP),prepare_sha256=file_digest(Path(__file__)))
    plan["hash"]=digest(plan)
    target=CONTROL/"plan.json"
    if target.exists(): assert read_json(target)==plan
    else: atomic_json(target,plan)
    empty=[(j["dataset"],j["input"]["sample_id"],j["mode"]) for j in jobs if not j["count"]]
    print("400 supports; empty:",empty,flush=True)
    if empty: raise ValueError("Empty GT support in frozen frame: "+str(empty))


if __name__=="__main__":
    main()
