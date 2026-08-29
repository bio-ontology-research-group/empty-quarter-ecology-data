#!/usr/bin/env python3
"""Generate the supplementary XRF mapping table from an audited ledger.

Required TSV columns:
  analyte, formula, entity_type, chebi, chebi_label, pubchem,
  pubchem_label, status, evidence_url, reviewed_by, reviewed_date, notes

Only rows with status ``verified`` are emitted.  LE must be explicitly
classified as an instrument pseudo-analyte or mixture and must not carry a
ChEBI or PubChem compound identifier.  This fail-closed design prevents the
previous hard-coded, shifted identifier table from silently reappearing in the
manuscript.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

REQUIRED = {
    "analyte",
    "formula",
    "entity_type",
    "chebi",
    "chebi_label",
    "pubchem",
    "pubchem_label",
    "status",
    "evidence_url",
    "reviewed_by",
    "reviewed_date",
    "notes",
}


def latex_escape(value: str) -> str:
    for old, new in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("_", r"\_"),
        ("#", r"\#"),
    ):
        value = value.replace(old, new)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("xrf_table.tex"))
    args = parser.parse_args()

    with args.ledger.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = REQUIRED.difference(reader.fieldnames or ())
        if missing:
            parser.error("ledger missing column(s): " + ", ".join(sorted(missing)))
        rows = list(reader)

    failures: list[str] = []
    for row in rows:
        analyte = row["analyte"].strip()
        if row["status"].strip().casefold() != "verified":
            failures.append(f"{analyte}: status is not verified")
        if not row["reviewed_by"].strip() or not row["reviewed_date"].strip():
            failures.append(f"{analyte}: missing reviewer/date")
        if analyte == "LE":
            if row["chebi"].strip() or row["pubchem"].strip():
                failures.append("LE: pseudo-analyte must not map to a compound")
            if row["entity_type"].strip().casefold() not in {
                "mixture",
                "pseudo-analyte",
                "instrument_pseudoanalyte",
            }:
                failures.append(
                    "LE: entity_type must be mixture or instrument pseudo-analyte"
                )
        elif not row["chebi"].strip() and not row["pubchem"].strip():
            if "no formula-matching external identifier" not in row[
                "notes"
            ].casefold():
                failures.append(
                    f"{analyte}: no accepted identifier and no audited null disposition"
                )
        if (row["chebi"].strip() or row["pubchem"].strip()) and not row[
            "evidence_url"
        ].strip():
            failures.append(f"{analyte}: missing authoritative evidence URL")

    if failures:
        parser.error("ledger is not release-ready:\n  " + "\n  ".join(failures))

    output = [
        r"\begin{longtable}{llll}",
        (
            r"\caption{Audited XRF reporting-channel cross-references. "
            r"Labels, formulas, charge and entity types were checked against "
            r"pinned ChEBI and PubChem records.} "
            r"\label{tab:chebi_mapping} \\"
        ),
        r"\toprule",
        r"Analyte & Formula/type & ChEBI & PubChem \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"Analyte & Formula/type & ChEBI & PubChem \\",
        r"\midrule",
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]
    for row in sorted(rows, key=lambda item: item["analyte"]):
        formula_or_type = row["formula"] or row["entity_type"]
        output.append(
            "{} & {} & {} & {} \\\\".format(
                latex_escape(row["analyte"]),
                latex_escape(formula_or_type),
                latex_escape(row["chebi"] or "--"),
                latex_escape(row["pubchem"] or "--"),
            )
        )
    output.append(r"\end{longtable}")
    output.extend(
        [
            r"\noindent\textit{Interpretation.} A dash denotes an audited null, "
            r"not a missing review. These \texttt{rdfs:seeAlso} cross-references "
            r"identify the element or oxide-equivalent reporting channel; they "
            r"do not assert that the corresponding molecule or mineral occurs "
            r"in a sample. The P$_2$O$_5$ channel is cross-referenced to the "
            r"ChEBI P$_4$O$_{10}$ class only because the formulas share the P:O empirical "
            r"ratio. LE is an instrument aggregate, and PrO$_2$ has no "
            r"formula-matching external identifier in the audited sources.",
        ]
    )
    args.output.write_text("\n".join(output) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
