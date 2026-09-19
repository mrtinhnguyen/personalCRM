"""Copy changed, already-collected Instagram files to NAS over the existing SSH key.

No provider requests, deletes, credential files, or collector scheduling changes.
Only publish after a successful local archive cycle; unchanged files are skipped.
"""
import argparse
import json
import shlex
import subprocess
import tarfile
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--host',default='crm-nas')
parser.add_argument('--destination',default='/srv/monica-next/data/staging/instagram-current')
parser.add_argument('--dry-run',action='store_true')
args=parser.parse_args()
root=args.root/'data/profiles';state=args.root/'state/crm-published-files.json'
before=json.loads(state.read_text()) if state.exists() else {}
after={};changed=[]
for path in sorted(root.glob('*/*')):
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.json','.jpg','.jpeg','.png','.webp','.mp4'}:continue
    key=path.relative_to(root).as_posix();info=path.stat();value=[info.st_size,info.st_mtime_ns];after[key]=value
    if before.get(key)!=value:changed.append((path,key))
if changed and not args.dry_run:
    destination=shlex.quote(args.destination)
    command=f'umask 077; mkdir -p {destination}/profiles && tar -xf - -C {destination}/profiles && date -u +%s > {destination}/.crm-ready'
    process=subprocess.Popen(['ssh','-o','BatchMode=yes',args.host,command],stdin=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdin,mode='w|') as archive:
            for path,key in changed:archive.add(path,arcname=key,recursive=False)
    finally:process.stdin.close()
    if process.wait():raise SystemExit('NAS archive transfer failed; publication state was not advanced')
    temporary=state.with_suffix('.tmp');temporary.write_text(json.dumps(after,sort_keys=True));temporary.chmod(0o600);temporary.replace(state)
print(json.dumps({'changed_files':len(changed),'source_files':len(after),'published':not args.dry_run}))
