"""Validate the complete paired cohort, calculate contrasts and update the formal report."""
from datetime import datetime
import os
from pathlib import Path
import uuid

import numpy as np

from scripts.prepare_stage1_oracle import BASE, CONTROL, OUTPUT, REPO
from wt.experiment import atomic_json, file_digest, read_json

KEYS=("CD","visible_CD","P","R","F","IoU","area_ratio")
NAMES={"A":"Oracle A · WT 变换","B":"Oracle B · GT 归一化","TRELLIS.2/B1.5":"TRELLIS.2 B1.5"}
MAIN=("TRELLIS.2/B1.5","B")


def metrics(result):
    s=result["shape"]
    vals=[s["cd_euclidean_mean"],result["regions"]["visible"]["metrics"]["cd_euclidean_mean"],
          s["precision@0.01"],s["recall@0.01"],s["f@0.01"]]
    if result["stage"]=="glb":
        vals.extend([result["comparisons"]["native"]["input"]["metrics"]["silhouette_iou"],result["geometry"]["area_gt_ratio"]])
    return dict(zip(KEYS,vals))


def load(row,ds,sid,j):
    path=Path(row["result_path"])
    assert file_digest(path)==row["result_sha256"]
    x=read_json(path)
    assert (x["sample_id"],x["revision"],x["seed"],x["status"],x["numerical_status"])==(sid,j["revision"],42,"complete","complete")
    assert str(x["protocol_version"])=="0.5"
    visible=x["regions"]["visible"]
    assert visible["status"]=="complete" or (visible["status"]=="empty_prediction" and visible["prediction_points"]==0 and visible["metrics"]["cd_euclidean_mean"] is None)
    hashes={Path(k).name:v for k,v in x["inputs"].items()}
    assert hashes["input.png"]==j["input"]["sha256"] and hashes["gt_points.npz"]==j["input"]["artifact_sha256"]["gt_points.npz"]
    return x


def tab(headers,rows):
    def line(row):return "| "+" | ".join(map(str,row))+" |"
    return "\n".join([line(headers),line(["---"]*len(headers)),*(line(r) for r in rows)])


