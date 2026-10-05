"""Read-only local source/evidence hash check; no settings/provider/cloud imports."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DEFAULT=ROOT/'docs/verification/v12-quality-20261005/manifest.json'


def check(path):
    manifest=json.loads(path.read_text());mismatches=[]
    for row in manifest['files']+manifest['preserved_evidence']:
        target=(ROOT/row['path']).resolve()
        if not target.is_relative_to(ROOT) or not target.is_file():
            mismatches.append({'path':row['path'],'error':'missing_or_outside_root'})
        elif hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:
            mismatches.append({'path':row['path'],'error':'hash_changed'})
    return {'kind':'read_only_v12_freeze_check','files':len(manifest['files']),
            'preserved_evidence':len(manifest['preserved_evidence']),
            'provider_calls':0,'mismatches':mismatches,'passed':not mismatches}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,default=DEFAULT)
    parser.add_argument('--output',type=Path);args=parser.parse_args();result=check(args.manifest)
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n';print(text,end='')
    if args.output: args.output.write_text(text)
    raise SystemExit(0 if result['passed'] else 1)
