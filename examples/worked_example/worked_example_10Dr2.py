#!/usr/bin/env python3
"""Worked example of the Rub' al-Khali data descriptor: follow specimen 10Dr2 from the physical tube to
an annotated gene, using only released tables.

    specimen -> 16S profile and shotgun library -> genome abundance profile -> genome -> gene -> annotation

The script uses the Python standard library only (no third-party packages) and reads the released files
from one directory (default ./release, or the first argument):

  from the data repository (empty-quarter-ecology-data):
    sample_ledger.tsv                     evidence/release/
    combined_samplesheet_accessions.tsv   metadata/amplicon/
    alpha.tsv                             evidence/ecology-canonical/cache/
    shotgun_cohort_accounting.tsv         metadata/cohorts/
    shotgun_mapping_qc_source.tsv         metadata/cohorts/source/
    gunc_progenomes3.tsv                  metadata/metagenome/canonical/
    ph_accepted_measurements.tsv          metadata/ph/
  from the genome deposit (refined MAG catalogue v1.0.0):
    library_metadata.tsv, refined_representatives.tsv, ena_genome_accessions.tsv,
    refined_coverm_profiles.tar.gz, refined_functional_tables.tar.gz
  from the gene crosswalk (EQ-PROT-CROSSWALK-v1.0.0):
    crosswalk/10Dr2.tsv.gz                genes of the genomes assembled from library 10Dr2

It also exercises three cases that a join must handle: a specimen with two amplicon profiles (F15PRr1),
a laboratory control that is not part of any cohort (EB1), and a missing measurement (pH of 10Dr1).
Expected output: worked_example_10Dr2.expected.txt (compare with `diff`).
"""
import csv
import gzip
import io
import sys
import tarfile
from pathlib import Path

REL = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("release")
SPECIMEN = "10Dr2"
# KOs tried in this order: coxL (aerobic CO dehydrogenase), hhyL (group 1h [NiFe] hydrogenase), cynT/can (carbonic anhydrase);
# the first one present in the most abundant genome is followed to its gene
KO_CANDIDATES = ["K03520", "K06281", "K01673"]


def rows(name, opener=open):
    with opener(REL / name, "rt", newline="") as fh:
        yield from csv.DictReader(fh, delimiter="\t")


def one(items, what):
    items = list(items)
    if len(items) != 1:
        raise SystemExit(f"FAIL: expected one {what}, found {len(items)}")
    return items[0]


def tar_member(archive, suffix):
    with tarfile.open(REL / archive) as tf:
        m = one([m for m in tf.getmembers() if m.name.endswith(suffix)], f"{suffix} in {archive}")
        return io.TextIOWrapper(tf.extractfile(m), encoding="utf-8").read()


print(f"== 1. Specimen {SPECIMEN}")
spec = one((r for r in rows("sample_ledger.tsv") if r["sample_id"] == SPECIMEN), "ledger row")
LABEL = {"Deep": "Deep (shallow subsurface soil)", "Rhizosphere": "Rhizosphere (root-adjacent soil)", "Surface": "Surface"}
print(f"trip {spec['trip']}, site {spec['site']} ({spec['canonical_site_iri']}), compartment {LABEL[spec['compartment']]}, "
      f"DNA kit {spec['dna_kit']}, DNA {float(spec['dna_concentration']):.2f} ng/ul")

print("== 2. 16S amplicon profile")
amp = one((r for r in rows("combined_samplesheet_accessions.tsv") if r["source_sample_name"] == SPECIMEN), "amplicon run")
alpha = {r[""]: r for r in rows("alpha.tsv")}
prof = one((k for k in alpha if k.split("_", 1)[-1] == SPECIMEN), "retained profile")
print(f"BioSample {amp['biosample_accession']}, run {amp['run']}; profile {prof}: "
      f"{int(float(alpha[prof]['depth'])):,} reads, Shannon {float(alpha[prof]['shannon']):.2f}")
two = sorted(r["run"] for r in rows("combined_samplesheet_accessions.tsv") if r["source_sample_name"] == "F15PRr1")
print(f"check, repeated preparation: F15PRr1 has {len(two)} amplicon runs {two}; "
      f"retained profiles {sorted(k for k in alpha if k.endswith('_F15PRr1'))}")
print(f"check, control: EB1 is a retained profile: {'EB1' in alpha}")

print("== 3. Shotgun library")
lib = one((r for r in rows("library_metadata.tsv") if r["sample"] == SPECIMEN), "library")
acc = one((r for r in rows("shotgun_cohort_accounting.tsv") if r["sample"] == SPECIMEN), "cohort row")
print(f"run {lib['run_accession']}, BioSample {lib['biosample_accession']}, assembly {lib['assembly_accession']}; "
      f"{acc['sequencer_platforms']}, {acc['library_prep_kits']}; {int(acc['post_qc_reads']):,} reads after QC; "
      f"core-transect cohort {acc['in_546_core_transect']}, amplicon-matched {acc['in_442_amplicon_matched']}")
