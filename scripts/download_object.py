"""Download the authorised WT object checkpoint; HF_TOKEN comes from environment."""
import os
from pathlib import Path
import sys
import time

from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout
from wt.paths import configure_cache_paths

configure_cache_paths()

from huggingface_hub import hf_hub_download

token = os.environ.get('HF_TOKEN')
token_file = Path(__file__).resolve().parents[1] / '.runtime/hf_token'
if not token and token_file.is_file():
    if token_file.stat().st_mode & 0o077:
        raise PermissionError('HF token file must have mode 600')
    token = token_file.read_text().strip()

for attempt in range(5):
    try:
        path = hf_hub_download('haoz19/object-model-6layer', 'model.pt',
                              revision='e9da924a0e00bb46569cc5e351bddb9d020b927f',
                              endpoint='https://huggingface.co', token=token or False)
        print(path)
        break
    except (ChunkedEncodingError, ConnectionError, Timeout) as exc:
        if attempt == 4:
            raise
        print(f'Resuming after {type(exc).__name__}, retry {attempt+1}/4', file=sys.stderr, flush=True)
        time.sleep(2)
