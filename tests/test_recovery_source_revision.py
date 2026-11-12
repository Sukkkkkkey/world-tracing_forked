"""Keep historical source checks valid after normal development."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts import finalize_recovery


def git(root, *arguments):
    return subprocess.check_output(
        ['git', '-C', str(root), '-c', 'user.name=Test',
         '-c', 'user.email=test@example.invalid', *arguments],
        stderr=subprocess.PIPE, text=True).strip()


@pytest.fixture
def recorded_source(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    original = b'original recovery viewer\n'
    (repo / 'viewer.py').write_bytes(original)
    git(repo, 'add', 'viewer.py')
    git(repo, 'commit', '-qm', 'record recovery')
    commit = git(repo, 'rev-parse', 'HEAD')
    audits = tmp_path / 'audits'
    audits.mkdir()
    review = audits / 'source-review.json'
    review.write_text(json.dumps({
        'status': 'reviewed',
        'files': [{'path': 'viewer.py',
                   'current_sha256': hashlib.sha256(original).hexdigest()}],
    }))
    (repo / 'configs').mkdir()
    lock = repo / 'configs/recovery_source.json'
    lock.write_text(json.dumps({
        'commit': commit,
        'review_sha256': hashlib.sha256(review.read_bytes()).hexdigest(),
    }))
    monkeypatch.setattr(finalize_recovery, 'REPO', repo)
    monkeypatch.setattr(finalize_recovery, 'AUDITS', audits)
    return repo, audits, commit


def test_default_uses_recorded_commit_after_viewer_edit(recorded_source):
    repo, _, commit = recorded_source
    (repo / 'viewer.py').write_text('new viewer implementation\n')
    assert finalize_recovery.verify_reviewed_sources() == commit


def test_explicit_matching_revision(recorded_source):
    _, _, commit = recorded_source
    assert finalize_recovery.verify_reviewed_sources(commit) == commit


def test_changed_source_in_selected_commit_is_rejected(recorded_source):
    repo, _, _ = recorded_source
    (repo / 'viewer.py').write_text('different historical source\n')
    git(repo, 'add', 'viewer.py')
    git(repo, 'commit', '-qm', 'change viewer')
    with pytest.raises(AssertionError, match='viewer.py'):
        finalize_recovery.verify_reviewed_sources('HEAD')


def test_changed_review_is_rejected(recorded_source):
    _, audits, _ = recorded_source
    path = audits / 'source-review.json'
    path.write_text(path.read_text() + '\n')
    with pytest.raises(AssertionError, match='source review changed'):
        finalize_recovery.verify_reviewed_sources()


def test_option_like_revision_is_rejected(recorded_source):
    with pytest.raises(subprocess.CalledProcessError):
        finalize_recovery.verify_reviewed_sources('--help')
