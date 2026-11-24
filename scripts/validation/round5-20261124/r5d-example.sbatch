#!/bin/bash
#SBATCH --job-name=r5d-example
#SBATCH --account=k10018
#SBATCH --partition=debug
#SBATCH --nodes=1
#SBATCH --time=00:30:00
#SBATCH --output=/scratch/project/k10018/work/eq-round5-20261124/data/example/%x-%j.log
# Clean-environment test of the worked example: a fresh virtual environment without any packages,
# python -I (isolated: no user site, no PYTHONPATH), an empty working directory, and only released files.
set -euo pipefail
W=/scratch/project/k10018/work/eq-round5-20261124/data/example
cd $W/release
echo "== deposit checksums"; grep -E "refined_coverm_profiles|library_metadata|refined_representatives|ena_genome_accessions" SHA256SUMS | sha256sum -c -
RUN=$W/run-$SLURM_JOB_ID; rm -rf $RUN; mkdir -p $RUN; cd $RUN
/usr/bin/python3 -m venv --without-pip venv
echo "== python: $(venv/bin/python -V); site-packages: $(ls venv/lib/python3*/site-packages | wc -l) entries"
env -i PATH=/usr/bin:/bin venv/bin/python -I $W/worked_example_10Dr2.py $W/release > output.txt 2> stderr.txt || { cat stderr.txt; exit 1; }
cat output.txt
if [ -s $W/worked_example_10Dr2.expected.txt ]; then diff $W/worked_example_10Dr2.expected.txt output.txt && echo "== matches expected output"; fi
# corrected annotation provenance table (eggNOG version column held an error message)
mkdir -p $W/../release-fixes
tar -xzOf $W/release/refined_functional_tables.tar.gz functional/annotation_provenance.tsv > $RUN/annotation_provenance.orig.tsv
venv/bin/python -I - <<'PY'
import csv, re, sys, os
run = os.getcwd(); out = os.path.join(os.environ.get("W", ""), "../release-fixes/annotation_provenance.tsv")
rows = list(csv.DictReader(open(f"{run}/annotation_provenance.orig.tsv"), delimiter="\t"))
n = 0
for r in rows:
    v = re.sub(r"\x1b\[[0-9;]*m", "", r["eggnog_version"])
    em = re.search(r"emapper-([\d.]+)", v); dm = re.search(r"diamond version ([\d.]+)", v)
    mm = re.search(r"MMseqs2 version found: (\S+)", v); nf = re.search(r"novel families DB version: ([\d.]+)", v)
    new = (f"emapper-{em.group(1)}; eggNOG DB 5.0.2 (data_dir /ibex/reference/KSL/eggnog-mapper/2.1.12, version table read 2026-11-24); "
           f"DIAMOND {dm.group(1)}; MMseqs2 {mm.group(1)}; novel families DB {nf.group(1)}")
    n += r["eggnog_version"] != new
    r["eggnog_version"] = new
with open(out, "w", newline="") as fo:
    w = csv.DictWriter(fo, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(rows)
print(f"annotation_provenance: {len(rows)} rows, {n} eggnog_version values rewritten -> {out}")
print("distinct new values:", sorted({r['eggnog_version'] for r in rows}))
PY
