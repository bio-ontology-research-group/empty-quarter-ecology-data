#!/usr/bin/env python3
"""Read-only HTTP archive integrity and explicit reference-root attribution audit."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

from rdflib import Graph, OWL, RDF


class HashingReader:
    def __init__(self, response):
        self.response = response
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size=-1):
        block = self.response.read(size)
        self.digest.update(block)
        self.size += len(block)
        return block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-bytes", required=True, type=int)
    parser.add_argument("--expected-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    expected_manifest = json.loads(args.expected_manifest.read_text())
    expected = {r["file"]: r for r in expected_manifest["records"]}
    assert len(expected) == 16
    allowed = set(expected) | {"manifest.json", "SHA256SUMS", "catalog-v001.xml"}
    retain = {"manifest.json", "SHA256SUMS", "catalog-v001.xml", "sio.owl", "envo.owl", "pato.owl", "uo.owl"}
    seen, retained, parents = {}, {}, set()
    with urllib.request.urlopen(args.url, timeout=180) as response:
        assert response.status == 200
        headers = dict(response.headers)
        stream = HashingReader(response)
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                assert member.isfile() and not member.issym(), member.name
                assert not path.is_absolute() and ".." not in path.parts, member.name
                name = path.name
                assert name in allowed and name not in seen, member.name
                parents.add(str(path.parent))
                digest = hashlib.sha256()
                chunks = []
                fileobj = archive.extractfile(member)
                for block in iter(lambda: fileobj.read(1048576), b""):
                    digest.update(block)
                    if name in retain:
                        chunks.append(block)
                seen[name] = dict(bytes=member.size, sha256=digest.hexdigest())
                if name in retain:
                    retained[name] = b"".join(chunks)
        while stream.read(1048576):
            pass
    assert set(seen) == allowed and len(parents) == 1
    assert stream.size == args.expected_bytes
    assert stream.digest.hexdigest() == args.expected_sha256
    embedded = json.loads(retained["manifest.json"])
    embedded_records = {r["file"]: r for r in embedded["records"]}
    assert set(embedded_records) == set(expected)
    for name in expected:
        for key in ("bytes", "sha256"):
            assert seen[name][key] == embedded_records[name][key] == expected[name][key], (name, key)
    checksum_records = {}
    for line in retained["SHA256SUMS"].decode().splitlines():
        digest, name = line.split(None, 1)
        name = name.lstrip("*")
        assert name not in checksum_records
        checksum_records[name] = digest
        assert name in seen and seen[name]["sha256"] == digest, name
    assert set(expected) <= set(checksum_records)
    assert seen["rubalkhali.owl"]["sha256"] == "46ca6cb6994eada44e936f19ba12f25dbc131fc31f76b4e2a46d61af3dfdf3b6"
    attribution = []
    for name in ("sio.owl", "envo.owl", "pato.owl", "uo.owl"):
        graph = Graph().parse(data=retained[name], format="xml")
        for root in sorted(graph.subjects(RDF.type, OWL.Ontology), key=str):
            metadata = []
            licences = []
            for predicate, value in sorted(graph.predicate_objects(root), key=lambda item: (str(item[0]), str(item[1]))):
                term = str(predicate).lower()
                record = dict(predicate=str(predicate), value=str(value), term_type=type(value).__name__)
                if any(token in term for token in ("license", "licence", "rights", "copyright")):
                    licences.append(record)
                if any(token in term for token in ("version", "title", "creator", "contributor", "publisher")):
                    metadata.append(record)
            attribution.append(dict(file=name, sha256=seen[name]["sha256"], ontology=str(root), explicit_licence_annotations=licences, attribution_metadata=metadata,
                                    scope="Exact ontology-root annotations only; an absent annotation is not permission or a new licence grant."))
    result = dict(passed=True, url=args.url, http_headers=headers, archive_bytes=stream.size,
                  archive_sha256=stream.digest.hexdigest(), verified_members=len(seen), verified_rdf_modules=len(expected),
                  archive_parent=next(iter(parents)), members=seen, reference_attribution=attribution,
                  checks="Exact19 regular-file members; no extras/symlinks/path escapes; all16 RDF hashes/sizes match embedded and independent frozen manifests; embedded checksums agree; corrected root hash confirmed.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("passed", "archive_bytes", "archive_sha256", "verified_members", "verified_rdf_modules", "reference_attribution")}, indent=2))


if __name__ == "__main__":
    main()
