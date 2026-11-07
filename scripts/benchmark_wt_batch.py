"""Benchmark real WT tensor batches while retaining one seed-42 RNG stream per image."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import time
import traceback

import numpy as np
import torch
from wt.artifacts import save_npz
from wt.batch import InferenceBackend
from wt.data import load_rgba_image, preprocess_rgba_for_model
from wt.experiment import atomic_json, file_digest, read_json, resolve_reference, run_directory
from wt.inference import inference_diffusion, _bypass_activation_checkpointing
from wt.paths import OUTPUT_ROOT, WEIGHTS_ROOT

REPO=Path(__file__).resolve().parents[1]


class IndependentNoise:
    """Benchmark-local adapter; fails closed if the model requests unsupported RNG."""
    def __init__(self,batch,seed):
        self.batch,self.seed=batch,seed
        self.calls=[]
    def __enter__(self):
        self.randn,self.like=torch.randn,torch.randn_like
        self.uniform,self.uniform_like=torch.rand,torch.rand_like
        self.saved=torch.cuda.get_rng_state()
        generator=torch.Generator(device='cuda').manual_seed(self.seed)
        self.states=[generator.get_state().clone() for _ in range(self.batch)]
        def randn(*shape,**kwargs):
            if len(shape)==1 and isinstance(shape[0],(tuple,list,torch.Size)):shape=tuple(shape[0])
            assert shape[0]==self.batch and torch.device(kwargs['device']).type=='cuda',('unsupported RNG',shape,kwargs)
            assert 'generator' not in kwargs
            return self.draw('randn',shape,lambda i:self.randn(1,*shape[1:],**kwargs))
        def like(value,**kwargs):
            assert value.shape[0]==self.batch and value.is_cuda,('unsupported RNG',value.shape)
            return self.draw('randn_like',tuple(value.shape),lambda i:self.like(value[i:i+1],**kwargs))
        def uniform(*shape,**kwargs):
            if len(shape)==1 and isinstance(shape[0],(tuple,list,torch.Size)):shape=tuple(shape[0])
            assert shape[0]==self.batch and torch.device(kwargs['device']).type=='cuda'
            assert 'generator' not in kwargs
            return self.draw('rand',shape,lambda i:self.uniform(1,*shape[1:],**kwargs))
        def uniform_like(value,**kwargs):
            assert value.shape[0]==self.batch and value.is_cuda
            return self.draw('rand_like',tuple(value.shape),lambda i:self.uniform_like(value[i:i+1],**kwargs))
        torch.randn,torch.randn_like=randn,like
        torch.rand,torch.rand_like=uniform,uniform_like
        return self
    def draw(self,kind,shape,fn):
        values=[]
        for i in range(self.batch):
            torch.cuda.set_rng_state(self.states[i])
            values.append(fn(i))
            self.states[i]=torch.cuda.get_rng_state()
        self.calls.append(dict(kind=kind,per_image_shape=[1,*shape[1:]]))
        return torch.cat(values,dim=0)
    def __exit__(self,*exc):
        torch.randn,torch.randn_like=self.randn,self.like
        torch.rand,torch.rand_like=self.uniform,self.uniform_like
        torch.cuda.set_rng_state(self.saved)


def compare(actual,expected,valid):
    diff=np.abs(actual[valid].astype(np.float64)-expected[valid].astype(np.float64))
    return dict(exact=bool(np.array_equal(actual,expected)),max_abs=float(diff.max()),
                mean_abs=float(diff.mean()),rmse=float(np.sqrt(np.mean(diff**2))),
                allclose_1e_5=bool(np.allclose(actual,expected,rtol=0,atol=1e-5)))


def main(args):
    plan=read_json(REPO/'configs/benchmark_single_gpu.json')
    p0=OUTPUT_ROOT/'experiments/20261013-P0-gso-pilot-v1'
    checkpoint=WEIGHTS_ROOT/'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
    backend=InferenceBackend(checkpoint,WEIGHTS_ROOT/'local-pipelines/TRELLIS.2')
    started=time.perf_counter();backend.load_wt();load_seconds=time.perf_counter()-started
    items=[]
    for style,method in [('gray','wt'),('black','wt_trellis2')]:
        for sample in plan['wt_samples']:
            original=run_directory(p0,sample,method,'defaults-v1',plan['seed'])
            cfg=read_json(original/'config.json')['parameters']
            image=Path(read_json(p0/'samples'/sample/'input.json')['image'])
            parent=original/'prediction.npz'
            if method!='wt':
                info=read_json(original/'wt_parent.json');parent=resolve_reference(original,info['path'])
            backend.reset_seed(plan['seed'])
            rgb,mask,K=preprocess_rgba_for_model(load_rgba_image(image,auto_alpha=True),
                image_size=504,num_layers=6,center_crop=True,alpha_erode_px=cfg['alpha_erode'],bg_color=tuple(cfg['bg_color']))
            items.append(dict(sample=sample,style=style,rgb=rgb,mask=mask,K=K,cfg=cfg,reference=parent))
    def predict(group,independent):
        rgb=torch.cat([v['rgb'] for v in group]).cuda()
        mask=torch.cat([v['mask'] for v in group]).cuda()
        K=torch.cat([v['K'] for v in group]).cuda()
        backend.reset_seed(plan['seed'])
        context=IndependentNoise(len(group),plan['seed']) if independent else nullcontext()
        with torch.no_grad(),torch.autocast('cuda',dtype=torch.bfloat16),_bypass_activation_checkpointing(backend.model),context as rng:
            xyz,valid,_=inference_diffusion(backend.model,rgb,gt_mask=mask,use_gt_mask=True,
                intrinsics=K,invalid_fill_mode='noise',**dict(backend.model_cfg['inference_kwargs'],num_steps=20))
        return xyz.float().cpu().numpy(),valid.cpu().numpy(),rng.calls if independent else None
    # Full b=1 execution proves the RNG adapter matches the existing serial stream.
    raw,raw_mask,_=predict(items[:1],False)
    adapted,adapted_mask,trace=predict(items[:1],True)
    assert np.array_equal(raw,adapted) and np.array_equal(raw_mask,adapted_mask),'RNG adapter changed batch=1'
    del raw,adapted,raw_mask,adapted_mask
    predict(items[:args.batch_size],args.batch_size>1)  # warm up actual batch shape
    atomic_json(args.control/'ready.json',dict(load_seconds=load_seconds,pid=__import__('os').getpid()))
    while not (args.control/'go').exists():time.sleep(.2)
    records=[];begin=time.perf_counter()
    for rep in range(plan['wt_repeats']):
        for offset in range(0,len(items),args.batch_size):
            group=items[offset:offset+args.batch_size]
            torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
            tick=time.perf_counter()
            xyz,mask,rng=predict(group,args.batch_size>1)
            torch.cuda.synchronize()
            elapsed=time.perf_counter()-tick
            for i,item in enumerate(group):
                directory=args.output/f'repeat-{rep}'/item['style']/item['sample']
                directory.mkdir(parents=True,exist_ok=True)
                save_npz(directory/'prediction.npz',xyz=xyz[i],mask=mask[i],
                    rgb=(item['rgb'][0].permute(1,2,0).numpy()*255).astype(np.uint8),intrinsics=item['K'][0].numpy())
                with np.load(item['reference'],allow_pickle=False) as old:
                    result=compare(xyz[i],old['xyz'],old['mask'])
                    result['mask_exact']=bool(np.array_equal(mask[i],old['mask']))
                    result['rgb_exact']=bool(np.array_equal((item['rgb'][0].permute(1,2,0).numpy()*255).astype(np.uint8),old['rgb']))
                    result['intrinsics_exact']=bool(np.array_equal(item['K'][0].numpy(),old['intrinsics']))
                records.append(dict(sample=item['sample'],style=item['style'],repeat=rep,comparison=result,
                    inference_seconds_per_image=elapsed/len(group),batch_seconds=elapsed,
                    reference=str(item['reference']),reference_sha256=file_digest(item['reference']),
                    peak_allocated=torch.cuda.max_memory_allocated(),peak_reserved=torch.cuda.max_memory_reserved(),
                    noise_calls=rng))
            print('WT-BATCH',args.batch_size,rep,offset+len(group),'/',len(items),flush=True)
    finish=time.perf_counter()
    atomic_json(args.output/'result.json',dict(status='completed',batch_size=args.batch_size,
        started_monotonic=begin,finished_monotonic=finish,wall_seconds=finish-begin,
        inference_seconds=sum(r['inference_seconds_per_image'] for r in records),images=len(records),
        records=records,load_seconds=load_seconds,rng_adapter_batch1_exact=True,
        all_exact=all(all(r['comparison'][k] for k in ('exact','mask_exact','rgb_exact','intrinsics_exact')) for r in records),
        source_sha256=file_digest(Path(__file__))))
    backend.unload_wt()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch-size',type=int,required=True)
    p.add_argument('--control',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True);args.control.mkdir(parents=True,exist_ok=True)
    try:main(args)
    except Exception as exc:
        atomic_json(args.output/'result.json',dict(status='failed',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc()))
        raise
