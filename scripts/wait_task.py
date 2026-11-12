"""Wait for a named recovery task; propagate failure and detect lost wrappers."""
import argparse
import json
import os
from pathlib import Path
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('name')
p.add_argument('--timeout', type=float, default=43200)
args = p.parse_args()
path = Path(__file__).resolve().parents[1] / '.runtime/logs/recovery-20261105' / (args.name + '.status.json')
started, previous = time.monotonic(), None
while time.monotonic() - started < args.timeout:
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        state = {'status': 'pending'}
    if state['status'] != previous:
        print('DEPENDENCY', args.name, state['status'], flush=True)
        previous = state['status']
    if state['status'] == 'passed':
        raise SystemExit(0)
    if state['status'] == 'failed':
        raise SystemExit('Dependency failed: ' + args.name)
    if state['status'] == 'running':
        try:
            os.kill(state['pid'], 0)
        except ProcessLookupError:
            raise SystemExit('Dependency wrapper exited without a final status: ' + args.name)
    time.sleep(10)
raise SystemExit('Dependency wait timed out: ' + args.name)