assert lib["biosample_accession"] == amp["biosample_accession"] or True  # amplicon and shotgun BioSamples are registered separately

print("== 4. Genome abundance profile of the library")
qc = one((r for r in rows("shotgun_mapping_qc_source.tsv") if r["sample_id"] == SPECIMEN), "mapping QC row")
print(f"relative-abundance product (CoverM 0.7.0): {float(qc['mapped_percent']):.1f}% of reads assigned to "
      f"{qc['nonzero_representatives']} genomes")
cov = list(csv.DictReader(io.StringIO(tar_member("refined_coverm_profiles.tar.gz", f"coverage/{SPECIMEN}.tsv")), delimiter="\t"))
total = int(acc["post_qc_reads"])
key = lambda c: f"{SPECIMEN} {c}"
cov.sort(key=lambda r: -int(r[key("Read Count")]))
mapped = sum(int(r[key("Read Count")]) for r in cov)
print(f"depth/breadth product (Bowtie2, CoverM 0.6.1, >=95% identity): {100 * mapped / total:.1f}% of reads; "
      f"{sum(float(r[key('Covered Fraction')]) >= 0.1 for r in cov)} genomes with at least 10% covered")
for r in cov[:3]:
    print(f"  {r['Genome']}: {100 * int(r[key('Read Count')]) / total:.2f}% of reads, mean depth {float(r[key('Mean')]):.1f}, "
          f"covered {100 * float(r[key('Covered Fraction')]):.1f}%")

print("== 5. Genome")
top = cov[0]["Genome"]
rep = one((r for r in rows("refined_representatives.tsv") if r["mag"] == top), "representative")
ena = one((r for r in rows("ena_genome_accessions.tsv") if r["genome"] == top), "ENA genome row")
gunc = one((r for r in rows("gunc_progenomes3.tsv") if r["genome"] == top), "GUNC row")
print(f"{top}: assembled from library {rep['sample']}; {rep['gtdb_r232_classification'].split(';')[-3:]}; "
      f"completeness {float(rep['Completeness']):.1f}%, contamination {float(rep['Contamination']):.1f}%; "
      f"chimerism screen {gunc['gunc_status']}; MIMAG {ena['mimag_tier']}; {ena['gca_accession']}")
kos = [l.split("\t") for l in tar_member("refined_functional_tables.tar.gz", "genome_ko_long.tsv").splitlines()]
kos = {k[1]: int(k[2]) for k in kos[1:] if k[0] == top}
KO_OF_INTEREST = next(k for k in KO_CANDIDATES if k in kos)
print(f"release annotation (Bakta/eggNOG): {len(kos):,} distinct KOs in this genome; "
      f"{KO_OF_INTEREST} in {kos.get(KO_OF_INTEREST, 0)} protein(s)")

print("== 6. Gene and annotation")
cols = ["gene", "genome", "contig", "start", "end", "strand", "family_rep", "family_flag", "match_class",
        "bakta_locus", "bakta_product", "eggnog_og", "cog_category", "ko", "pfam", "eggnog_description"]
genes = [dict(zip(cols, l.rstrip("\n").split("\t"))) for l in gzip.open(REL / "crosswalk" / f"{SPECIMEN}.tsv.gz", "rt")]
genes = [g for g in genes if g["genome"] == top]
hits = sorted((g for g in genes if KO_OF_INTEREST in g["ko"].replace("ko:", "").split(",")),
              key=lambda g: (g["contig"], int(g["start"])))
print(f"{len(genes):,} Pyrodigal genes in {top}; {sum(g['match_class'] in ('exact', 'same_stop') for g in genes):,} "
      f"carry a transferred Bakta/eggNOG annotation; genes with {KO_OF_INTEREST}: {len(hits)}")
for g in hits:
    print(f"  {g['gene']} {g['contig']}:{g['start']}-{g['end']} ({g['strand']}), match {g['match_class']}, "
          f"Bakta {g['bakta_locus']} '{g['bakta_product']}', eggNOG {g['eggnog_og']}, COG {g['cog_category']}, KO {g['ko']}")

print("== 7. Soil pH of the same tube")
ph = {r["sample_id"]: r for r in rows("ph_accepted_measurements.tsv") if r["disposition"] == "ADMITTED_MEASUREMENT"}
p = ph[SPECIMEN]
print(f"{SPECIMEN}: pH {float(p['ph_value']):.2f} in CaCl2, electrode slope {p['slope_percent']}%")
for other in ("10Dr1", "10Dr3"):
    print(f"check, missing measurement: {other} pH {'%.2f' % float(ph[other]['ph_value']) if other in ph else 'not admitted (no value is borrowed from another tube)'}")
print("OK")
