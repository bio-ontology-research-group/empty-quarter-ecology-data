#!/usr/bin/env python3
"""Report which cited works are held locally and which are not.

A referee or co-author cannot audit a claim against a citation that nobody can
open.  This audit lists every key cited by the authoritative manuscript
sources, resolves each to a local full-text copy where one exists, and states
plainly which citations have no local custody.  It does not download anything
and does not guess: a key is either matched to a file on disk by DOI, by title
tokens, or it is reported as uncovered.

The report is the evidence for the source-custody requirement; it is not a
quality judgement about the cited work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

AUTHORITATIVE = (
    "sn-article.tex",
    "01_introduction.tex",
    "02_methods.tex",
    "02_methods_taxonomy.tex",
    "03_knowledge_representation.tex",
    "04_data_records.tex",
    "05_validation.tex",
    "06_usage.tex",
    "supplement.tex",
    "kr_supplement.tex",
    "env_table.tex",
    "xrf_table.tex",
)

CITE_RE = re.compile(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]*)\}")
ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,]+),")
FIELD_RE = re.compile(r"(\w+)\s*=\s*[{\"](.+?)[}\"]\s*,?\s*\n", re.S)
STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "in", "on", "to", "with", "from",
    "its", "their", "into", "across", "based", "using", "data", "study",
}


def relative_to_project(path: Path, project_root: Path) -> str:
    """Repository-relative path, so evidence carries no machine-specific root."""
    try:
        return str(Path(path).resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_bib(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: dict[str, dict[str, str]] = {}
    positions = [(match.start(), match.group(2).strip()) for match in ENTRY_RE.finditer(text)]
    for index, (start, key) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        body = text[start:end]
        fields = {name.lower(): value.strip() for name, value in FIELD_RE.findall(body)}
        entries[key] = fields
    return entries


def title_tokens(title: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    return {token for token in cleaned.split() if len(token) > 3 and token not in STOPWORDS}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-root", type=Path, default=root)
    parser.add_argument(
        "--library",
        type=Path,
        action="append",
        default=None,
        help="directory holding local full-text copies (repeatable)",
    )
    parser.add_argument(
        "--output", type=Path, default=root / "zenodo/evidence/bibliography/source_custody.json"
    )
    args = parser.parse_args()

    libraries = args.library or [
        args.paper_root / "resource",
        args.paper_root.parent / "review-literature",
    ]
    libraries = [path for path in libraries if path.is_dir()]

    bib = args.paper_root / "sn-bibliography.bib"
    if not bib.is_file():
        print(f"FAIL: bibliography is absent: {bib}", file=sys.stderr)
        return 1
    entries = parse_bib(bib)

    cited: dict[str, list[str]] = {}
    for name in AUTHORITATIVE:
        source = args.paper_root / name
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in CITE_RE.finditer(text):
            for key in match.group(1).split(","):
                key = key.strip()
                if key:
                    cited.setdefault(key, []).append(name)

    corpus = []
    for library in libraries:
        for path in library.rglob("*"):
            if path.suffix.lower() in {".pdf", ".txt", ".xml", ".html"} and path.is_file():
                corpus.append(path)

    corpus_text: dict[Path, str] = {}
    for path in corpus:
        if path.suffix.lower() == ".pdf":
            corpus_text[path] = path.name.lower()
        else:
            try:
                # Match the source header, not arbitrary bibliography entries
                # deep in another manuscript or review report.
                corpus_text[path] = (
                    path.name
                    + " "
                    + path.read_text(encoding="utf-8", errors="replace")[:4000]
                ).lower()
            except OSError:
                corpus_text[path] = path.name.lower()

    records = []
    for key in sorted(cited):
        fields = entries.get(key, {})
        doi = (fields.get("doi") or "").lower().strip()
        title = fields.get("title", "")
        tokens = title_tokens(title)
        matches: list[str] = []
        for path, text in corpus_text.items():
            name_tokens = title_tokens(path.name)
            title_overlap = (
                len(tokens & title_tokens(text)) / len(tokens)
                if tokens
                else 0.0
            )
            filename_overlap = (
                len(tokens & name_tokens) / len(tokens)
                if tokens
                else 0.0
            )
            doi_in_header = doi and doi in text
            doi_in_filename = doi and doi in path.name.lower()
            if doi_in_filename or (
                doi_in_header and (filename_overlap >= 0.4 or title_overlap >= 0.75)
            ):
                matches.append(str(path))
                continue
            if tokens and title_overlap >= 0.75 and len(tokens & title_tokens(text)) >= 3:
                matches.append(str(path))
        records.append(
            {
                "key": key,
                "in_bibliography": key in entries,
                "cited_in": sorted(set(cited[key])),
                "title": title,
                "doi": fields.get("doi", ""),
                "local_copies": sorted(
                    {relative_to_project(Path(match), args.paper_root.parent) for match in matches}
                ),
                "custody": "local" if matches else "no_local_copy",
            }
        )

    missing_keys = [record["key"] for record in records if not record["in_bibliography"]]
    uncovered = [record["key"] for record in records if record["custody"] == "no_local_copy"]

    report = {
        "bibliography": relative_to_project(bib, args.paper_root.parent),
        "bibliography_sha256": sha256(bib),
        "bibliography_entries": len(entries),
        "cited_keys": len(records),
        "keys_missing_from_bibliography": missing_keys,
        "keys_without_local_copy": uncovered,
        "libraries_searched": [
            relative_to_project(path, args.paper_root.parent) for path in libraries
        ],
        "records": records,
        "note": (
            "Matching is by DOI plus title context or strong title-token overlap "
            "against PDF filenames and the first 4,000 characters of text files; "
            "bibliography mentions deep in unrelated files are not matches. A "
            "key reported as covered is not "
            "a guarantee that the local copy is the exact cited version; where a "
            "preprint and a final version differ, the archived copy should be "
            "checked against the bibliography entry before submission."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"cited keys: {len(records)}; bibliography entries: {len(entries)}")
    print(f"keys missing from bibliography: {len(missing_keys)} {missing_keys}")
    print(f"keys without a local copy: {len(uncovered)}")
    print(f"report -> {args.output}")
    return 1 if missing_keys else 0


if __name__ == "__main__":
    sys.exit(main())
