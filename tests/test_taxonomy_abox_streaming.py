import json
from pathlib import Path
import subprocess
import sys

from scripts.validation import validate_taxonomy_abox_streaming as validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "validation"
    / "validate_taxonomy_abox_streaming.py"
)


def iri(value: str) -> str:
    return f"<{value}>"


def triple(subject: str, predicate: str, obj: str) -> str:
    return f"{iri(subject)} {iri(predicate)} {obj} ."


def literal(value: str, datatype: str | None = None) -> str:
    result = json.dumps(value)
    if datatype:
        result += f"^^{iri(datatype)}"
    return result


def valid_fixture(broken_quality_link: bool = False) -> str:
    base = validator.BASE
    taxon = "http://purl.obolibrary.org/obo/NCBITaxon_2"
    fastq = base + "RAK_7790001"
    protocol = validator.PROTOCOL_IRI
    process = base + "RAK_P290001"
    quality_iris = [base + f"RAK_Q{number:08d}" for number in range(1, 15)]
    value_iris = [base + f"RAK_V{number:08d}" for number in range(1, 15)]
    dataset_iris = [
        base + f"RAK_{validator.DATASET_START + offset}"
        for offset in range(14)
    ]
    lines: list[str] = []

    lines.append(
        triple(taxon, validator.RDF_TYPE, iri(validator.OWL_NAMED_INDIVIDUAL))
    )
    for quality in quality_iris:
        lines.append(
            triple(taxon, validator.SIO_HAS_ATTRIBUTE, iri(quality))
        )

    lines.append(
        triple(fastq, validator.RDF_TYPE, iri(validator.OWL_NAMED_INDIVIDUAL))
    )
    for quality in quality_iris:
        lines.append(
            triple(fastq, validator.SIO_HAS_ATTRIBUTE, iri(quality))
        )

    lines.extend(
        [
            triple(
                protocol,
                validator.RDF_TYPE,
                iri(validator.OWL_NAMED_INDIVIDUAL),
            ),
            triple(
                protocol,
                validator.RDFS_LABEL,
                literal("16S amplicon processing protocol"),
            ),
            triple(
                process,
                validator.RDF_TYPE,
                iri(validator.OWL_NAMED_INDIVIDUAL),
            ),
            triple(
                process,
                validator.RDF_TYPE,
                iri(validator.WORKFLOW_CLASS),
            ),
        ]
    )
    for dataset in dataset_iris:
        lines.append(triple(process, validator.SIO_HAS_OUTPUT, iri(dataset)))
    lines.extend(
        [
            triple(process, validator.SIO_HAS_INPUT, iri(fastq)),
            triple(process, validator.SIO_IS_SPECIFIED_BY, iri(protocol)),
            triple(
                process,
                validator.RDFS_LABEL,
                literal("16S amplicon processing of sample1 (ERR1)"),
            ),
        ]
    )

    for offset, dataset in enumerate(dataset_iris):
        absolute = offset % 2 == 0
        kind = "Absolute" if absolute else "Relative"
        rank = validator.RANKS[offset // 2]
        dataset_class = (
            validator.ABSOLUTE_DATASET_CLASS
            if absolute
            else validator.RELATIVE_DATASET_CLASS
        )
        lines.extend(
            [
                triple(
                    dataset,
                    validator.RDF_TYPE,
                    iri(validator.OWL_NAMED_INDIVIDUAL),
                ),
                triple(dataset, validator.RDF_TYPE, iri(dataset_class)),
                triple(
                    dataset,
                    validator.SIO_HAS_MEMBER,
                    iri(value_iris[offset]),
                ),
                triple(
                    dataset,
                    validator.RDFS_LABEL,
                    literal(
                        f"Taxon {kind.lower()} abundance dataset for "
                        f"sample1 ({rank})"
                    ),
                ),
            ]
        )

    for offset, quality in enumerate(quality_iris):
        number = offset + 1
        absolute = number % 2 == 1
        quality_class = (
            validator.ABSOLUTE_QUALITY_CLASS
            if absolute
            else validator.RELATIVE_QUALITY_CLASS
        )
        pato_class = (
            validator.AMOUNT_QUALITY_CLASS
            if absolute
            else validator.CONCENTRATION_QUALITY_CLASS
        )
        value = value_iris[offset]
        if broken_quality_link and number == 1:
            value = value_iris[1]
        lines.extend(
            [
                triple(
                    quality,
                    validator.RDF_TYPE,
                    iri(validator.OWL_NAMED_INDIVIDUAL),
                ),
                triple(quality, validator.RDF_TYPE, iri(pato_class)),
                triple(quality, validator.RDF_TYPE, iri(quality_class)),
                triple(quality, validator.SIO_IS_ATTRIBUTE_OF, iri(taxon)),
                triple(quality, validator.SIO_IS_ATTRIBUTE_OF, iri(fastq)),
                triple(
                    quality,
                    validator.SIO_HAS_MEASUREMENT_VALUE,
                    iri(value),
                ),
            ]
        )

    for offset, value in enumerate(value_iris):
        number = offset + 1
        absolute = number % 2 == 1
        kind = "Absolute" if absolute else "Relative"
        rank = validator.RANKS[offset // 2]
        value_class = (
            validator.ABSOLUTE_VALUE_CLASS
            if absolute
            else validator.RELATIVE_VALUE_CLASS
        )
        value_predicate = (
            validator.ABSOLUTE_VALUE_PROPERTY
            if absolute
            else validator.RELATIVE_VALUE_PROPERTY
        )
        numeric = "2.0" if absolute else "0.5"
        lineage = "; ".join(
            f"{item}: Taxon"
            for item in validator.RANKS[: (offset // 2) + 1]
        )
        lines.extend(
            [
                triple(
                    value,
                    validator.RDF_TYPE,
                    iri(validator.OWL_NAMED_INDIVIDUAL),
                ),
                triple(value, validator.RDF_TYPE, iri(value_class)),
                triple(
                    value,
                    validator.SIO_IS_MEASUREMENT_VALUE_OF,
                    iri(quality_iris[offset]),
                ),
                triple(
                    value,
                    value_predicate,
                    literal(numeric, validator.XSD_DOUBLE),
                ),
                triple(
                    value,
                    validator.LINEAGE_PROPERTY,
                    literal(lineage),
                ),
                triple(
                    value,
                    validator.RDFS_LABEL,
                    literal(
                        f"{kind} abundance of Taxon in sample1 ({rank})"
                    ),
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def run_validator(tmp_path: Path, source: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    source_path = tmp_path / "taxonomy.ttl"
    report_path = tmp_path / "report.json"
    source_path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source_path),
            "--output",
            str(report_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(report_path.read_text(encoding="utf-8"))


def test_complete_streaming_gate_accepts_structurally_valid_fixture(tmp_path):
    result, report = run_validator(tmp_path, valid_fixture())

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "passed"
    assert report["coverage"]["shex"]["status"] == "not_run"
    assert report["structural_scan"]["bytes_read"] == report["input"]["bytes"]
    assert (
        report["structural_scan"]["triples_scanned"]
        == report["turtle_parser"]["triple_count"]
    )
    assert report["structural_results"]["category_counts"] == {
        "datasets": 14,
        "fastq_bearer_subjects": 1,
        "other_bearer_subjects": 1,
        "processes": 1,
        "protocol_subjects": 1,
        "qualities": 14,
        "values": 14,
    }
    assert report["structural_results"]["violations"]["total"] == 0


def test_gate_fails_on_broken_reciprocal_measurement_link(tmp_path):
    result, report = run_validator(
        tmp_path, valid_fixture(broken_quality_link=True)
    )

    assert result.returncode == 1
    assert report["status"] == "failed"
    violations = report["structural_results"]["violations"]["by_code"]
    assert violations["quality_value_link"] == 1
    assert violations["measurement_inverse_mismatch"] == 1
    assert report["turtle_parser"]["passed"]


def test_gate_fails_closed_on_invalid_turtle_and_still_writes_json(tmp_path):
    result, report = run_validator(
        tmp_path,
        "<https://example.org/subject> <https://example.org/predicate> .\n",
    )

    assert result.returncode == 1
    assert report["status"] == "failed"
    assert not report["turtle_parser"]["passed"]
    assert any(
        "Raptor did not complete" in item
        for item in report["execution_errors"]
    )
    assert report["coverage"]["shex"]["coverage_fraction"] == 0.0


def test_gate_fails_closed_when_streaming_parser_is_unavailable(tmp_path):
    source_path = tmp_path / "taxonomy.ttl"
    report_path = tmp_path / "report.json"
    source_path.write_text(valid_fixture(), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source_path),
            "--output",
            str(report_path),
            "--rapper",
            str(tmp_path / "does-not-exist"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert report["status"] == "failed"
    assert "Raptor rapper is required" in report["execution_errors"][0]
