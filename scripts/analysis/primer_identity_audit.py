#!/usr/bin/env python3
"""Count declared 16S primer sequences at the starts of raw FASTQ reads.

The command is intentionally streaming and stops after a declared number of
reads per file.  It can therefore be piped to ``python3 -`` on a data host
without copying raw FASTQ files.
"""

from __future__ import annotations

import argparse
import gzip
import re
from pathlib import Path
from typing import Iterator


PATTERNS = {
    "bakt_341f": re.compile(r"^CCTACGGG[ACGT]GGC[AT]GCAG"),
    # Klindworth et al. V3--V4 reverse primer, positions 785--805.
    "bakt_785r": re.compile(r"^GACTAC[ACT][ACG]GGGTATCTAATCC"),
    # Apprill et al. 806RB sequence recorded in the current project SOP.
    "apprill_806rb": re.compile(r"^GGACTAC[ACGT][ACG]GGGT[AT]TCTAAT"),
}


def fastq_sequences(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="ascii") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number % 4 == 2:
                yield line.rstrip().upper()


def audit_file(path: Path, limit: int) -> dict[str, int | str]:
    counts: dict[str, int | str] = {
        "file": path.name,
        "n_reads": 0,
        "starts_CCTAC": 0,
        "matches_bakt_341f": 0,
        "starts_GACTAC": 0,
        "matches_bakt_785r": 0,
        "starts_GGACTAC": 0,
        "matches_apprill_806rb": 0,
    }
    for sequence in fastq_sequences(path):
        counts["n_reads"] = int(counts["n_reads"]) + 1
        counts["starts_CCTAC"] = int(counts["starts_CCTAC"]) + int(
            sequence.startswith("CCTAC")
        )
        counts["starts_GACTAC"] = int(counts["starts_GACTAC"]) + int(
            sequence.startswith("GACTAC")
        )
        counts["starts_GGACTAC"] = int(counts["starts_GGACTAC"]) + int(
            sequence.startswith("GGACTAC")
        )
        for name, pattern in PATTERNS.items():
            key = f"matches_{name}"
            counts[key] = int(counts[key]) + int(bool(pattern.match(sequence)))
        if counts["n_reads"] == limit:
            break
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=10_000,
        help="maximum reads inspected per FASTQ (default: 10000)",
    )
    parser.add_argument("fastq", nargs="+", type=Path)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    return args


def main() -> None:
    args = parse_args()
    columns = [
        "file",
        "n_reads",
        "starts_CCTAC",
        "matches_bakt_341f",
        "starts_GACTAC",
        "matches_bakt_785r",
        "starts_GGACTAC",
        "matches_apprill_806rb",
    ]
    print("\t".join(columns))
    for path in args.fastq:
        result = audit_file(path, args.limit)
        print("\t".join(str(result[column]) for column in columns))


if __name__ == "__main__":
    main()
