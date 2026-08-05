#!/usr/bin/env python3
"""Midpoint-root a Newick tree deterministically with scikit-bio."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from skbio import TreeNode


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tree = TreeNode.read(args.input)
    before = sum(1 for _ in tree.tips())
    if before < 2:
        raise ValueError(f"Cannot midpoint-root a tree with {before} tip(s)")
    rooted = tree.root_at_midpoint()
    after = sum(1 for _ in rooted.tips())
    if before != after:
        raise ValueError(
            f"Midpoint rooting changed the tip count: {before} -> {after}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rooted.write(args.output)
    print(
        f"PASS: midpoint-rooted {before} tips; "
        f"sha256={sha256(args.output)}"
    )


if __name__ == "__main__":
    main()
