#!/usr/bin/env python3
"""Validate generated pdfTeX files and emit deterministic metadata.

This intentionally uses only the Python standard library so the paper-build
process does not depend on a host installation of Poppler's ``pdfinfo``.
The generated manuscripts are ordinary, unencrypted pdfTeX files with page
objects and MediaBox declarations in the top-level byte stream.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

PDFTEX_METADATA = re.compile(
    r"PDF_META\s*pages=(\d+)\s*width=([0-9.]+)pt\s*"
    r"height=([0-9.]+)pt\s*depth=([0-9.]+)pt"
)


def pdftex_metadata(path: Path) -> tuple[int, str]:
    source = rf"""
\edef\pdffile{{\detokenize{{{path.resolve()}}}}}
\pdfximage page 1 {{\pdffile}}
\edef\pdfpagecount{{\the\pdflastximagepages}}
\setbox0=\hbox{{\pdfrefximage\pdflastximage}}
\immediate\write16{{PDF_META pages=\pdfpagecount width=\the\wd0 height=\the\ht0 depth=\the\dp0}}
\bye
"""
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / "metadata.tex"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [
                "pdftex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                source_path.name,
            ],
            text=True,
            capture_output=True,
            cwd=directory,
            check=False,
        )
        log_path = Path(directory) / "texput.log"
        log = log_path.read_text(errors="replace") if log_path.exists() else ""
    if result.returncode:
        raise ValueError(
            f"{path}: pdfTeX could not read the generated PDF\n"
            f"{result.stdout}\n{result.stderr}\n{log}"
        )
    match = PDFTEX_METADATA.search(result.stdout + "\n" + log)
    if match is None:
        raise ValueError(
            f"{path}: pdfTeX did not report page metadata\n"
            f"{result.stdout}\n{result.stderr}\n{log}"
        )
    pages = int(match.group(1))
    if pages < 1:
        raise ValueError(f"{path}: no pages found")
    width = float(match.group(2))
    height = float(match.group(3)) + float(match.group(4))
    if width <= 0 or height <= 0:
        raise ValueError(f"{path}: invalid first-page dimensions")
    page_size = f"{width:.3f}x{height:.3f}"
    return pages, page_size


def inspect(path: Path) -> tuple[str, int, int, str, str]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"{path}: missing PDF header")
    if b"%%EOF" not in data[-2048:]:
        raise ValueError(f"{path}: missing terminal PDF marker")
    if b"/Encrypt" in data:
        raise ValueError(f"{path}: encrypted PDFs are not accepted")

    pages, page_size = pdftex_metadata(path)
    version = data[5 : data.find(b"\n", 5)].decode("ascii", errors="strict")
    digest = hashlib.sha256(data).hexdigest()
    return version, pages, len(data), page_size, digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path, nargs="+")
    args = parser.parse_args()

    print("path\tpdf_version\tpages\tbytes\tfirst_page_tex_points\tsha256")
    for path in args.pdf:
        version, pages, size, box, digest = inspect(path)
        print(f"{path}\t{version}\t{pages}\t{size}\t{box}\t{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
