"""Lossless packaging of large scheduler logs; preserve and verify raw bytes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil


def sha(path,compressed=False):
    digest=hashlib.sha256()
    with (gzip.open(path,'rb') if compressed else path.open('rb')) as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--unpack',action='store_true');args=ap.parse_args()
root=args.root;raw=root/'scheduler.jsonl';packed=root/'scheduler.jsonl.gz';manifest=root/'storage-manifest.json'
if args.unpack:
    info=json.loads(manifest.read_text())['scheduler.jsonl']
    assert sha(packed)==info['gzip_sha256']
    if not raw.exists():
        temporary=raw.with_suffix('.jsonl.tmp')
        with gzip.open(packed,'rb') as source,temporary.open('wb') as target:shutil.copyfileobj(source,target)
        assert sha(temporary)==info['raw_sha256']
        temporary.replace(raw)
    assert sha(raw)==info['raw_sha256']
    print('Verified materialized scheduler.jsonl')
else:
    original=sha(raw)
    if not packed.exists():
        with packed.open('wb') as target:
            with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0) as output:
                with raw.open('rb') as source:shutil.copyfileobj(source,output)
    assert sha(packed,compressed=True)==original
    info=dict(raw_bytes=raw.stat().st_size,raw_sha256=original,gzip_bytes=packed.stat().st_size,
              gzip_sha256=sha(packed),lossless_roundtrip_verified=True,
              note='Plaintext retained locally and on PACE; Git stores lossless gzip. Materialize before running the original archived analysis.')
    manifest.write_text(json.dumps({'scheduler.jsonl':info},indent=2)+'\n')
    print(json.dumps(info,indent=2))
