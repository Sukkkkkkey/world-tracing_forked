"""Compare actual rerun metrics with the archived historical workbook, without forcing agreement."""
import argparse
from collections import Counter,defaultdict
import math
from pathlib import Path
import statistics
import hashlib,json
from wt.experiment import read_json,atomic_json,file_digest
from wt.paths import OUTPUT_ROOT

HISTORICAL=OUTPUT_ROOT/"recovery/20261105T044019Z/historical-workbook-metrics.json"


def compare(require_complete=False):
    source=read_json(HISTORICAL)
    groups=defaultdict(list)
    rows=[]
    pending=[]
    covered=0
    config_hashes={}
    for original in source["records"]:
        exp,sample,method,config,seed,parameter_hash=original["identity"]
        directory=OUTPUT_ROOT/"experiments"/exp/"samples"/sample/method/config/f"seed-{seed:04d}"
        path=directory/"metrics.json"
        if not path.is_file() or read_json(path).get("evaluation_status")!="complete":
            pending.append(original["identity"])
            continue
        actual=read_json(directory/"config.json")["parameters"]
        actual_hash=hashlib.sha256(json.dumps(actual,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
        assert actual_hash==parameter_hash, "Historical parameter identity changed"
        config_hashes[str(directory/"config.json")]=file_digest(directory/"config.json")
        metrics=read_json(path)
        metric_sha256=file_digest(path)
        lookup={(r["protocol_id"],r["metric"]):r for r in metrics["metrics"]}
        for old in original["metrics"]:
            key=(old["protocol_id"],old["metric"])
            new=lookup[key]
            values=dict(identity=original["identity"],protocol_id=key[0],metric=key[1],
                old_status=old["status"],new_status=new["status"],old=old["value"],new=new["value"],
                new_reason=new.get("reason"),metric_file=str(path),metric_sha256=metric_sha256)
            if old["status"]=="complete" and new["status"]=="complete":
                values["delta"]=new["value"]-old["value"]
                values["numerically_close"]=math.isclose(old["value"],new["value"],abs_tol=1e-9,rel_tol=1e-6)
            groups[(exp,method,config,*key)].append(values)
            rows.append(values)
        covered+=1
    summaries=[]
    for key,values in sorted(groups.items()):
        paired=[r for r in values if "delta" in r]
        old=[r["old"] for r in values if r["old_status"]=="complete"]
        new=[r["new"] for r in values if r["new_status"]=="complete"]
        summaries.append(dict(zip(("experiment","method","config","protocol_id","metric"),key),
            observed_runs=len(values),old_valid=len(old),new_valid=len(new),
            old_mean=statistics.fmean(old) if old else None,new_mean=statistics.fmean(new) if new else None,
            paired=len(paired),mean_paired_delta=statistics.fmean(r["delta"] for r in paired) if paired else None,
            max_abs_paired_delta=max((abs(r["delta"]) for r in paired),default=None),
            numerically_close=sum(r["numerically_close"] for r in paired),
            status_transitions=dict(Counter(r["old_status"]+" -> "+r["new_status"] for r in values))))
    assert len(source["records"])==450
    if require_complete:
        assert not pending, f"{len(pending)} quantitative runs are still pending"
    result=dict(status="complete" if not pending else "partial",expected_runs=450,compared_runs=covered,
        pending=pending,groups=summaries,rows=rows,config_sha256=config_hashes,
        historical_source_sha256=file_digest(HISTORICAL),historical_workbook_sha256=source["source_workbook_sha256"],
        script_sha256=file_digest(Path(__file__)),
        interpretation="This measures new-versus-historical differences. It is not an acceptance threshold and never selects seeds or alters scores.",
        limitations="Old per-run predictions and frozen input hashes were not migrated. Parameter/sample identities can be verified, but individual numerical differences cannot be uniquely attributed from workbook values alone.")
    destination=OUTPUT_ROOT/"validation/recovery-20261105"/("historical-comparison.json" if not pending else "historical-comparison.partial.json")
    atomic_json(destination,result)
    print("Compared",covered,"of 450 historical quantitative runs")
    for g in summaries:
        if g["protocol_id"]=="gso-shape-sim3-v1" and g["metric"]=="cd_euclidean_mean":
            print(g["experiment"],g["method"],g["config"],"old/new means",g["old_mean"],g["new_mean"])
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete",action="store_true")
    compare(parser.parse_args().require_complete)
