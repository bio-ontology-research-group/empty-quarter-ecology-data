#!/usr/bin/env python3
"""Stage the refined MAG catalogue v1.0.0 for a Zenodo deposit.

The deposit holds the three project-hosted archives (sequences, functional
tables, coverage profiles) next to the canonical metadata tables. This script
writes the small files of the upload set into OUT: metadata tables, a scoped
data dictionary, README, licence, Zenodo record metadata and an upload helper.
The large archives stay on IBEX; ``finish_on_ibex.sh`` hard-links them into the
upload directory and checks every SHA-256 against the receipts.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

VERSION = "1.0.0"
DEST = "metadata/metagenome/canonical"
TABLES = ("refined_representatives.tsv", "genome_manifest.tsv", "library_metadata.tsv",
          "ena_genome_accessions.tsv")
RECEIPTS = ("packaging_receipt.json", "analysis_receipt.json")
IBEX_RELEASE = "/ibex/project/c2014/rob/data-paper-mag-tier1-20261024/release"
TITLE = "Metagenome-assembled genome catalogue of Rub' al-Khali (Empty Quarter) desert soils"

# Paper author order; affiliations and ORCIDs follow the KG v3.0.1 Zenodo record.
AUTHORS = ["Tawfiq, Rund", "Abdelhakim, Marwa", "Alajel, Sulaiman M.", "Alarawi, Mohammed",
           "Aldakhil, Hind", "Derouiche, Abderahmane", "Drautz-Moses, Daniela I.", "Dumontier, Michel",
           "Grünberg, Raik", "Kulmanov, Maxat", "Lopez-Velazquez, Alejandra", "Martinez Arbas, Susana",
           "Niu, Kexin", "Sivakumar, Krishnakumar", "Wang, Tiannyu", "Zhao, Xiang", "Zubair, Jood",
           "Rueping, Magnus", "Hoehndorf, Robert"]
BORG = ("Bio-Ontology Research Group (BORG), Computer, Electrical and Mathematical Sciences and "
        "Engineering (CEMSE) Division, King Abdullah University of Science and Technology (KAUST), "
        "Thuwal, Saudi Arabia")


def read_table(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def creators(root):
    record = json.loads((root / "evidence/kg-v3.0.1/zenodo-record.json").read_text())
    known = {c["name"]: c for c in record["metadata"]["creators"]}
    known.setdefault("Kulmanov, Maxat", {"name": "Kulmanov, Maxat", "affiliation": BORG})
    missing = set(AUTHORS) - set(known)
    if missing:
        raise ValueError(f"authors without creator metadata: {sorted(missing)}")
    return [{k: known[name][k] for k in ("name", "affiliation", "orcid") if k in known[name]} for name in AUTHORS]


def readme(status):
    ena = status["ena_deposit"]
    tiers = ena["representative_mimag_tiers"]
    return f"""# {TITLE}, v{VERSION}

