"""Render the six controlled texture seeds with one fixed display transform per group."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from evaluation.render import Rasterizer,load_mesh_parts,normalize_parts,make_camera
from wt.experiment import atomic_json,file_digest,read_json,run_directory

SIZE=384

def main(root):
    recipe=read_json(Path(__file__).resolve().parents[1]/"configs/recovery_experiments.json")["supplemental"][1]
    assert root.name==recipe["id"]
    out=root/"review"
    out.mkdir(parents=True,exist_ok=True)
    renderer=Rasterizer()
    width=3*SIZE
    height=2*(2*SIZE+44)
    sheet=Image.new("RGB",(width,height),(245,245,245))
    draw=ImageDraw.Draw(sheet)
    sources={}
    for row,config in enumerate(recipe["configs"]):
        transform=None
        for col,seed in enumerate(recipe["texture_seeds"]):
            folder=run_directory(root,recipe["sample"],"wt_trellis2",config,seed)
            assert read_json(folder/"run.json")["status"]=="complete"
            parts=load_mesh_parts(folder/"mesh.glb")
            if transform is None:
                parts,transform,_=normalize_parts(parts,"y")
            else:
                for mesh in parts:mesh.apply_transform(transform)
            x,y=col*SIZE,row*(2*SIZE+44)
            draw.text((x+6,y+7),config+" / texture seed "+str(seed),fill="black")
            for view,angle in enumerate((-90,90)):
                camera=make_camera(angle,elevation=10,resolution=SIZE)
                rgba,_,mask,_=renderer.render(parts,camera["K"],camera["T_world_to_camera"],SIZE,texture=True)
                assert mask.any()
                image=Image.fromarray(rgba)
                bg=Image.new("RGBA",image.size,(235,235,235,255))
                bg.alpha_composite(image)
                sheet.paste(bg.convert("RGB"),(x,y+30+view*SIZE))
            for name in ("mesh.glb","mesh.json","run.json","config.json"):
                p=folder/name;sources[str(p)]=file_digest(p)
    sheet.save(out/"texture-seeds.png")
    assert all(file_digest(Path(p))==sha for p,sha in sources.items())
    atomic_json(out/"manifest.json",dict(status="rendered-awaiting-visual-review",runs=6,
        image_sha256=file_digest(out/"texture-seeds.png"),source_sha256=sources,
        script_sha256=file_digest(Path(__file__)),
        views="Two opposite canonical glTF views; fixed bounds normalization within each group; base-color texture under unit ambient"))
    print(out,flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment",type=Path,required=True)
    main(parser.parse_args().experiment)
