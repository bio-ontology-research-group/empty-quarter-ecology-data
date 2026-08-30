#!/usr/bin/env python3
"""Curate field environmental metadata and render the supplementary table.

Raw expedition sheets are immutable inputs.  Every changed or quarantined
measurement must be declared in the tab-separated correction ledger.  The
script verifies the raw cell before applying a ledger row, rejects
out-of-range curated measurements, and writes both a machine-readable table
and an audit report alongside the LaTeX table.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


TRIP_FILES = (
    "trip1-2023.tsv",
    "trip2-2023.tsv",
    "trip3-2024.tsv",
    "trip4-2024.tsv",
    "trip5-2025.tsv",
)
TRIP_LABELS = {
    "trip1-2023.tsv": "Trip 1 (2023)",
    "trip2-2023.tsv": "Trip 2 (2023)",
    "trip3-2024.tsv": "Trip 3 (2024)",
    "trip4-2024.tsv": "Trip 4 (2024)",
    "trip5-2025.tsv": "Trip 5 (2025)",
}
EXPECTED_ROLE_COUNTS = {
    "trip1-2023.tsv": {
        "primary_transect_site": 60,
        "named_special_record": 4,
    },
    "trip2-2023.tsv": {"primary_transect_site": 8},
    "trip3-2024.tsv": {
        "primary_transect_site": 60,
        "named_special_record": 5,
        "trip1_auxiliary_or_revisit_record": 15,
    },
    "trip4-2024.tsv": {"primary_transect_site": 60},
    "trip5-2025.tsv": {
        "primary_transect_site": 60,
        "named_special_record": 2,
    },
}
MEASUREMENT_FIELDS = ("temperature", "pressure", "humidity")
CORRECTABLE_FIELDS = MEASUREMENT_FIELDS + ("date",)
RANGES = {
    "temperature": (-50.0, 60.0),
    "pressure": (800.0, 1100.0),
    "humidity": (0.0, 100.0),
}
CORRECTION_COLUMNS = (
    "source_file",
    "source_row",
    "site",
    "original_field",
    "original_value",
    "corrected_field",
    "corrected_value",
    "status",
    "rationale",
)
CURATED_COLUMNS = (
    "expedition",
    "source_file",
    "source_row",
    "record_role",
    "site",
    "date",
    "time",
    "coordinates",
    "temperature_c",
    "pressure_mbar",
    "relative_humidity_pct",
    "qc_status",
    "qc_action",
    "notes",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_cell(value: str | None) -> str:
    return "" if value is None else value.strip()


def parse_coordinates(value: str) -> str:
    if not value:
        return ""
    parts = value.split(",")
    if len(parts) != 2:
        raise ValueError(f"cannot parse coordinates: {value!r}")
    try:
        latitude = float(parts[0].strip().split()[0].replace("°", ""))
        longitude = float(parts[1].strip().split()[0].replace("°", ""))
    except (IndexError, ValueError) as error:
        raise ValueError(f"cannot parse coordinates: {value!r}") from error
    return f"{latitude:.4f} N, {longitude:.4f} E"


def read_corrections(path: Path) -> dict[tuple[str, int, str], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != CORRECTION_COLUMNS:
            raise ValueError(
                f"{path}: correction columns must be {CORRECTION_COLUMNS}"
            )
        corrections: dict[tuple[str, int, str], dict[str, str]] = {}
        for row in reader:
            cleaned = {key: normalize_cell(value) for key, value in row.items()}
            try:
                source_row = int(cleaned["source_row"])
            except ValueError as error:
                raise ValueError(
                    f"{path}: invalid source_row {cleaned['source_row']!r}"
                ) from error
            key = (
                cleaned["source_file"],
                source_row,
                cleaned["original_field"],
            )
            if key in corrections:
                raise ValueError(f"{path}: duplicate correction key {key}")
            if cleaned["original_field"] not in CORRECTABLE_FIELDS:
                raise ValueError(f"{path}: unsupported original field in {key}")
            if cleaned["corrected_field"] not in CORRECTABLE_FIELDS:
                raise ValueError(f"{path}: unsupported corrected field in {key}")
            if not (
                cleaned["status"].startswith("confirmed_")
                or cleaned["status"].startswith("quarantined_")
            ):
                raise ValueError(f"{path}: unsupported status in {key}")
            if not cleaned["rationale"]:
                raise ValueError(f"{path}: correction lacks rationale in {key}")
            corrections[key] = cleaned
    return corrections


def record_role(source_file: str, site: str, date: str) -> str:
    if re.fullmatch(r"\d+", site):
        site_number = int(site)
        if 1 <= site_number <= 60:
            return "primary_transect_site"
        if source_file == "trip1-2023.tsv" and 61 <= site_number <= 64:
            return "trip1_only_nonrevisited_site"
        return "numeric_site_outside_declared_frame"
    if source_file == "trip3-2024.tsv":
        try:
            parsed_date = datetime.strptime(date, "%d/%m/%Y")
        except ValueError as error:
            raise ValueError(
                f"{source_file}: cannot classify dated record {site!r}, {date!r}"
            ) from error
        if parsed_date.year == 2023:
            return "trip1_auxiliary_or_revisit_record"
    return "named_special_record"


def expedition_label(source_file: str, role: str) -> str:
    if role == "trip1_auxiliary_or_revisit_record":
        return "Trip 1 auxiliary/revisit (2023)"
    return TRIP_LABELS[source_file]


def raw_rows(path: Path) -> Iterable[tuple[int, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = [normalize_cell(item).lower() for item in next(reader)]
        except StopIteration:
            return
        if not {"site", "date", "time", "coordinates"}.issubset(header):
            raise ValueError(f"{path}: incomplete header {header}")
        for source_row, values in enumerate(reader, start=2):
            if not any(normalize_cell(value) for value in values):
                continue
            if len(values) < len(header):
                values += [""] * (len(header) - len(values))
            elif len(values) > len(header):
                # Some field sheets contain an extra tab before the note.  It
                # affects only the final free-text column; retain all text.
                values = values[: len(header) - 1] + [
                    "\t".join(values[len(header) - 1 :]).strip()
                ]
            yield source_row, {
                key: normalize_cell(value) for key, value in zip(header, values)
            }


def validate_measurement(field: str, value: str, context: str) -> None:
    if not value:
        return
    try:
        numeric = float(value)
    except ValueError as error:
        raise ValueError(f"{context}: non-numeric {field} {value!r}") from error
    lower, upper = RANGES[field]
    if not lower <= numeric <= upper:
        raise ValueError(
            f"{context}: {field} {value} outside [{lower}, {upper}]"
        )


def curate(
    project_root: Path,
) -> tuple[list[dict[str, str]], dict[str, object], list[dict[str, str]]]:
    sample_dir = project_root / "data/metadata/samplesheets"
    correction_path = (
        project_root
        / "data/metadata/samples/environmental_measurement_corrections.tsv"
    )
    corrections = read_corrections(correction_path)
    used_corrections: set[tuple[str, int, str]] = set()
    curated: list[dict[str, str]] = []
    source_audit: list[dict[str, object]] = []
    role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    measurement_counts: dict[str, Counter[str]] = defaultdict(Counter)
    status_counts: Counter[str] = Counter()
    applied_rows: list[dict[str, str]] = []

    for source_file in TRIP_FILES:
        path = sample_dir / source_file
        file_rows = 0
        for source_row, row in raw_rows(path):
            file_rows += 1
            site = row.get("site", "")
            if not site:
                raise ValueError(f"{source_file}:{source_row}: site is empty")
            values = {
                field: row.get(field, "") for field in MEASUREMENT_FIELDS
            }
            values["date"] = row.get("date", "")
            row_actions: list[str] = []
            for original_field in CORRECTABLE_FIELDS:
                key = (source_file, source_row, original_field)
                correction = corrections.get(key)
                if correction is None:
                    continue
                if correction["site"] != site:
                    raise ValueError(
                        f"{key}: ledger site {correction['site']!r} does not "
                        f"match source site {site!r}"
                    )
                if values[original_field] != correction["original_value"]:
                    raise ValueError(
                        f"{key}: ledger raw value "
                        f"{correction['original_value']!r} does not match "
                        f"{values[original_field]!r}"
                    )
                corrected_field = correction["corrected_field"]
                if (
                    corrected_field != original_field
                    and values[corrected_field]
                    and values[corrected_field]
                    != correction["corrected_value"]
                ):
                    raise ValueError(
                        f"{key}: corrected field {corrected_field} is already "
                        f"populated with {values[corrected_field]!r}"
                    )
                values[original_field] = ""
                values[corrected_field] = correction["corrected_value"]
                used_corrections.add(key)
                row_actions.append(
                    f"{correction['status']}:"
                    f"{original_field}->{corrected_field}"
                )
                applied_rows.append(correction)

            context = f"{source_file}:{source_row} site {site}"
            for field in MEASUREMENT_FIELDS:
                value = values[field]
                validate_measurement(field, value, context)
                if value:
                    measurement_counts[source_file][field] += 1

            role = record_role(source_file, site, values["date"])
            role_counts[source_file][role] += 1
            status = (
                ",".join(sorted({item.split(":", 1)[0] for item in row_actions}))
                if row_actions
                else "source_as_recorded"
            )
            status_counts.update([status])
            curated.append(
                {
                    "expedition": expedition_label(source_file, role),
                    "source_file": source_file,
                    "source_row": str(source_row),
                    "record_role": role,
                    "site": site,
                    "date": values["date"],
                    "time": row.get("time", ""),
                    "coordinates": row.get("coordinates", ""),
                    "temperature_c": values["temperature"],
                    "pressure_mbar": values["pressure"],
                    "relative_humidity_pct": values["humidity"],
                    "qc_status": status,
                    "qc_action": ";".join(row_actions),
                    "notes": row.get("notes", ""),
                }
            )

        actual_roles = dict(sorted(role_counts[source_file].items()))
        if actual_roles != EXPECTED_ROLE_COUNTS[source_file]:
            raise ValueError(
                f"{source_file}: record-role counts {actual_roles} do not "
                f"match expected {EXPECTED_ROLE_COUNTS[source_file]}"
            )
        source_audit.append(
            {
                "path": str(path.relative_to(project_root)),
                "sha256": sha256(path),
                "nonblank_records": file_rows,
                "record_roles": actual_roles,
                "measurements_retained": dict(
                    sorted(measurement_counts[source_file].items())
                ),
            }
        )

    unused = sorted(set(corrections) - used_corrections)
    if unused:
        raise ValueError(f"unused correction-ledger entries: {unused}")

    trip3_site21 = [
        row
        for row in curated
        if row["source_file"] == "trip3-2024.tsv" and row["site"] == "21"
    ]
    if len(trip3_site21) != 1:
        raise ValueError("Trip 3 site 21 is not uniquely represented")
    if trip3_site21[0]["relative_humidity_pct"] != "31.321":
        raise ValueError("Trip 3 site 21 humidity changed from 31.321%")

    trip3_dates = [
        datetime.strptime(row["date"], "%d/%m/%Y").date()
        for row in curated
        if row["expedition"] == "Trip 3 (2024)"
    ]
    if (
        len(trip3_dates) != 65
        or min(trip3_dates).isoformat() != "2024-02-17"
        or max(trip3_dates).isoformat() != "2024-02-21"
    ):
        raise ValueError(
            "Trip 3 must contain 65 February 2024 records ending 2024-02-21"
        )
    trip1_auxiliary_dates = [
        datetime.strptime(row["date"], "%d/%m/%Y").date()
        for row in curated
        if row["record_role"] == "trip1_auxiliary_or_revisit_record"
    ]
    if (
        len(trip1_auxiliary_dates) != 15
        or min(trip1_auxiliary_dates).isoformat() != "2023-03-17"
        or max(trip1_auxiliary_dates).isoformat() != "2023-03-20"
    ):
        raise ValueError(
            "The 15 legacy-sheet auxiliary records must remain in Trip 1"
        )

    audit: dict[str, object] = {
        "status": "passed",
        "method": (
            "Raw field sheets are retained unchanged; exact-cell correction "
            "ledger entries are verified before use; curated temperature, "
            "pressure and relative-humidity values must pass declared ranges."
        ),
        "correction_ledger": {
            "path": str(correction_path.relative_to(project_root)),
            "sha256": sha256(correction_path),
            "entries": len(corrections),
            "applied": len(used_corrections),
            "status_counts": dict(
                sorted(Counter(row["status"] for row in applied_rows).items())
            ),
        },
        "range_checks": {
            field: {"minimum": limits[0], "maximum": limits[1]}
            for field, limits in RANGES.items()
        },
        "source_files": source_audit,
        "curated_records": len(curated),
        "row_qc_status_counts": dict(sorted(status_counts.items())),
        "trip3_site21_humidity_pct": "31.321",
        "trip3_site21_primary_source_corroboration": (
            "data/metadata/obsolete/Trip_Metadata.xlsx stores 0.31321; "
            "the current percent representation is therefore 31.321."
        ),
        "campaign_date_audit": {
            "trip3_records": len(trip3_dates),
            "trip3_start": min(trip3_dates).isoformat(),
            "trip3_end": max(trip3_dates).isoformat(),
            "trip1_auxiliary_records_from_legacy_trip3_sheet": len(
                trip1_auxiliary_dates
            ),
            "trip1_auxiliary_start": min(trip1_auxiliary_dates).isoformat(),
            "trip1_auxiliary_end": max(trip1_auxiliary_dates).isoformat(),
            "evidence": (
                "Trip_Metadata.xlsx sheet Trip3 rows 67--81 records March "
                "2023; commit ffc330ee changed only the year to 2024."
            ),
        },
    }
    return curated, audit, applied_rows


def render_curated_tsv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=CURATED_COLUMNS,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def display(value: str) -> str:
    return latex_escape(value) if value else r"\textemdash{}"


def render_latex(
    rows: list[dict[str, str]], applied_rows: list[dict[str, str]]
) -> str:
    lines = [
        r"\begin{scriptsize}",
        r"\setlength{\LTleft}{-\landexcess}",
        r"\setlength{\LTright}{0pt plus 1fill}",
        r"\begin{longtable}{llllllll}",
        (
            r"\caption{Site-specific field environmental observations across "
            r"all expeditions. Values are generated from the immutable source "
            r"sheets and the versioned correction ledger; a dash denotes an "
            r"unrecorded or quarantined value. Altitude was not recorded in "
            r"these field sheets.} \label{tab:env_data} \\"
        ),
        r"\toprule",
        (
            r"Expedition & Site & Date & Time & Coordinates & "
            r"Temp. (\degree C) & Press. (mbar) & RH (\%) \\"
        ),
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        (
            r"Expedition & Site & Date & Time & Coordinates & "
            r"Temp. (\degree C) & Press. (mbar) & RH (\%) \\"
        ),
        r"\midrule",
        r"\endhead",
        r"\midrule",
        r"\multicolumn{8}{r}{Continued on next page} \\",
        r"\bottomrule",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
    ]
    for row in rows:
        table_row = (
            row["expedition"],
            row["site"],
            row["date"],
            row["time"],
            parse_coordinates(row["coordinates"]),
            row["temperature_c"],
            row["pressure_mbar"],
            row["relative_humidity_pct"],
        )
        lines.append(" & ".join(display(item) for item in table_row) + r" \\")
    lines.append(r"\end{longtable}")

    site40 = next(
        row
        for row in applied_rows
        if row["source_file"] == "trip5-2025.tsv"
        and row["site"] == "40"
        and row["original_field"] == "humidity"
    )
    if site40["status"].startswith("quarantined_"):
        site40_note = (
            r"Trip~5 site~40 contains the source value 194\% RH, which is "
            r"outside the physical range. Because no primary source currently "
            r"establishes a decimal correction, the curated value is missing; "
            r"194 is preserved in the correction ledger."
        )
    else:
        site40_note = (
            r"Trip~5 site~40 RH was corrected from 194 to "
            + latex_escape(site40["corrected_value"])
            + r"\% using the evidence recorded in the correction ledger."
        )
    lines.extend(
        [
            r"\noindent\textit{Metadata QC.} "
            r"For Trip~2, the eight values 34.5--41.9 occur in the source "
            r"humidity column while the temperature column is empty. The "
            r"ledger assigns them to temperature; neither pressure nor "
            r"relative humidity is inferred. Trip~3 site~21 is retained as "
            r"31.321\% RH because the original workbook records the "
            r"fraction 0.31321. The 15 March records appended to the legacy "
            r"Trip~3 worksheet are dated 2023 in that workbook; the curated "
            r"table therefore labels them Trip~1 auxiliary/revisit records, "
            r"and Trip~3 ends on 21 February 2024. "
            + site40_note,
            r"\end{scriptsize}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_or_check(path: Path, content: str, check: bool) -> None:
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            raise ValueError(f"generated artifact is stale: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write all three generated artifacts into this directory.",
    )
    parser.add_argument("--curated-output", type=Path)
    parser.add_argument("--latex-output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail unless the selected outputs already have exact content.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    if args.output_dir:
        output_dir = args.output_dir.resolve()
        curated_output = output_dir / "environmental_measurements_curated.tsv"
        latex_output = output_dir / "env_table.tex"
        audit_output = output_dir / "environmental_measurements_audit.json"
    else:
        curated_output = (
            args.curated_output
            or project_root
            / "data/processed/metadata/environmental_measurements_curated.tsv"
        )
        latex_output = (
            args.latex_output or project_root / "data-paper/env_table.tex"
        )
        audit_output = (
            args.audit_output
            or project_root
            / "data/processed/metadata/environmental_measurements_audit.json"
        )

    rows, audit, applied_rows = curate(project_root)
    curated_content = render_curated_tsv(rows)
    latex_content = render_latex(rows, applied_rows)
    audit["generated_outputs"] = {
        "curated_tsv_sha256": hashlib.sha256(
            curated_content.encode("utf-8")
        ).hexdigest(),
        "latex_sha256": hashlib.sha256(
            latex_content.encode("utf-8")
        ).hexdigest(),
    }
    audit_content = json.dumps(
        audit, indent=2, sort_keys=True, ensure_ascii=False
    ) + "\n"

    write_or_check(Path(curated_output), curated_content, args.check)
    write_or_check(Path(latex_output), latex_content, args.check)
    write_or_check(Path(audit_output), audit_content, args.check)
    print(
        json.dumps(
            {
                "status": "passed",
                "curated_records": len(rows),
                "corrections_applied": len(applied_rows),
                "curated_output": str(curated_output),
                "latex_output": str(latex_output),
                "audit_output": str(audit_output),
                "check": args.check,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
