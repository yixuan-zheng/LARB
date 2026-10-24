"""Collect a completed stage with sanitized diagnostics; cluster settings come from local env."""
import argparse
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile

ap=argparse.ArgumentParser();ap.add_argument('--job',required=True);ap.add_argument('--exclude-analysis',action='store_true');args=ap.parse_args();assert args.job.isdigit()
target=os.environ['PACE_SSH_TARGET'];runtime=os.environ['PACE_PROJECT_ROOT']
HERE=Path(__file__).resolve().parent;destination=HERE/'results'/('job-'+args.job)
script=r'''
import io,json,os,tarfile
from pathlib import Path
import sys
root=Path.cwd();job=JOB
result=root/'week4/baseline-controls/results'/('job-'+job)
skip_analysis=SKIP_ANALYSIS
redactions=sorted({str(root),str(root.resolve()),str(Path.home()),os.environ.get('PWD','')}-set(['']),key=len,reverse=True)
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 for path in sorted(result.rglob('*')):
  if not path.is_file() or path.name=='scheduler.jsonl':continue
  if skip_analysis and path.relative_to(result).parts[0]=='analysis':continue
  data=path.read_bytes()
  if path.name in ['server.log','requirements-executed.txt']:
   text=data.decode()
   for private in redactions:text=text.replace(private,'<RUNTIME_ROOT>')
   data=text.encode()
  info=tarfile.TarInfo(str(path.relative_to(result)));info.size=len(data);info.mode=0o644
  archive.addfile(info,io.BytesIO(data))
'''.replace('JOB',repr(args.job)).replace('SKIP_ANALYSIS',repr(args.exclude_analysis))
command='cd '+shlex.quote(runtime)+' && python3 -c '+shlex.quote(script)
with tempfile.TemporaryDirectory() as temporary:
    archive=Path(temporary)/'result.tar.gz'
    with archive.open('wb') as output:
        subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=20',target,command],stdout=output,check=True)
    destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as packed:
        for member in packed:
            assert member.isfile() and '..' not in Path(member.name).parts and not Path(member.name).is_absolute()
            path=destination/member.name;data=packed.extractfile(member).read()
            if path.exists():assert path.read_bytes()==data,'Collected immutable evidence changed: '+member.name
            else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
# Scheduler accounting contains no private workspace or login fields.
accounting=subprocess.check_output(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=20',target,
    'sacct -X -j '+args.job+' --noheader --parsable2 --format=JobIDRaw,State,ElapsedRaw,ExitCode,AllocTRES,Start,End'],text=True)
(destination/'accounting.txt').write_text(re.sub(r'CANCELLED by \d+','CANCELLED',accounting))
print('Collected',destination.relative_to(HERE.parent.parent),'with sanitized diagnostics and immutable source/input evidence.')
