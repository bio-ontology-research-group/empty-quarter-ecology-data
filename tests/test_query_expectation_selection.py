"""Complete-profile expectations must not be derived from a truncated preview."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/release/derive_query_expectations.py"
SPEC = importlib.util.spec_from_file_location("expectations", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_complete_run_selection_after_first_hundred_preserves_duplicates():
    prefix = [{"runLabel": "FASTQ dataset for earlier", "count": 1}] * 100
    target = [{"runLabel": "FASTQ dataset for ERR16061083", "count": n} for n in range(120)]
    target.append(target[-1].copy())
    assert MODULE.select_taxonomy_run(prefix + target, "ERR16061083") == target


def test_exact_label_only_and_absent_run_fails():
    with pytest.raises(ValueError, match="No source-derived"):
        MODULE.select_taxonomy_run([{"runLabel": "FASTQ dataset for ERR160610830"}], "ERR16061083")


def test_emitted_lineage_matches_frozen_rank_label_encoding():
    assert MODULE.emitted_lineage("Bacteria;Actinomycetota;Actinobacteria;0319-7L14;NA;NA") == (
        "Domain: Bacteria; Phylum: Actinomycetota; Class: Actinobacteria; "
        "Order: 0319-7L14; Family: NA; Genus: NA")
    assert MODULE.emitted_lineage("Bacteria;;;;;Pseudomonas") == (
        "Domain: Bacteria; Phylum: NA; Class: NA; Order: NA; Family: NA; Genus: Pseudomonas")


@pytest.mark.parametrize('value', [-1, 1.5, float('nan'), float('inf')])
def test_invalid_read_counts_rejected(value):
    with pytest.raises(ValueError, match='finite, nonnegative integers'):
        MODULE.validate_read_counts(MODULE.np.array([[value]]))


def test_numeric_order_precedes_lexical_count_order():
    MODULE.validate_read_counts(MODULE.np.array([[0, 9, 100, 509]]))
    rows=[dict(runLabel='run',count=n,lineage='same',proc='proc') for n in (9.0,100.0,509.0)]
    assert [r['count'] for r in sorted(rows,key=MODULE.taxonomy_numeric_order)] == [509,100,9]