This deposit contains the species-representative metagenome-assembled genomes
(MAGs) reconstructed from 551 shotgun metagenomes of Rub' al-Khali desert soil,
collected in five campaigns between 2023 and 2025, together with their quality
estimates, taxonomy, gene annotations and per-library coverage. It accompanies the
data descriptor of the Rub' al-Khali knowledge base
(https://rubalkhali.science/; KG v3.0.1, https://doi.org/10.5281/zenodo.23134168).

## Contents

| File | Content |
|---|---|
| `refined_mags.tar.gz` | {status['representatives']:,} refined dRep representative FASTAs ({status['sequence_archive']['contigs']:,} contigs, {status['sequence_archive']['bases']:,} bp) |
| `refined_functional_tables.tar.gz` | `functional/`: per-genome KO, CAZy, Pfam and preferred-name counts (`genome_*_long.tsv`), predicted/annotated protein counts (`genome_ngenes.tsv`), tool versions and checksums per genome (`annotation_provenance.tsv`) |
| `refined_coverm_profiles.tar.gz` | `coverage/<library>.tsv`: CoverM mean depth, covered fraction, trimmed mean, read count and length of every genome in each of the {status['read_bearing_libraries']} libraries; `reference/genomes.tsv` (contig-to-genome definition) and `reference/reference_receipt.json`; `samples551.tsv` (library list) |
| `refined_representatives.tsv` | source library, binning strategy, CheckM2 quality and GTDB R232 lineage per representative |
| `genome_manifest.tsv` | archive member path, size, SHA-256, contig and base count per FASTA |
| `library_metadata.tsv` | campaign, site, compartment, replicate and ENA BioSample, experiment, run and assembly accessions per library |
| `ena_genome_accessions.tsv` | {ena['binned_metagenomes']:,} refined bins with MIMAG tier, binned-metagenome accessions and, for {ena['mags']:,} representatives, MAG BioSample, analysis, GCA and sequence accessions |
| `DATA_DICTIONARY.tsv` | field definitions, units and missing-value conventions of the four tables |
| `packaging_receipt.json`, `analysis_receipt.json` | integrity receipts of the three archives |
| `SHA256SUMS` | SHA-256 of every file in this deposit |

## Methods summary

Reads were assembled per library with MEGAHIT v1.2.9 (contigs of at least 500 bp),
binned with SemiBin2 v2.2.1 (single-sample and self-supervised) and refined with
DAS Tool v1.1.7. CheckM2 v1.1.0 estimated completeness and contamination. dRep
dereplicated the {ena['binned_metagenomes']:,} bins with at least 50% completeness and
at most 10% contamination at 95% ANI (fastANI) into {status['representatives']:,} species
representatives; GTDB-Tk v2.7.2 classified them against GTDB R232. MIMAG tiers:
{tiers['high']} high quality, {tiers['medium']:,} medium quality, and {tiers['below-medium']} representative at exactly
10% contamination. Bakta v1.12.0 (database v6.0 full) predicted genes;
eggNOG-mapper v2.1.13 (eggNOG v5.0.2, DIAMOND v2.0.15) assigned KOs, CAZy
families, Pfam domains and preferred names. Bowtie2 v2.5.1 (`--very-sensitive`,
first 200 million read pairs) mapped each library to a reference of all refined
contigs, each prefixed with its genome identifier; CoverM v0.6.1 genome mode
counted reads at 95% identity or more. Code and validation:
https://github.com/bio-ontology-research-group/empty-quarter-data-paper
(`scripts/release/`, `evidence/mag-catalogue-20261024/`).

## Related ENA records

ENA study PRJEB125153 (ERP204894) holds the {ena['runs']} read runs, {ena['primary_assemblies']} primary
assemblies, {ena['binned_metagenomes']:,} binned metagenomes and {ena['mags']:,} MAGs (public from
{ena['scheduled_release']}). `48Dr2__self_SemiBin_25` is at ENA as a binned metagenome only,
because ENA admits MAGs below 10% contamination. This deposit contains all
{status['representatives']:,} representatives.

## Licence

Project-authored data in this deposit are licensed under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). Taxonomic lineages derive from
GTDB release R232; functional identifiers derive from KEGG, CAZy, Pfam and eggNOG,
which retain their own terms. Raw reads at ENA retain their own access conditions.
"""


def zenodo_metadata(root, status):
    description = (
        f"<p>Species-representative metagenome-assembled genomes (MAGs) from 551 shotgun metagenomes "
        f"of Rub' al-Khali (Empty Quarter) desert soil, Saudi Arabia: {status['representatives']:,} refined "
        f"dRep representatives with CheckM2 quality estimates, MIMAG tiers, GTDB R232 taxonomy, "
        f"Bakta and eggNOG-mapper gene annotations, and CoverM coverage profiles of all 551 libraries.</p>"
        f"<p>Reads, assemblies, bins and MAGs are deposited at ENA under PRJEB125153. "
        f"See README.md for contents, methods and licence.</p>"
        f"<p>Portal: <a href=\"https://rubalkhali.science/\">https://rubalkhali.science/</a><br>"
        f"Code: <a href=\"https://github.com/bio-ontology-research-group/empty-quarter-data-paper\">"
        f"https://github.com/bio-ontology-research-group/empty-quarter-data-paper</a></p>")
    return {"metadata": {
        "title": TITLE, "version": VERSION, "upload_type": "dataset", "access_right": "open",
        "license": "cc-by-4.0", "description": description, "creators": creators(root),
        "keywords": ["metagenome-assembled genomes", "MAG", "shotgun metagenomics", "desert soil",
                     "Rub' al-Khali", "Empty Quarter", "hyperarid", "GTDB", "Bakta", "eggNOG"],
        "related_identifiers": [
            {"identifier": "10.5281/zenodo.23134168", "relation": "isSupplementTo", "scheme": "doi"},
            {"identifier": "https://www.ebi.ac.uk/ena/browser/view/PRJEB125153", "relation": "isDerivedFrom", "scheme": "url"},
            {"identifier": "https://github.com/bio-ontology-research-group/empty-quarter-data-paper", "relation": "isSupplementedBy", "scheme": "url"},
        ],
        "prereserve_doi": True,
    }}


UPLOAD = """#!/usr/bin/env bash
# Create a Zenodo draft from zenodo_metadata.json and upload every file listed in SHA256SUMS.
# Usage: ZENODO_TOKEN=... bash upload_to_zenodo.sh   (the draft stays unpublished; publish in the web UI)
set -euo pipefail
cd "$(dirname "$0")"
api=${ZENODO_API:-https://zenodo.org/api}
: "${ZENODO_TOKEN:?set ZENODO_TOKEN to a token with deposit:write}"
sha256sum -c --quiet SHA256SUMS
draft=$(curl -fsS -H "Authorization: Bearer $ZENODO_TOKEN" -H "Content-Type: application/json" \\
    -X POST "$api/deposit/depositions" --data @zenodo_metadata.json)
bucket=$(printf '%s' "$draft" | python3 -c 'import json,sys; print(json.load(sys.stdin)["links"]["bucket"])')
printf '%s' "$draft" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("draft", d["id"], "reserved DOI", d["metadata"]["prereserve_doi"]["doi"])'
while read -r _ name; do
    echo "uploading $name"
    curl -fsS -H "Authorization: Bearer $ZENODO_TOKEN" --upload-file "$name" "$bucket/$name" > /dev/null
done < SHA256SUMS
echo "uploaded; review and publish the draft at https://zenodo.org/deposit"
"""

FINISH = f"""#!/usr/bin/env bash
# Run on IBEX inside this directory: link the release archives, write and check SHA256SUMS.
set -euo pipefail
cd "$(dirname "$0")"
release=${{1:-{IBEX_RELEASE}}}
for name in refined_mags.tar.gz refined_functional_tables.tar.gz refined_coverm_profiles.tar.gz; do
    ln -f "$release/$name" "$name"
done
python3 - <<'PY'
import hashlib, json
def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()
expected = {{json.load(open("packaging_receipt.json"))["artifact"]: json.load(open("packaging_receipt.json"))["sha256"]}}
expected.update({{a["artifact"]: a["sha256"] for a in json.load(open("analysis_receipt.json"))["artifacts"]}})
for name, digest in expected.items():
    if sha(name) != digest:
        raise SystemExit(f"checksum differs from receipt: {{name}}")
print("archives match receipts")
PY
ls -1 | grep -v -e '^SHA256SUMS$' -e '^upload_to_zenodo.sh$' -e '^finish_on_ibex.sh$' -e '^zenodo_metadata.json$' -e '\\.log$' \\
    | sort | xargs sha256sum > SHA256SUMS
sha256sum -c --quiet SHA256SUMS && echo "SHA256SUMS written and verified: $(wc -l < SHA256SUMS) files"
"""


def stage(root, out):
    status = json.loads((root / DEST / "release_status.json").read_text())
    if not (status["sequence_release"] and status["annotation_release"] and status["recruitment_release"]):
        raise ValueError("catalogue is not a verified sequence-and-analyses candidate")
    out.mkdir(parents=True, exist_ok=True)
    for name in TABLES + RECEIPTS:
        shutil.copy2(root / DEST / name, out / name)
    dictionary = [r for r in read_table(root / "metadata/DATA_DICTIONARY.tsv")
                  if r["path"] in {f"{DEST}/{name}" for name in TABLES}]
    for row in dictionary:
        row["path"] = Path(row["path"]).name
    if {r["path"] for r in dictionary} != set(TABLES):
        raise ValueError("data dictionary does not describe every table")
    with (out / "DATA_DICTIONARY.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dictionary[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(dictionary)
    (out / "README.md").write_text(readme(status), encoding="utf-8")
    (out / "zenodo_metadata.json").write_text(json.dumps(zenodo_metadata(root, status), indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    (out / "upload_to_zenodo.sh").write_text(UPLOAD)
    (out / "finish_on_ibex.sh").write_text(FINISH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stage(args.root, args.out)
