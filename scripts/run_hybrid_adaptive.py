"""Resume a frozen Hybrid pilot; reduce the sampling batch on CUDA OOM."""
import argparse
from collections import defaultdict
import fcntl
import gc
from pathlib import Path
import time
import traceback

from scripts import run_hybrid_ablation as original
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.hybrid_ablation import assert_camera_idle, validate_backend_provenance, validate_plan, validate_sources

SIZES = (64, 32, 16, 12, 10, 8, 6, 4)


def cuda_oom(exc):
    import torch
    msg = str(exc).lower()
    return (isinstance(exc, torch.cuda.OutOfMemoryError)
            or ("out of memory" in msg and ("cuda" in msg or "gpu" in msg))
            or "cuda_error_out_of_memory" in msg)


def schedule_for(group, requested):
    return dict(requested_size=requested, actual_size=len(group),
                members=[j["source_key"] for j in group])


def identity(job, schedule, provenance, executor, plan):
    return digest(dict(parameters=job["parameters"], strategy=job["strategy"],
                       source_pins=job["pins"], transform=job["canonical_transform"],
                       provenance=provenance, executor_sha256=executor,
                       batch=schedule, plan_hash=plan["plan_hash"]))


def bucket(job):
    # Images and WT supports are prepared per view. Only compatible model calls share a batch.
    return job["strategy"], job["preprocessing"], job["config_id"], digest(job["parameters"])


def dispatch(jobs, queue, attempt, recover):
    # Keep the original order within each experimental condition; run a full batch first.
    groups = defaultdict(list)
    for job in jobs:
        groups[bucket(job)].append(job)
    deferred = set(queue["deferred"])
    failures = []
    for members in sorted(groups.values(), key=len, reverse=True):
        pending = [j for j in members if j["destination"] not in deferred]
        while pending:
            requested = queue["ceiling"]
            group = pending[:requested]
            done, oom = attempt(group, requested, False)
            if oom:
                recover()
                smaller = [s for s in SIZES if s < len(group)]
                if smaller:
                    queue["ceiling"] = max(smaller)
                else:
                    deferred.update(j["destination"] for j in group if j["destination"] not in done)
                    queue["deferred"] = sorted(deferred)
                    queue["ceiling"] = SIZES[-1]
            pending = [j for j in pending if j["destination"] not in done | deferred]
    for job in jobs:
        if job["destination"] in deferred:
            _, oom = attempt([job], 1, True)
            if oom:
                recover()
                failures.append(job["destination"])
    return failures


