"""Render compact inspection sheets without modifying inference or evaluation artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

from evaluation.geometry import transform_points
from evaluation.render import Rasterizer, load_mesh_parts, make_camera, normalize_parts
from wt.experiment import atomic_json, file_digest, read_json, resolve_reference, run_directory
from wt.paths import OUTPUT_ROOT
from wt.textured_mesh.canon import GLB_TO_CANONICAL

SIZE = 192
REPO = Path(__file__).resolve().parents[1]


def composite(image):
    image = image.convert("RGBA")
    background = Image.new("RGBA", image.size, (238, 238, 238, 255))
    background.alpha_composite(image)
    background = background.convert("RGB")
    background.thumbnail((SIZE, SIZE))
    tile = Image.new("RGB", (SIZE, SIZE), (238, 238, 238))
    tile.paste(background, ((SIZE-background.width)//2, (SIZE-background.height)//2))
    return tile


def cloud_image(points, camera):
    xyz = transform_points(points, np.asarray(camera["T_world_to_camera"]))
    K = np.asarray(camera["K"])
    valid = np.isfinite(xyz).all(1) & (xyz[:, 2] > 0)
    xyz = xyz[valid]
    uv = xyz[:, :2] / xyz[:, 2:3] * K.diagonal()[:2] + K[:2, 2]
    uv = np.floor(uv).astype(np.int64)
    depth = np.full((SIZE, SIZE), np.inf)
    for dx,dy in [(0,0),(-1,0),(1,0),(0,-1),(0,1)]:
        x,y=uv[:,0]+dx,uv[:,1]+dy
        keep=(x>=0)&(x<SIZE)&(y>=0)&(y<SIZE)
        np.minimum.at(depth,(y[keep],x[keep]),xyz[keep,2])
    mask=np.isfinite(depth)
    assert mask.any(), "Empty point preview"
    rgb=np.full((SIZE,SIZE,3),238,dtype=np.uint8)
    low,high=np.quantile(depth[mask],[.01,.99])
    tone=np.clip((depth[mask]-low)/max(high-low,1e-6),0,1)
    rgb[mask]=np.stack([95-40*tone,150-60*tone,185-60*tone],axis=1).astype(np.uint8)
    return Image.fromarray(rgb)


def selection(root, spec, recipe):
    ids=(read_json(REPO/"configs/historical_gso_samples.json")[spec["split"]]
         if "split" in spec else recipe["qualitative_ids"])
    if spec.get("split") != "eval100":
        return ids, "All frozen samples"
    scored=[]
    for sample in ids:
        path=run_directory(root,sample,"wt_trellis2","defaults-v1",42)/"metrics.json"
        metrics=read_json(path)["metrics"]
        score=next(r["value"] for r in metrics if r["protocol_id"]=="gso-shape-sim3-v1" and r["metric"]=="cd_euclidean_mean")
        scored.append((score,sample))
    chosen=list(ids[:5])
    for _,sample in sorted(scored,reverse=True):
        if sample not in chosen:
            chosen.append(sample)
        if len(chosen)==10:
            break
    return chosen, "First five frozen IDs plus highest hybrid CD-L1, deduplicated to ten"


def render(root):
    recipe=read_json(REPO/"configs/recovery_experiments.json")
    spec=next(s for s in recipe["experiments"] if s["id"]==root.name)
    ids,rule=selection(root,spec,recipe)
    configs=read_json(REPO/spec["configs"])
    # Configuration files may use the batch wrapper object.
    from wt.batch import resolve_configs
    methods=[(c["method"],c["config_id"]) for c in resolve_configs(configs)]
    methods.append(("pixal3d","resolution1024-v1"))
    out=OUTPUT_ROOT/"validation/recovery-20261105"/root.name/"visuals"
    out.mkdir(parents=True,exist_ok=True)
    renderer=Rasterizer()
    fingerprints={}
    pages=[]
    for offset in range(0,len(ids),3):
        group=ids[offset:offset+3]
        width=(len(methods)+1)*SIZE
        height=len(group)*(2*SIZE+50)
        sheet=Image.new("RGB",(width,height),(248,248,248))
        draw=ImageDraw.Draw(sheet)
        for row,sample_id in enumerate(group):
            y0=row*(2*SIZE+50)
            sample_path=root/"samples"/sample_id/"input.json"
            sample=read_json(sample_path)
            image_path=resolve_reference(sample_path.parent,sample["image"])
            assert file_digest(image_path)==sample["sha256"]
            fingerprints[str(sample_path)]=file_digest(sample_path)
            with Image.open(image_path) as image:
                sheet.paste(composite(image),(0,y0+30))
            draw.text((4,y0+5),sample_id[:90],fill="black")
            draw.text((4,y0+SIZE+36),"Input / views A and B",fill="black")
            if "evaluation_dir" in sample:
                camera_path=Path(sample["evaluation_dir"])/"camera.json"
                camera=read_json(camera_path)
                front=dict(camera)
                front["K"]=(np.asarray(camera["K"])*SIZE/camera["resolution"]).tolist()
                front["K"][2][2]=1.
                front["resolution"]=SIZE
                back=make_camera(camera["azimuth_degrees"]+180,elevation=camera["elevation_degrees"],resolution=SIZE)
                cameras=[front,back]
                fingerprints[str(camera_path)]=file_digest(camera_path)
            else:
                cameras=[make_camera(a,elevation=15,resolution=SIZE) for a in (-90,90)]
            for col,(method,config) in enumerate(methods,1):
                directory=run_directory(root,sample_id,method,config,42)
                state=read_json(directory/"run.json")
                assert state["status"]=="complete"
                inputs=[directory/"run.json",directory/"config.json"]
                matrix=None
                if "evaluation_dir" in sample:
                    matrix=np.asarray(read_json(directory/"registration.json")["matrix"])
                    inputs.append(directory/"registration.json")
                if method=="wt":
                    inputs.append(directory/"prediction.npz")
                    with np.load(directory/"prediction.npz",allow_pickle=False) as data:
                        points=data["xyz"][data["mask"]]
                    if len(points)>300000:
                        points=points[np.random.default_rng(0).choice(len(points),300000,replace=False)]
                    if matrix is not None:
                        points=transform_points(points,matrix)
                    else:
                        points=np.stack([points[:,0],points[:,2],-points[:,1]],1)
                        lower,upper=points.min(0),points.max(0)
                        points=(points-(lower+upper)/2)/np.linalg.norm(upper-lower)
                    tiles=[cloud_image(points,camera) for camera in cameras]
                else:
                    inputs += [directory/"mesh.glb",directory/"mesh.json"]
                    parts=load_mesh_parts(directory/"mesh.glb")
                    rotation=np.eye(4)
                    if matrix is not None:
                        if method=="pixal3d":
                            rotation=np.linalg.inv(np.asarray(read_json(directory/"mesh.json")["decoded_to_glb"]))
                        else:
                            rotation[:3,:3]=GLB_TO_CANONICAL
                        transform=matrix@rotation
                        for mesh in parts:
                            mesh.apply_transform(transform)
                    else:
                        # Display normalization only. Native methods have no verified input-camera pose.
                        parts,_,_=normalize_parts(parts,"y")
                    tiles=[]
                    for camera in cameras:
                        rgba,_,mask,_=renderer.render(parts,camera["K"],camera["T_world_to_camera"],SIZE,texture=True)
                        assert mask.any(), "Empty textured preview"
                        tiles.append(composite(Image.fromarray(rgba)))
                    del parts
                label=method+("/shared" if config=="shared-wt-v1" else "")
                draw.text((col*SIZE+3,y0+15),label,fill="black")
                for view,tile in enumerate(tiles):
                    sheet.paste(tile,(col*SIZE,y0+30+view*SIZE))
                for path in inputs:
                    fingerprints[str(path)]=file_digest(path)
                print("PREVIEW",root.name,sample_id,method,config,flush=True)
        name=f"page-{offset//3+1:02d}.png"
        sheet.save(out/name)
        pages.append(dict(path=name,sha256=file_digest(out/name),samples=group))
    assert all(file_digest(Path(p))==sha for p,sha in fingerprints.items())
    atomic_json(out/"manifest.json",dict(status="rendered-awaiting-visual-review",samples=ids,selection=rule,pages=pages,
        source_sha256=fingerprints,script_sha256=file_digest(Path(__file__)),
        gso_views="Saved Sim(3) registration applied only for display, frozen camera and reverse view",
        qualitative_views="Per-output bounds normalization, canonical glTF axes, two opposite views; no camera-pose claim",
        wt_display="At most 300000 deterministic points with one-pixel splatting and depth shading",
        mesh_display="Full exported GLB geometry, base color texture, no scene lighting; not the geometry used for scoring"))
    print(out,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment",type=Path,required=True)
    args=parser.parse_args()
    render(args.experiment)
