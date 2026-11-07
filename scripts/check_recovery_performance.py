"""Require a reviewed performance decision before the R2 recovery starts."""
from pathlib import Path
from wt.experiment import read_json,file_digest
from wt.paths import OUTPUT_ROOT

REPO=Path(__file__).resolve().parents[1]
DECISION=OUTPUT_ROOT/'validation/single-gpu-batch-20261105/decision.json'

def check():
    value=read_json(DECISION)
    assert value['status']=='reviewed' and value['seed']==42 and value['wt_batch_size']==1
    assert all(value['workers'][kind] in (1,2) for kind in ('baseline','pixal'))
    assert value['runner_sha256']==file_digest(REPO/'scripts/run_parallel_recovery.py')
    for path,sha in value['evidence_sha256'].items():assert file_digest(Path(path))==sha,path
    for revision in value.get('accepted_prior_decisions',[]):
        path=Path(revision['path'])
        assert file_digest(path)==revision['sha256']
        prior=read_json(path)
        assert prior['status']=='reviewed' and prior['seed']==42 and prior['wt_batch_size']==1
        assert file_digest(Path(revision['runner_snapshot']))==prior['runner_sha256']
        for evidence,sha in prior['evidence_sha256'].items():assert file_digest(Path(evidence))==sha,evidence
    return value

if __name__=='__main__':
    result=check()
    print('Reviewed single-GPU policy:',result['workers'],'WT batch=',result['wt_batch_size'])
