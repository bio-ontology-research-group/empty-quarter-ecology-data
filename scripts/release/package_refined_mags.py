#!/usr/bin/env python3
"""Package actual refined dRep FASTAs and verify the exact archived bytes."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fasta_counts(data):
    identifiers = set()
    bases = 0
    sequence_length = None
    for line in data.splitlines():
        if not line:
            continue
        if line.startswith(b">"):
            if sequence_length == 0:
                raise ValueError("empty FASTA sequence")
            fields = line[1:].split()
            if not fields or fields[0] in identifiers:
                raise ValueError("missing or duplicate FASTA identifier")
            identifiers.add(fields[0])
            sequence_length = 0
        else:
            if sequence_length is None:
                raise ValueError("sequence before FASTA header")
            if any(c in line for c in (b" ", b"\t")):
                raise ValueError("whitespace inside FASTA sequence")
            sequence_length += len(line)
            bases += len(line)
    if not identifiers or sequence_length == 0:
        raise ValueError("empty FASTA sequence or file")
    return len(identifiers), bases


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(data))


def build(genomes, metadata, output):
    with metadata.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    names = [r["drep_fasta_basename"] for r in rows]
    if not names or len(names) != len(set(names)):
        raise ValueError("empty or duplicate representative list")
    if any(name != Path(name).name or not name.endswith(".fa") for name in names):
        raise ValueError("unsafe FASTA basename")
    if set(names) != {p.name for p in genomes.glob("*.fa")}:
        raise ValueError("actual dRep FASTA set differs from metadata")
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "refined_mags.tar.gz"
    if archive_path.exists():
        raise ValueError(f"refusing to overwrite existing archive: {archive_path}")
    temporary = output / "refined_mags.tar.gz.partial"
    manifest = []
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=1, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as archive:
                    for i, row in enumerate(sorted(rows, key=lambda r: r["mag"]), 1):
                        name = row["drep_fasta_basename"]
                        if name != row["mag"] + ".fa":
                            raise ValueError(f"representative/FASTA mismatch: {name}")
                        data = (genomes / name).read_bytes()
                        contigs, bases = fasta_counts(data)
                        if (contigs, bases) != (int(row["Total_Contigs"]), int(row["Genome_Size"])):
                            raise ValueError(f"refined CheckM2/FASTA mismatch for {name}: {contigs} contigs, {bases} bp")
                        member = "genomes/" + name
                        manifest.append({"mag": row["mag"], "path": member, "bytes": len(data),
                                         "sha256": hashlib.sha256(data).hexdigest(), "contigs": contigs, "bases": bases})
                        add_bytes(archive, member, data)
                        if i % 250 == 0:
                            print(f"packaged {i}/{len(rows)} genomes", flush=True)
                    text = io.StringIO(newline="")
                    writer = csv.DictWriter(text, fieldnames=list(manifest[0]), delimiter="\t", lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(manifest)
                    manifest_bytes = text.getvalue().encode()
                    add_bytes(archive, "genome_manifest.tsv", manifest_bytes)
        expected = {r["path"]: r for r in manifest}
        seen = set()
        with tarfile.open(temporary, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile() or member.name in seen:
                    raise ValueError(f"invalid archive member: {member.name}")
                seen.add(member.name)
                handle = archive.extractfile(member)
                if member.name == "genome_manifest.tsv":
                    if handle.read() != manifest_bytes:
                        raise ValueError("internal manifest differs")
                    continue
                row = expected[member.name]
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                if member.size != row["bytes"] or digest.hexdigest() != row["sha256"]:
                    raise ValueError(f"archive checksum mismatch: {member.name}")
        if seen != set(expected) | {"genome_manifest.tsv"}:
            raise ValueError("archive membership differs")
        receipt = {"artifact": "refined_mags.tar.gz", "bytes": temporary.stat().st_size,
                   "sha256": sha256(temporary), "representatives": len(rows),
                   "contigs": sum(r["contigs"] for r in manifest), "bases": sum(r["bases"] for r in manifest),
                   "genome_source": str(genomes), "metadata_sha256": sha256(metadata),
                   "archive_members_verified": True, "quality_lengths_verified": True}
        temporary.replace(archive_path)
        (output / "genome_manifest.tsv").write_bytes(manifest_bytes)
        (output / "packaging_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(json.dumps(receipt), flush=True)
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genomes", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.genomes, args.metadata, args.output)
