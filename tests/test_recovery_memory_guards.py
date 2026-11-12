"""Data-loss guards for the selective R2 OOM recovery."""
import json
from pathlib import Path
import shutil
import pytest
from scripts.repair_recovery_memory import remove_archived_failed, verify_hashes
from wt.experiment import file_digest

@pytest.fixture
def paths(tmp_path):
    root=tmp_path/'experiment'
    target=root/'samples'/'sample'/'wt_trellis2'/'defaults-v1'/'seed-0042'
    target.mkdir(parents=True)
    (target/'run.json').write_text(json.dumps({'status':'failed'}))
    (target/'run.log').write_text('CUDA out of memory')
    archive=tmp_path/'archive';shutil.copytree(target,archive)
    neighbor=root/'samples'/'other'/'wt_trellis2'/'defaults-v1'/'seed-0042'
    neighbor.mkdir(parents=True)
    (neighbor/'run.json').write_text(json.dumps({'status':'complete'}))
    return root,target,archive,neighbor

def refused(paths):
    root,target,archive,neighbor=paths
    with pytest.raises((AssertionError,FileNotFoundError,ValueError)):
        remove_archived_failed(root,target,archive)
    assert target.exists()
    assert json.loads((neighbor/'run.json').read_text())['status']=='complete'

def test_exact_failed_archive_only_removes_target(paths):
    root,target,archive,neighbor=paths
    remove_archived_failed(root,target,archive)
    assert not target.exists()
    assert (archive/'run.log').read_text()=='CUDA out of memory'
    assert json.loads((neighbor/'run.json').read_text())['status']=='complete'

@pytest.mark.parametrize('state',['complete','running','planned'])
def test_nonfailed_state_is_preserved(paths,state):
    for folder in paths[1:3]:
        (folder/'run.json').write_text(json.dumps({'status':state}))
    refused(paths)

def test_evaluated_directory_is_preserved(paths):
    for folder in paths[1:3]:(folder/'metrics.json').write_text('{}')
    refused(paths)

def test_changed_file_is_preserved(paths):
    (paths[1]/'run.log').write_text('later attempt')
    refused(paths)

def test_archive_extra_file_is_rejected(paths):
    (paths[2]/'extra').write_text('unexpected')
    refused(paths)

def test_archive_missing_file_is_rejected(paths):
    (paths[2]/'run.log').unlink()
    refused(paths)

def test_outside_project_is_preserved(paths,tmp_path):
    root,target,archive,neighbor=paths
    outside=tmp_path/'outside';shutil.copytree(target,outside)
    refused((root,outside,archive,neighbor))

def test_wrong_directory_depth_is_preserved(paths):
    root,target,archive,neighbor=paths
    wrong=root/'samples'/'seed-0042';shutil.copytree(target,wrong)
    refused((root,wrong,archive,neighbor))

def test_symlink_directory_is_preserved(paths):
    root,target,archive,neighbor=paths
    link=root/'samples'/'linked';link.symlink_to(target,target_is_directory=True)
    refused((root,link,archive,neighbor))
    assert target.exists()

def test_nested_symlink_is_rejected(paths):
    (paths[1]/'linked').symlink_to(paths[3]/'run.json')
    (paths[2]/'linked').symlink_to(paths[3]/'run.json')
    refused(paths)

def test_preservation_hash_detects_changed_result(paths):
    root,target,archive,neighbor=paths
    rel=str((neighbor/'run.json').relative_to(root))
    records={rel:file_digest(neighbor/'run.json')}
    verify_hashes(root,records)
    (neighbor/'run.json').write_text('changed')
    with pytest.raises(AssertionError,match='Preserved artifact changed'):
        verify_hashes(root,records)
