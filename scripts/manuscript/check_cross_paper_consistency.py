#!/usr/bin/env python3
"""Check the data descriptor and the companion ecology paper against each other.

A referee will read both manuscripts. Anything that disagrees between them --- a
primer, a denominator, a compartment name, a companion citation that resolves
nowhere --- costs more credibility than the same error in one paper alone.
This script compares the two sources on the items that must agree and reports
every contradiction it finds.

The ecology manuscript is read only. Contradictions located there are reported
with their file and line so the ecology author can fix them; this script never
edits it.

Exit status is 0 when no contradiction is found, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATA_SOURCES = (
    "01_introduction.tex",
    "02_methods.tex",
    "02_methods_taxonomy.tex",
    "03_knowledge_representation.tex",
    "04_data_records.tex",
    "05_validation.tex",
    "06_usage.tex",
    "sn-article.tex",
    "kr_supplement.tex",
)
ECOLOGY_SOURCES = ("main.tex", "supplement.tex")

# Strings that must not appear as a current statement in either manuscript.
PROHIBITED = (
    (r"806RB?\b", "retired reverse primer 806R/806RB"),
    (r"GGACTACNVGGGTWTCTAAT", "retired 806RB primer sequence"),
    (r"\bApprill\b", "retired Apprill primer citation"),
    (
        r"compartment\s+and\s+genomic-potential\s+structure",
        "retired ecology companion title",
    ),
    (
        r"no control-sample community records",
        "false claim: 24 control profiles are in the canonical feature table",
    ),
    (
        r"no contamination assessment has been performed",
        "false claim: a preliminary prevalence screen is distributed",
    ),
)
# A retired term may be named while it is being retired. A hit is excused when
# the surrounding lines mark it as superseded rather than asserted.
SUPERSESSION_CONTEXT = re.compile(
    r"(supersed|previously|correction|rejects|no longer|retired|instead of)", re.IGNORECASE
)
CONTEXT_WINDOW = 6
# Strings that must appear somewhere in each manuscript.
REQUIRED_BOTH = (
    (r"Bakt.{0,2}785R", "corrected reverse primer name"),
    (r"GACTACHVGGGTATCTAATCC", "corrected reverse primer sequence"),
)
# Denominators that must agree wherever they appear in both manuscripts.
SHARED_COUNTS = (
    (r"1,271", "canonical feature profiles"),
    (r"1,237", "ecology profiles"),
    (r"1,227", "primary-frame profiles"),
    (r"351,472", "ASVs"),
    (r"725", "laboratory XRF records"),
    (r"547", "Trips 1-4 laboratory XRF records"),
    (r"178", "Trip 5 laboratory XRF records"),
    (r"150", "CoverM profiles"),
    (r"990", "matched genomes"),
)
TERMINOLOGY = (
    (
        r"\b64 sites\b",
        "'64 sites' should be '64 numeric site labels': four are Trip-1-only aliases",
    ),
    (
        r"(?<!``)Deep Soil Sample(?!'')",
        "'Deep Soil Sample' should appear only as a quoted historical graph label",
    ),
)


def load(root: Path, names: tuple[str, ...]) -> dict[str, list[str]]:
    documents = {}
    for name in names:
        path = root / name
        if path.is_file():
            documents[name] = path.read_text(encoding="utf-8", errors="replace").split("\n")
    return documents


def scan(
    documents: dict[str, list[str]],
    pattern: str,
    excuse_supersession: bool = False,
    skip_listings: bool = False,
) -> list[tuple[str, int, str]]:
    compiled = re.compile(pattern)
    hits = []
    for name, lines in documents.items():
        in_listing = False
        for number, line in enumerate(lines, start=1):
            if skip_listings:
                if line.startswith("\\begin{lstlisting}"):
                    in_listing = True
                    continue
                if line.startswith("\\end{lstlisting}"):
                    in_listing = False
                    continue
                if in_listing:
                    continue
            if line.lstrip().startswith("%"):
                continue
            if not compiled.search(line):
                continue
            if excuse_supersession:
                window = "\n".join(
                    lines[max(0, number - 1 - CONTEXT_WINDOW) : number + CONTEXT_WINDOW]
                )
                if SUPERSESSION_CONTEXT.search(window):
                    continue
            hits.append((name, number, line.strip()))
    return hits


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=root)
    parser.add_argument(
        "--ecology-root",
        type=Path,
        default=Path("/home/leechuck/Documents/papers/empty-quarter-amplicon"),
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    data = load(args.data_root, DATA_SOURCES)
    if not data:
        print(f"FAIL: no data-paper sources under {args.data_root}", file=sys.stderr)
        return 1
    ecology = load(args.ecology_root, ECOLOGY_SOURCES)

    findings: list[dict] = []

    expected_ecology_title = (
        "Landscape-scale bacterial biogeography across the Rub' al-Khali "
        "reveals recurring spatial and soil-position structure"
    )
    ecology_flat = re.sub(
        r"\s+",
        " ",
        " ".join(
            line
            for lines in ecology.values()
            for line in lines
        ),
    )
    bibliography_path = args.data_root / "sn-bibliography.bib"
    bibliography_flat = (
        re.sub(
            r"\s+",
            " ",
            bibliography_path.read_text(
                encoding="utf-8", errors="replace"
            ),
        )
        if bibliography_path.is_file()
        else ""
    )
    bibliography_title = expected_ecology_title.replace(
        "Rub' al-Khali", "{Rub' al-Khali}"
    )
    if ecology and expected_ecology_title not in ecology_flat:
        findings.append(
            {
                "kind": "title",
                "manuscript": "ecology",
                "file": "main.tex/supplement.tex",
                "line": 0,
                "what": "current ecology title is absent",
                "text": "",
            }
        )
    if bibliography_title not in bibliography_flat:
        findings.append(
            {
                "kind": "title",
                "manuscript": "data-paper",
                "file": "sn-bibliography.bib",
                "line": 0,
                "what": "companion bibliography title is stale or absent",
                "text": "",
            }
        )

    for pattern, description in PROHIBITED:
        for label, documents in (("data-paper", data), ("ecology", ecology)):
            for name, number, line in scan(documents, pattern, excuse_supersession=True):
                findings.append(
                    {
                        "kind": "prohibited",
                        "manuscript": label,
                        "file": name,
                        "line": number,
                        "what": description,
                        "text": line[:160],
                    }
                )

    for pattern, description in REQUIRED_BOTH:
        for label, documents in (("data-paper", data), ("ecology", ecology)):
            if not documents:
                continue
            if not scan(documents, pattern):
                findings.append(
                    {
                        "kind": "missing",
                        "manuscript": label,
                        "file": "",
                        "line": 0,
                        "what": f"{description} is absent",
                        "text": "",
                    }
                )

    for pattern, description in TERMINOLOGY:
        for label, documents in (("data-paper", data), ("ecology", ecology)):
            for name, number, line in scan(documents, pattern, skip_listings=True):
                findings.append(
                    {
                        "kind": "terminology",
                        "manuscript": label,
                        "file": name,
                        "line": number,
                        "what": description,
                        "text": line[:160],
                    }
                )

    shared = []
    for pattern, description in SHARED_COUNTS:
        in_data = bool(scan(data, pattern))
        in_ecology = bool(scan(ecology, pattern)) if ecology else None
        shared.append(
            {"count": pattern, "meaning": description, "in_data_paper": in_data, "in_ecology": in_ecology}
        )

    companion = {
        "data_paper_cites_ecology": bool(scan(data, r"\\cite\{[^}]*ecology_companion")),
        "ecology_cites_data_paper": bool(scan(ecology, r"\\cite\{[^}]*rubalkhali_datapaper"))
        if ecology
        else None,
        "note": (
            "Both companion bibliography entries need a resolvable identifier "
            "(preprint or DOI) before either manuscript is submitted; a circular "
            "citation with no identifier is a common desk-reject trigger."
        ),
    }

    report = {
        "data_paper_sources": sorted(data),
        "ecology_sources": sorted(ecology),
        "ecology_readable": bool(ecology),
        "findings": findings,
        "shared_counts": shared,
        "companion_citations": companion,
        "status": "failed" if findings else "passed",
    }
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for finding in findings:
        print(
            f"{finding['manuscript']:11s} {finding['kind']:12s} "
            f"{finding['file']}:{finding['line']}  {finding['what']}"
        )
    if not ecology:
        print(f"NOTE: ecology manuscript not readable at {args.ecology_root}")
    print(f"{len(findings)} cross-paper finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
