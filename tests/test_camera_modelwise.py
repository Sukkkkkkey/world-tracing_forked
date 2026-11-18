"""Scheduling regressions: cross-condition model reuse and exact Hybrid parents."""
from pathlib import Path
import shutil
import sys
import pytest
from PIL import Image
from scripts import run_camera_ablation_modelwise as queue
from wt.batch import resolve_configs
from wt.experiment import read_json, run_directory

class FakeBackend:
    provenance = {"fixture": "modelwise-v1"}
    def __init__(self, events):
        self.events = events
        self.model = self.pipeline = None
    def load_wt(self):
        self.model = object()
        self.events.append(("load_wt",))
    def unload_wt(self):
        self.model = None
    def load_trellis(self, include_stage1, modes):
        self.pipeline = object()
        self.events.append(("load_trellis", include_stage1))
    def unload_trellis(self):
        self.pipeline = None
    def recover(self):
        pass
    def predict_wt(self, image, cfg, seed, directory):
        assert self.model is not None
        self.events.append(("predict_wt", image.name, tuple(cfg["bg_color"]), cfg["alpha_erode"]))
        (directory/"prediction.npz").write_bytes(str((image.name,cfg["bg_color"],cfg["alpha_erode"],seed)).encode())
        shutil.copyfile(image, directory/"rgba.png")
    def generate_mesh(self, image, cfg, seed, directory, parent):
        assert self.pipeline is not None
        assert (parent is None) == (cfg["method"] == "trellis2")
        self.events.append(("mesh",cfg["method"],cfg["config_id"],image.name))
        (directory/"decoded_mesh.ply").write_text("mesh")
        (directory/"mesh.glb").write_text("glb")
        return {"decoded_mesh":{"path":"decoded_mesh.ply","kind":"mesh"},
                "mesh":{"path":"mesh.glb","kind":"mesh"}}

def contexts(tmp_path):
    result=[]
    for label in ("GSO","OOD"):
        image=tmp_path/f"{label}.png"
        Image.new("RGBA",(8,8),(30,60,90,255)).save(image)
        sample={"sample_id":label,"image":str(image)}
        result.append(dict(dataset=label,condition="A0",source_inputs=[sample],
                           root=str(tmp_path/label),control_source=None))
    return result

def backend(events, phase):
    return queue.resident_backend(FakeBackend,phase)(events)

def test_manifest_prefix_is_stable_and_duplicates_rejected():
    rows=[{"sample_id":str(i)} for i in range(100)]
    assert queue.select_inputs(rows,50) == rows[:50]
    with pytest.raises(ValueError,match="Duplicate"):
        queue.select_inputs(rows+rows[:1],50)
    with pytest.raises(ValueError,match="Insufficient"):
        queue.select_inputs(rows[:2],50)

def test_all_wt_parents_precede_mesh_and_models_stay_loaded_across_datasets(tmp_path):
    plan={"contexts":contexts(tmp_path)}
    events=[]
    for phase in queue.PHASES:
        queue.inference(plan,phase,backend(events,phase))
    assert events.count(("load_wt",)) == 1
    assert events.count(("load_trellis",True)) == 1
    assert events.count(("load_trellis",False)) == 2
    predictions=[x for x in events if x[0]=="predict_wt"]
    assert len(predictions)==4
    assert {x[2:] for x in predictions} == {((128,128,128),0),((0,0,0),2)}
    first_mesh=next(i for i,x in enumerate(events) if x[0]=="mesh")
    assert all(x[0]!="predict_wt" for x in events[first_mesh:])
    assert [(x[1],x[2]) for x in events if x[0]=="mesh"] == [
        ("trellis2","defaults-v1")]*2 + [("wt_trellis2","defaults-v1")]*2 + [
        ("wt_trellis2","shared-wt-v1")]*2
    for context in plan["contexts"]:
        root=Path(context["root"]); sid=context["source_inputs"][0]["sample_id"]
        wt=run_directory(root,sid,"wt","defaults-v1",42)/"prediction.npz"
        shared=run_directory(root,sid,"wt_trellis2","shared-wt-v1",42)
        parent=read_json(shared/"wt_parent.json")
        assert wt.read_bytes() == (shared/parent["path"]).read_bytes()
        default=run_directory(root,sid,"wt_trellis2","defaults-v1",42)
        other=read_json(default/"wt_parent.json")
        assert wt.read_bytes() != (default/other["path"]).read_bytes()
    events.clear()
    for phase in queue.PHASES:
        queue.inference(plan,phase,backend(events,phase))
    assert events == []

def test_hybrid_never_silently_reloads_wt_when_parent_is_missing(tmp_path):
    plan={"contexts":contexts(tmp_path)}; events=[]
    with pytest.raises(ValueError,match="WT phase incomplete"):
        queue.inference(plan,"hybrid-default",backend(events,"hybrid-default"))
    assert events == []

def test_changed_completed_config_is_not_overwritten(tmp_path):
    plan={"contexts":contexts(tmp_path)}; events=[]
    queue.inference(plan,"wt",backend(events,"wt"))
    context=plan["contexts"][0]; sample=context["source_inputs"][0]
    cfg=resolve_configs([queue.CONFIGURATIONS[0]])[0]
    directory,_=queue.run_source(context,sample,cfg)
    before=(directory/"run.json").read_bytes()
    with pytest.raises(ValueError,match="configuration mismatch"):
        queue.complete_run(directory,sample,dict(cfg,wt_steps=99))
    assert (directory/"run.json").read_bytes()==before

def test_execution_requires_explicit_resume_flag(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,"argv",["queue","--config",str(tmp_path/"missing"),
        "--control",str(tmp_path/"control"),"--phase","wt"])
    with pytest.raises(SystemExit) as error:
        queue.main()
    assert error.value.code==2

def test_plan_contains_only_unique_conditions_and_preserves_first_fifty(tmp_path, monkeypatch):
    import wt.paths
    monkeypatch.setattr(wt.paths, "PROCESSED_ROOT", tmp_path/"data")
    monkeypatch.setattr(wt.paths, "OUTPUT_ROOT", tmp_path/"output")
    for label in ("GSO","OOD"):
        source=tmp_path/"data"/label
        source.mkdir(parents=True)
        rows=[{"sample_id":str(i),"image":"unused"} for i in range(100)]
        (source/"eval100.jsonl").write_text("".join(queue.json.dumps(r)+"\n" for r in rows))
    config=dict(seed=42,assets_per_dataset=50,conditions=["A0","A1","B1"],
                condition_aliases={"B0":"A0"},configurations=queue.CONFIGURATIONS,
                phase_order=list(queue.PHASES),run_id="test",data_subdirectory="camera",
                old_control=str(tmp_path/"old"),datasets={
                    x:dict(source=x,control_experiment="control-"+x) for x in ("GSO","OOD")})
    plan=queue.make_plan(config,tmp_path/"control")
    assert len(plan["contexts"])==6
    assert all(c["condition"]!="B0" for c in plan["contexts"])
    assert plan["unique_method_outputs"]==1200
    assert plan["unique_evaluation_stages"]==2100
    assert all(v["sample_ids"]==[str(i) for i in range(50)] for v in plan["source_manifests"].values())