def report():
    plan=read_json(CONTROL/"plan.json")
    assert file_digest(BASE/"metrics-index.json")==plan["baseline_index_sha256"]
    jobs={(j["dataset"],j["input"]["sample_id"],j["mode"]):j for j in plan["jobs"]}
    assert len(jobs)==400
    values={}
    native_pairs={}
    rows=[]
    for i in read_json(BASE/"metrics-index.json"):
        ds,sid,role=i["dataset"],i["sid"],i["role"]
        x=load(i["row"],ds,sid,jobs[ds,sid,"A"])
        assert x["stage"]==("points" if role.startswith("WT/") else "glb")
        values[ds,sid,role]=metrics(x)
        if role==MAIN[0]:
            native_pairs[ds,sid]=(x["reference"],x["sampling_seeds"])
    assert len(values)==2000 and len(native_pairs)==200
    scope=read_json(CONTROL/"B-primary.json")
    assert scope["plan_hash"]==plan["hash"] and scope["primary"]=="B"
    retained=set(scope["reference_A"])
    for (ds,sid,role),j in jobs.items():
        if role=="A" and j["dest"] not in retained:continue
        dest=Path(j["dest"])
        assert file_digest(Path(j["support"]))==j["support_sha256"]==read_json(dest/"oracle.json")["support_sha256"]
        row=read_json(CONTROL/"metrics"/ds/sid/(role+".json"))
        assert (row["dataset"],row["sid"],row["mode"],row["plan_hash"])==(ds,sid,role,plan["hash"])
        x=load(row,ds,sid,j)
        assert x["method"]=="trellis2" and x["config_id"]==j["parameters"]["config_id"] and x["stage"]=="glb" and x["source_directory"]==str(dest)
        assert (x["reference"],x["sampling_seeds"])==native_pairs[ds,sid]
        assert x["inputs"][str(dest/"mesh.glb")]==file_digest(dest/"mesh.glb")
        values[ds,sid,role]=metrics(x)
        rows.append(row)
    assert len(rows)==200+len(retained)
    atomic_json(OUTPUT/"metrics-index.json",rows)
    title="## TRELLIS.2 第一阶段稀疏结构 Oracle"
    lines=[title,"GSO、OOD 各 100 个正式资产，主实验为 Oracle B 的 200 份 exported GLB 与原生 B1.5 的逐资产对照。Oracle A 仅保留切换时已完成的输出作为参考。固定 B1 图像、B1.5 原生紧裁剪、seed 42、1024 cascade 和 v0.5 评测。A 将 GT 表面放入灰背景 WT 的冻结坐标变换；B 以 GT 表面积加权中心居中、最大轴向半径缩放到 0.45。两组均只给下游模型传入 32³ 网格的表面相交体素。"]
    summary={}
    rng=np.random.default_rng(42)
    for ds in ("GSO","OOD"):
        ids=sorted(sid for d,sid,m in jobs if d==ds and m=="B")
        assert len(ids)==100
        roles=sorted({r for d,_,r in values if d==ds and r!="A"})
        cols={r:{k:np.array([values[ds,s,r][k] for s in ids],dtype=float) for k in values[ds,ids[0],r]} for r in roles}
        assert all(np.isfinite(v).all() for c in cols.values() for k,v in c.items() if k!="visible_CD")
        visible_ok=np.logical_and.reduce([np.isfinite(cols[r]["visible_CD"]) for r in MAIN])
        visible_missing={r:[s for s,v in zip(ids,cols[r]["visible_CD"]) if not np.isfinite(v)] for r in MAIN}
        for r in MAIN:
            cols[r]["visible_CD"]=cols[r]["visible_CD"][visible_ok]
        means={r:{k:float(v.mean()) if v.size else None for k,v in c.items()} for r,c in cols.items()}
        lines.append("### "+ds+" · 100 个资产")
        def table(rr):
            return tab(["输出","完整 CD ↓","可见 CD ↓","P@.01 ↑","R@.01 ↑","F@.01 ↑","输入轮廓 IoU ↑","面积 / GT"],
                [[NAMES.get(r,r)]+[f"{means[r][k]:.6f}" if means[r].get(k) is not None else "—" for k in KEYS] for r in rr])
        lines.append(table(MAIN))
        lines.append(f"完整形状指标覆盖 100/100。主表可见 CD 和相关差值取两组均有可见预测点的共同 {visible_ok.sum()}/100 个资产。v0.5 对空可见预测返回未定义的 CD，逐组缺项见统计 JSON。")
        pairs={}
        boot=rng.integers(0,100,(10000,100))
        pr=[]
        for l,r in [("B",MAIN[0])]:
            pair=pairs[l+" − "+r]={}
            for k in KEYS:
                d=cols[l][k]-cols[r][k]
                gain=(abs(cols[r][k]-1)-abs(cols[l][k]-1)) if k=="area_ratio" else (-d if k.endswith("CD") else d)
                if not d.size:
                    pair[k]=dict(mean=None,ci=None,n=0,wins=0,ties=0,losses=0)
                    pr.append([l+" − "+r,k,"—","—","0/0/0"])
                    continue
                sample_indices=boot if len(d)==len(ids) else rng.integers(0,len(d),(10000,len(d)))
                lo,hi=np.quantile(d[sample_indices].mean(axis=1),[.025,.975])
                w,t,n=[int(a.sum()) for a in (gain>0,gain==0,gain<0)]
                pair[k]=dict(n=len(d),mean=float(d.mean()),ci=[float(lo),float(hi)],wins=w,ties=t,losses=n)
                pr.append([l+" − "+r,k,f"{d.mean():+.6f}",f"[{lo:+.6f}, {hi:+.6f}]",f"{w}/{t}/{n}"])
        lines.append("同资产差值取前者减后者；95% 区间按资产配对重采样 10,000 次，未作多重比较校正。面积比差值为原始比值之差，胜负按距 1 的绝对误差计算。")
        lines.append(tab(["对照","指标","均值差","95% 区间","胜 / 平 / 负"],pr))
        for role in ["B"]:
            p=pairs[role+" − "+MAIN[0]]["CD"]
            inference="区间支持 CD 降低" if p["ci"][1]<0 else ("区间支持 CD 升高" if p["ci"][0]>0 else "区间包含零，平均提升方向尚不确定")
            lines.append(f"Oracle {role} 相对 B1.5 的完整 CD 差值为 {p['mean']:+.6f}，{p['wins']}/100 个资产更低；{inference}。")
        clipped={m:[jobs[ds,s,m]["outside_area_fraction"] for s in ids] for m in ("A","B")}
        lines.append(f"A 有 {sum(v>1e-7 for v in clipped['A'])}/100 个资产的 GT 表面越界，平均越界面积占比为 {np.mean(clipped['A']):.2%}。B − A 同时包含平移、尺度及相应裁切变化。")
        subset=[s for s in ids if (ds,s,"A") in values]
        reference={}
        if subset:
            lines.append(f"**Oracle A 参考 · 已导出 {len(subset)} 个资产。** 该子集由停止时的运行顺序决定。下表在相同资产上比较 A、B 与 B1.5，独立于主表。")
            refrows=[]
            for k in KEYS:
                triples=np.array([[values[ds,s,r][k] for r in ("A","B",MAIN[0])] for s in subset],dtype=float)
                triples=triples[np.isfinite(triples).all(axis=1)]
                if not len(triples):
                    refrows.append([k,0]+["—"]*5)
                    reference[k]=dict(n=0)
                    continue
                a,b,base=triples.mean(axis=0)
                reference[k]=dict(n=len(triples),A=a,B=b,B15=base,B_minus_A=b-a,A_minus_B15=a-base)
                refrows.append([k,len(triples),f"{a:.6f}",f"{b:.6f}",f"{base:.6f}",f"{b-a:+.6f}",f"{a-base:+.6f}"])
            lines.append(tab(["指标","有效配对","A","B","B1.5","B − A","A − B1.5"],refrows))
        else:
            lines.append("此数据集在停止 A 组时尚无已导出的 A 网格。")
        lines.append("**同批资产的已有 WT、Hybrid、TRELLIS.2 对照**")
        lines.append(table([r for r in roles if r not in MAIN]))
        summary[ds]=dict(n=100,reference_A=dict(ids=subset,metrics=reference),visible_paired_n=int(visible_ok.sum()),visible_missing=visible_missing,means=means,pairs=pairs)
    lines.append(f"CD 均为配准后双向欧氏 CD-L1 原值。WT 以点云参评；各网格均使用 exported GLB。结果反映当前 32³ 表面表示与单一 seed 下的经验上限。逐资产指标索引与统计见 `{OUTPUT}/metrics-index.json`、`summary.json`，冻结计划与回灌核验见 `{CONTROL}/plan.json`、`smoke.json`。")
    section="\n\n".join(lines)+"\n"
    atomic_json(OUTPUT/"summary.json",summary)
    doc=REPO/"docs/20261118_hybrid_ablation.md"
    raw=doc.read_text()
    if title in raw:
        assert section in raw
        return
    head,body=raw.split("\n\n",1)
    tmp=doc.with_suffix("."+uuid.uuid4().hex+".tmp")
    tmp.write_text(head+"\n\n"+section+"\n"+body)
    assert doc.read_text()==raw
    os.replace(tmp,doc)


if __name__=="__main__":
    report()