def run(plan, policy, control):
    from wt.hybrid_ablation_backend import HybridAblationBackend
    from wt.paths import WEIGHTS_ROOT
    root = validate_plan(plan)
    if (policy["plan_hash"] != plan["plan_hash"] or read_json(root / "plan.json") != plan
            or tuple(policy["sizes"]) != SIZES):
        raise ValueError("Frozen pilot or batch policy changed")
    if file_digest(Path(original.__file__)) != policy["legacy_executor_sha256"]:
        raise ValueError("Original batch executor changed")
    validate_sources(plan)
    assert_camera_idle()
    with (root / ".hybrid.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backend = HybridAblationBackend(None, WEIGHTS_ROOT / "local-pipelines/TRELLIS.2")
        for src in plan["sources"].values():
            validate_backend_provenance(src, backend.provenance)
        return run_locked(plan, policy, control, backend)


def run_locked(plan, policy, control, backend):
    journal = control / "adaptive-attempts"
    journal.mkdir(exist_ok=True)
    executor = digest([policy["legacy_executor_sha256"], file_digest(Path(__file__))])
    legacy = policy["completed_at_pause"]
    owners = {}
    jobs = []
    for group in original.mesh_batches(plan, 4):
        old_schedule = schedule_for(group, 4)
        for job in group:
            path = job["destination"]
            if path in legacy:
                key = identity(job, old_schedule, backend.provenance, policy["legacy_executor_sha256"], plan)
                if legacy[path] != key or not original.completed_job(Path(path), key, job["input"]["sha256"]):
                    raise ValueError(f"Previously completed batch-4 output changed: {path}")
            else:
                jobs.append(job)
    by_path = {j["destination"]: j for j in jobs}
    if len(by_path) != policy["remaining"] or len(legacy) + len(jobs) != 480:
        raise ValueError("Resume inventory changed")
    queue = dict(ceiling=SIZES[0], deferred=[])
    # Replay completed attempts to retain the last batch ceiling across restarts.
    events = sorted(journal.glob("attempt-*.json"))
    for path in events:
        event = read_json(path)
        if event["executor"] != executor or event["plan_hash"] != plan["plan_hash"]:
            raise ValueError("Adaptive journal identity changed")
        group = [by_path[p] for p in event["destinations"]]
        if len({bucket(j) for j in group}) != 1 or event["schedule"] != schedule_for(group, event["schedule"]["requested_size"]):
            raise ValueError("Invalid batch membership")
        for j in group:
            owners[j["destination"]] = (event["number"], event["schedule"])
        if event["status"] == "oom" and not event["single_retry"]:
            smaller = [s for s in SIZES if s < len(group)]
            queue["ceiling"] = max(smaller) if smaller else SIZES[-1]
            if not smaller:
                queue["deferred"].extend(p for p in event["destinations"] if p not in event["completed"])
    number = len(events)
    def preserve_partial(job, seq, schedule):
        directory = Path(job["destination"])
        runfile = directory / "run.json"
        key = identity(job, schedule, backend.provenance, executor, plan)
        if runfile.is_file():
            st = read_json(runfile)
            if st["config_hash"] != key or st["input_sha256"] != job["input"]["sha256"] or st["status"] == "complete":
                raise ValueError(f"Unexpected partial run: {directory}")
        # Each journal entry was written after checking that its destinations were empty.
        if directory.exists() and any(directory.iterdir()):
            archived = directory.with_name(f".{directory.name}-adaptive-attempt-{seq:05d}")
            if archived.exists(): raise FileExistsError(archived)
            directory.rename(archived)
    pending = []
    for job in jobs:
        p = job["destination"]
        d = Path(p)
        if p in owners:
            seq, sched = owners[p]
            key = identity(job, sched, backend.provenance, executor, plan)
            if (d/"run.json").is_file() and read_json(d/"run.json")["status"] == "complete":
                original.completed_job(d,key,job["input"]["sha256"])
                continue
            preserve_partial(job,seq,sched)
        elif d.exists() and any(d.iterdir()):
            raise ValueError(f"Destination has no matching adaptive attempt: {d}")
        pending.append(job)

    def attempt(group, requested, single):
        nonlocal number
        assert_camera_idle()
        validate_sources({"sources": {j["source_key"]: j for j in group}})
        sched = schedule_for(group, requested)
        number += 1
        path = journal / f"attempt-{number:05d}.json"
        event = dict(number=number, executor=executor, plan_hash=plan["plan_hash"], schedule=sched,
                     destinations=[j["destination"] for j in group], single_retry=single, status="running", completed=[])
        for j in group:
            dest = Path(j["destination"])
            if dest.exists() and any(dest.iterdir()):
                raise ValueError(f"Refusing to overwrite {dest}")
        atomic_json(path,event)
        done = set()
        started = time.monotonic()
        try:
            # Even isolated retries use the same batched sampler, seed policy and metrics.
            with backend.prepare_batch(group):
                sampling = time.monotonic()-started
                for j in group:
                    assert_camera_idle()
                    key = identity(j,sched,backend.provenance,executor,plan)
                    original.finish_mesh(plan,backend,j,Path(j["destination"]),key,sched,sampling)
                    done.add(j["destination"])
            event["status"] = "complete"
        except Exception as exc:
            event.update(status="oom" if cuda_oom(exc) else "error", error=str(exc)[-2500:])
            if event["status"] != "oom": raise
        finally:
            event["completed"] = sorted(done)
            atomic_json(path,event)
        if event["status"] == "oom":
            for j in group:
                if j["destination"] not in done:
                    preserve_partial(j,number,sched)
        return done, event["status"] == "oom"

    def recover():
        gc.collect()
        backend.recover()
    if pending:
        try:
            backend.load_trellis(include_stage1=False, modes={"1024_cascade"})
            failures = dispatch(pending, queue, attempt, recover)
        finally:
            backend.unload_trellis()
    else:
        failures = []
    atomic_json(control / "adaptive-result.json", dict(plan_hash=plan["plan_hash"], requested=SIZES[0],
                retained_batch4=len(legacy), remaining_at_pause=len(jobs), failed_singletons=failures))
    return int(bool(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--execute-gpu", action="store_true", required=True)
    args = parser.parse_args()
    return run(read_json(args.plan), read_json(args.policy), args.policy.parent)


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 2
    raise SystemExit(code)
