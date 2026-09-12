#!/usr/bin/env python3
"""Stream-verify every whitelisted archive member and protected source identity."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def archive_manifest(path):
    with tarfile.open(path, 'r|gz') as tar:
        for member in tar:
            if member.name.endswith('/SOURCE_MANIFEST.json'):
                return json.load(tar.extractfile(member))
    raise ValueError('no source manifest')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    got={}; manifest=None; sums=None
    with tarfile.open(a.archive,'r|gz') as tar:
        for member in tar:
            path=PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            assert path.parts[0]=='rubalkhali-kg-3.0.0-source'
            relative='/'.join(path.parts[1:]); assert relative not in got
            content=tar.extractfile(member); h=hashlib.sha256(); collected=[]
            for chunk in iter(lambda:content.read(1024*1024),b''):
                h.update(chunk)
                if relative in ('SOURCE_MANIFEST.json','SOURCE_SHA256SUMS'): collected.append(chunk)
            got[relative]=dict(sha256=h.hexdigest(),bytes=member.size)
            if relative=='SOURCE_MANIFEST.json':manifest=json.loads(b''.join(collected))
            if relative=='SOURCE_SHA256SUMS':sums=b''.join(collected).decode()
    records={r['path']:r for r in manifest['records']}
    assert set(got)==set(records)|{'SOURCE_MANIFEST.json','SOURCE_SHA256SUMS'}
    for name,row in records.items():assert got[name]==dict(sha256=row['sha256'],bytes=row['bytes'])
    assert sums==''.join(r['sha256']+'  '+r['path']+'\n' for r in manifest['records'])
    old={r['path']:r for r in archive_manifest(a.previous)['records']}
    protected=[name for name in old if name.startswith(('data/','config/','env/','scripts/rdf/','scripts/taxonomy/')) or name in ('scripts/release/rebuild_public_sources.sh','scripts/release/stamp_kg_release.py','scripts/release/write_offline_catalog.py','expected/fresh_modules_manifest.json','scripts/release/kg/materialize.py')]
    assert protected
    for name in protected:assert name in records and old[name]['sha256']==records[name]['sha256'],name
    h=hashlib.sha256()
    with a.archive.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):h.update(chunk)
    report=dict(passed=True,archive=a.archive.name,archive_bytes=a.archive.stat().st_size,archive_sha256=h.hexdigest(),verified_members=len(got),whitelisted_files=len(records),uncompressed_bytes=manifest['bytes'],protected_files_unchanged=len(protected),protected_files=protected,added=sorted(set(records)-set(old)),changed=sorted(name for name in old if name in records and old[name]['sha256']!=records[name]['sha256']),removed=sorted(set(old)-set(records)))
    with a.report.open('x') as handle:json.dump(report,handle,indent=2);handle.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('protected_files','added','changed','removed')},indent=2))


if __name__=='__main__':main()
