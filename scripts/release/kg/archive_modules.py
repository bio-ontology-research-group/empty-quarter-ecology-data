#!/usr/bin/env python3
"""Archive exactly the final hash-listed RDF modules and offline catalogue."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if root.parent != Path('/data/empty-quarter-releases'):
        raise ValueError('explicit isolated release root required')
    source = root / 'inputs/scientific'
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest['version'] != '3.0.0' or len(manifest['records']) != 16:
        raise ValueError('unexpected module inventory')
    files = []
    for item in manifest['records']:
        path = source / item['file']
        if path.parent != source or path.is_symlink() or not path.is_file():
            raise ValueError('invalid module path')
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('module checksum mismatch: ' + item['file'])
        files.append(path)
    files += [source / name for name in ('manifest.json', 'SHA256SUMS', 'catalog-v001.xml')]
    if len({path.name for path in files}) != 19:
        raise ValueError('duplicate archive entries')
    target = root / 'publication/kg/3.0.0/rubalkhali-kg-3.0.0-modules.tar.gz'
    with target.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=1, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(files):
                info = archive.gettarinfo(str(path), arcname='rubalkhali-kg-3.0.0-modules/' + path.name)
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = 0
                info.mode = 0o644
                info.pax_headers = {}
                with path.open('rb') as handle:
                    archive.addfile(info, handle)
    result = {'name': target.name, 'url': '/downloads/kg/3.0.0/' + target.name,
              'bytes': target.stat().st_size, 'sha256': digest(target),
              'description': 'Sixteen original RDF modules, pinned imported ontologies, input checksums and an offline import catalogue.',
              'module_count': 16, 'archive_members': 19, 'passed': True}
    (root / 'evidence/modules_archive.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
