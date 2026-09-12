#!/usr/bin/env python3
"""Derive deterministic KG release metadata without changing entity axioms.

The version is explicit and never auto-incremented. Only the root ontology
metadata changes in both root-subject serializations; scientific entity
declarations are preserved. The legacy KB alias is not a release load input.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

BASE = "https://rubalkhali.science/kb/"
MODULES = (
    "rubalkhali_controls.ttl", "rubalkhali_dna.owl", "rubalkhali_measurements.owl",
    "rubalkhali_ph_eq_ph_shared_v1_0_0.ttl", "rubalkhali_qc.owl",
    "rubalkhali_samples.owl", "rubalkhali_sites.owl", "rubalkhali_sra.owl",
    "rubalkhali_taxonomy_abox.ttl", "rubalkhali_xrf.owl", "ecosystem_module.ttl",
)


def stamp(source: str, version: str, released_at: str = "2026-09-10T00:00:00Z", previous_version: str = "v2.0.6") -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Use an explicit numeric MAJOR.MINOR.PATCH version")
    pattern = re.compile(r'(<owl:Ontology rdf:about="' + re.escape(BASE) + r'">)(.*?)(</owl:Ontology>)', re.S)
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise ValueError("Expected exactly one explicit root ontology header")
    match = matches[0]
    body = match[2]
    body = re.sub(r'\s*<owl:versionIRI\b[^>]*/>', '', body)
    body = re.sub(r'\s*<owl:versionInfo\b[^>]*>.*?</owl:versionInfo>', '', body, flags=re.S)
    body = re.sub(r'\s*<owl:imports rdf:resource="' + re.escape(BASE) + r'[^"]+"\s*/>', '', body)
    # Retain the authoritative date/version-pinned external imports and other
    # ontology annotations; replace only release identity and module catalogue.
    lines = [f'\n        <owl:versionIRI rdf:resource="{BASE}v{version}/"/>',
             f'\n        <owl:versionInfo>{version}</owl:versionInfo>']
    lines.append(body.rstrip())
    lines.extend(f'\n        <owl:imports rdf:resource="{BASE}{name}"/>' for name in MODULES)
    replacement = match[1] + ''.join(lines) + '\n    ' + match[3]
    result = source[:match.start()] + replacement + source[match.end():]
    # OWLAPI serialized root annotations separately as rdf:Description.
    # Updating only owl:Ontology leaves contradictory current version values.
    description = re.compile(r'(<rdf:Description rdf:about="' + re.escape(BASE) + r'">)(.*?)(</rdf:Description>)', re.S)
    if len(list(description.finditer(result))) != 1:
        raise ValueError("Expected one root rdf:Description metadata block")
    def normalize_description(block):
        body = block[2]
        for tag in ("pav:version", "pav:previousVersion", "owl:versionInfo", "terms1:modified"):
            body = re.sub(r'\s*<' + tag + r'\b[^>]*>.*?</' + tag + r'>', '', body, flags=re.S)
        return (block[1] + body.rstrip()
                + f'\n        <terms1:modified>{released_at}</terms1:modified>'
                + f'\n        <pav:previousVersion>{previous_version}</pav:previousVersion>'
                + f'\n        <pav:version>v{version}</pav:version>\n    ' + block[3])
    return description.sub(normalize_description, result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--released-at", required=True, help="Explicit immutable UTC release timestamp")
    p.add_argument("--previous-version", required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    before = args.input.read_bytes()
    after = stamp(before.decode(), args.version, args.released_at, args.previous_version).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(after)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps({
        "scope": "root-subject metadata only across owl:Ontology and rdf:Description; scientific entity axioms unchanged",
        "version": args.version, "version_iri": BASE + "v" + args.version + "/",
        "released_at": args.released_at, "previous_version": args.previous_version,
        "source_path": str(args.input), "source_sha256": hashlib.sha256(before).hexdigest(),
        "output_path": str(args.output), "output_sha256": hashlib.sha256(after).hexdigest(),
        "scientific_module_imports": list(MODULES),
        "excluded_legacy_alias": "rubalkhali_kb.owl",
        "alias_reason": "Do not duplicate curated TBox axioms into the default asserted union.",
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
