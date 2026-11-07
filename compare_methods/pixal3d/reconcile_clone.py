"""Reconcile the eight pip/Conda overlaps after cloning the project environment."""
import argparse,base64,datetime,hashlib,importlib,importlib.metadata,json,os
from pathlib import Path
import re,subprocess,sys,tarfile

ROOT=Path(__file__).resolve().parents[2]
ENV=(ROOT/".venv-pixal3d").resolve()
SITE=ENV/"lib/python3.11/site-packages"
SETUP=ROOT/"compare_methods/pixal3d"
WHEELS=ROOT/".runtime/cache/pixal3d/clone-python-wheels"
normalize=lambda s:re.sub(r"[-_.]+","-",s).lower()
LOCK=json.loads((SETUP/"clone-python.lock.json").read_text())
PACKAGES={normalize(r["name"]):r for r in LOCK["packages"]}


def distributions():
    return [d for d in importlib.metadata.distributions(path=[str(SITE)])
            if normalize(d.metadata.get("Name","")) in PACKAGES]


def verify():
    values=distributions()
    reports=[]
    for name,record in PACKAGES.items():
        matches=[d for d in values if normalize(d.metadata["Name"])==name]
        assert len(matches)==1,(name,"duplicate/missing metadata",len(matches))
        d=matches[0]
        assert d.version==record["version"],(name,d.version)
        count=0
        for entry in d.files or []:
            if not entry.hash or entry.hash.mode!="sha256":continue
            path=Path(d.locate_file(entry)).resolve()
            assert path.is_relative_to(ENV),path
            digest=base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode()
            assert digest==entry.hash.value,(name,str(entry),"RECORD mismatch")
            count+=1
        reports.append(dict(name=name,version=d.version,files_verified=count))
    return reports


def main(repair):
    assert Path(sys.prefix).resolve()==ENV,"Use the isolated Pixal Python"
    try:
        checked=verify()
    except (AssertionError,FileNotFoundError):
        if not repair:raise
        WHEELS.mkdir(parents=True,exist_ok=True)
        def wheels_ready():
            return all(any(hashlib.sha256(p.read_bytes()).hexdigest()==r["sha256"] for p in WHEELS.glob("*.whl"))
                       for r in PACKAGES.values())
        if not wheels_ready():
            subprocess.run([sys.executable,"-m","pip","download","--no-deps","--only-binary=:all:",
                "--require-hashes","--index-url","https://mirrors.aliyun.com/pypi/simple",
                "--dest",str(WHEELS),"-r",str(SETUP/"clone-python-repair.txt")],check=True)
        assert wheels_ready()
        snapshot=ROOT/".runtime"/("clone-python-before-repair-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+".tar.gz")
        files=set()
        for d in distributions():
            for entry in d.files or []:
                path=Path(d.locate_file(entry)).resolve()
                assert path.is_relative_to(ENV),path
                if path.is_file():files.add(path)
        assert not snapshot.exists(),"Preserve/review prior repair snapshot before another destructive repair"
        with tarfile.open(snapshot,"w:gz") as tar:
            for path in sorted(files):
                tar.add(path,arcname=str(path.relative_to(ENV)),recursive=False)
        for attempt in range(3):
            names=sorted({d.metadata["Name"] for d in distributions()})
            if not names:break
            subprocess.run([sys.executable,"-m","pip","uninstall","-y",*names],check=True)
            importlib.invalidate_caches()
        assert not distributions(),"Duplicate package metadata remains"
        subprocess.run([sys.executable,"-m","pip","install","--no-index","--no-deps","--require-hashes",
            "--find-links",str(WHEELS),"-r",str(SETUP/"clone-python-repair.txt")],check=True)
        checked=verify()
    # Do imports in a fresh process so no pre-repair module stays cached.
    check='import requests,charset_normalizer; text="恢复实验结果，校验环境依赖。"; raw=text.encode("utf-8"); assert str(charset_normalizer.from_bytes(raw).best())==text; r=requests.Response(); r._content=raw; assert r.apparent_encoding.lower().replace("-","_")=="utf_8"'
    subprocess.run([sys.executable,"-W","error","-c",check],check=True)
    subprocess.run([sys.executable,"-m","pip","check"],check=True)
    freeze=subprocess.run([sys.executable,"-m","pip","freeze","--all"],check=True,capture_output=True,text=True).stdout
    (SETUP/"requirements.lock.txt").write_text(freeze)
    report=dict(status="passed",environment=str(ENV),packages=checked,
        lock_sha256=hashlib.sha256((SETUP/"clone-python.lock.json").read_bytes()).hexdigest(),
        finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
    out=Path(os.environ["WT_OUTPUT_ROOT"])/"validation/pixal3d-clone-python.json"
    out.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair",action="store_true")
    main(parser.parse_args().repair)
