#!/usr/bin/env python3
"""Archive only the explicit checked source whitelist, excluding runtime caches."""
import argparse
import gzip
import hashlib
import json
import tarfile
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    a = p.parse_args()
    manifest = json.loads((a.source / "SOURCE_MANIFEST.json").read_text())
    names = sorted([r["path"] for r in manifest["records"]] + ["SOURCE_MANIFEST.json", "SOURCE_SHA256SUMS"])
    assert len(names) == len(set(names))
    assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in names)
    assert not a.archive.exists()
    with a.archive.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=1, mtime=0) as compressed:
            with tarfile.open(mode="w|", fileobj=compressed) as tar:
                for name in names:
                    path = a.source / name
                    assert path.is_file() and not path.is_symlink()
                    info = tarfile.TarInfo("rubalkhali-kg-3.0.0-source/" + name)
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.mtime = 1788998400
                    with path.open("rb") as content:
                        tar.addfile(info, content)
    digest = hashlib.sha256()
    with a.archive.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            digest.update(block)
    result = dict(archive=a.archive.name, bytes=a.archive.stat().st_size, sha256=digest.hexdigest(), archived_files=len(names),
                  scientific_source_files=manifest["files"], scientific_source_bytes=manifest["bytes"],
                  policy="Exact manifest whitelist only, including declared public acceptance tests/witnesses; no symlinks, caches, private correspondence, credentials, administrative backups, .git or unlisted fixtures; no new licence")
    a.archive.with_suffix(a.archive.suffix + ".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
