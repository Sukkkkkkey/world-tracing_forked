"""Run the B1.5 Stage 1 replay gate, then the frozen A and B queues."""
import gc
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from PIL import Image

from scripts.prepare_stage1_oracle import CONTROL, FORMAL, OUTPUT
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import WEIGHTS_ROOT
from wt.textured_mesh.batched_cascade import pack_supports

# Match the exact B1.5 conditioner, sampler, decoding and exporter used in the formal run.
sys.path.insert(0,str(FORMAL))
import native_b15_worker as native


def support(job):
    path=Path(job["support"])
    if file_digest(path)!=job["support_sha256"]:
        raise ValueError(f"Frozen support changed: {path}")
    return np.load(path,allow_pickle=False)


@torch.no_grad()
def oracle_latents(pipe,images,cfg,supports,expected=None):
    generators=[torch.Generator(device="cpu").manual_seed(42) for _ in images]
    lr=pipe.get_cond(images,512)
    hr=pipe.get_cond(images,1024)
    # The native generator consumes exactly this noise before the low-res shape flow.
    native.structure_noise(pipe.models["sparse_structure_flow_model"],generators)
    coords=pack_supports(supports,pipe.device)
    if expected is not None:
        assert torch.equal(coords.cpu(),expected["coords"])
        assert all(torch.equal(g.get_state(),s) for g,s in zip(generators,expected["states"],strict=True))
    low=native.flow(pipe,"shape_slat_flow_model_512",coords,[len(x) for x in supports],generators,lr,cfg)
    decoder=pipe.models["shape_slat_decoder"]
    with native.resident(pipe,decoder),native.bounded_layernorm(decoder),native.inference_parameters(decoder):
        previous=decoder.low_vram
        try:
            decoder.low_vram=pipe.low_vram
            up=decoder.upsample(low,upsample_times=4)
        finally:
            decoder.low_vram=previous
    high=torch.cat((up[:,:1],((up[:,1:]+.5)/512*64).int()),1).unique(dim=0).contiguous()
    del up,low
    lengths=torch.bincount(high[:,0].long(),minlength=len(images)).tolist()
    if len(lengths)!=len(images) or not all(lengths):raise ValueError("Lost batch member in upsampling")
    shape=native.flow(pipe,"shape_slat_flow_model_1024",high,lengths,generators,hr,cfg)
    tex=native.flow(pipe,"tex_slat_flow_model_1024",high,lengths,generators,hr,cfg,shape)
    return shape,tex,[g.get_state() for g in generators]


class OracleBackend(native.Backend):
    def process(self,group):
        self.jobs={j["input"]["image"]:j for j in group}
        supports=[support(j) for j in group]
        with patch.object(native,"latents",lambda p,images,cfg:oracle_latents(p,images,cfg,supports)):
            return super().process(group)

    def generate_mesh(self,image,cfg,seed,directory,parent):
        artifacts=super().generate_mesh(image,cfg,seed,directory,parent)
        j=self.jobs[str(image)]
        keys=["mode","count","support_sha256","gt_sha256","outside_area_fraction","transform","wt_transform_source"]
        atomic_json(directory/"oracle.json",{key:j[key] for key in keys})
        return artifacts


def smoke(plan,pins):
    backend=native.Backend(None,WEIGHTS_ROOT/"local-pipelines/TRELLIS.2")
    backend.load_trellis(True,{"1024_cascade"})
    pipe=backend.pipeline
    results=[]
    for ds in ("GSO","OOD"):
        # Deterministically take a formal member whose input belongs to the native B1.5 batch runner.
        j=next(j for j in plan["jobs"] if j["dataset"]==ds and j["mode"]=="A" and str(OUTPUT.parent/"20261121-hybrid-formal-b1-bs48") in j["native_dir"])
        with Image.open(j["input"]["image"]) as im: image=pipe.preprocess_image(im.copy())
        expected={}
        real=native.flow
        def record(p,name,coords,lengths,gs,*args,**kwargs):
            if name=="shape_slat_flow_model_512":
                expected.update(coords=coords.cpu().clone(),states=[g.get_state().clone() for g in gs])
            return real(p,name,coords,lengths,gs,*args,**kwargs)
        with patch.object(native,"flow",record):
            a,b,states=native.latents(pipe,[image],j["parameters"])
        reference=[(s.coords.cpu(),s.feats.float().cpu()) for s in (a,b)]
        del a,b
        xyz=expected["coords"][:,1:].numpy()
        a,b,again=oracle_latents(pipe,[image],j["parameters"],[xyz],expected)
        max_errors=[]
        for (coords,feats),s in zip(reference,(a,b),strict=True):
            assert torch.equal(coords,s.coords.cpu())
            got=s.feats.float().cpu()
            max_errors.append(float((feats-got).abs().max()))
            torch.testing.assert_close(feats,got,rtol=1e-4,atol=1e-5)
        assert torch.equal(states[0],again[0])
        results.append(dict(dataset=ds,sid=j["input"]["sample_id"],voxels=len(xyz),
                            shape_texture_max_abs=max_errors,rng_before_and_after_equal=True))
        del a,b,reference
        gc.collect();torch.cuda.empty_cache()
    atomic_json(CONTROL/"smoke.json",dict(pins=pins,results=results))


def main(mode):
    plan=read_json(CONTROL/"plan.json")
    pins=dict(plan=plan["hash"],worker=file_digest(Path(__file__)),native=file_digest(Path(native.__file__)),
              cascade=file_digest(FORMAL/"b15_cascade.py"))
    if mode=="smoke":
        return smoke(plan,pins)
    assert mode in ("A","B") and read_json(CONTROL/"smoke.json")["pins"]==pins
    jobs=[j for j in plan["jobs"] if j["mode"]==mode]
    assert len(jobs)==200 and all(j["count"] for j in jobs)
    directory=CONTROL/mode
    directory.mkdir(exist_ok=True)
    orig_complete=native.complete
    def complete(j):
        if not orig_complete(j):return False
        info=read_json(Path(j["dest"])/"oracle.json")
        assert info["support_sha256"]==j["support_sha256"] and info["mode"]==mode
        return True
    with patch.object(native,"Backend",OracleBackend),patch.object(native,"complete",complete):
        from wt.experiment import digest
        native.run(dict(jobs=jobs,worker_sha256=digest(pins),cascade_sha256=pins["cascade"]),directory)


if __name__=="__main__":
    main(sys.argv[1])
