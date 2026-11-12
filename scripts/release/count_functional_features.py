"""Count distinct functional features in the released annotation products.

Reads the Bakta/eggNOG archive (refined_functional_tables.tar.gz), the legacy
analytical KO matrix (rep_ko_v2.tsv) and the PICRUSt2 KO table, and writes the
counts and input checksums as JSON. build_cohort_product_manifest.py reads this
JSON instead of typed-in numbers and checks the archive checksum against
analysis_receipt.json.

Run where the inputs are (on Shaheen:
/project/k10018/empty-quarter/data/refined-annotations):

    python3 -I count_functional_features.py SRC_DIR > functional_feature_counts.json
"""
import csv
import hashlib
import io
import json
import re
import sys
import tarfile

KO = re.compile(r"^K\d{5}$")


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def norm(k: str) -> str:
    k = k.strip()
    k = k[3:] if k.startswith("ko:") else k
    if not KO.match(k):
        raise ValueError(f"not a KO: {k!r}")
    return k


def main(src: str) -> dict:
    out: dict = {"inputs": {}}
    arc = f"{src}/refined_functional_tables.tar.gz"
    out["inputs"]["refined_functional_tables.tar.gz"] = sha(arc)
    bakta: dict = {}
    with tarfile.open(arc) as t:

        def rows(name: str):
            member = t.extractfile(f"functional/{name}")
            return csv.DictReader(io.TextIOWrapper(member, encoding="utf-8"), delimiter="\t")

        bakta_kos, genomes = set(), set()
        for r in rows("genome_ko_long.tsv"):
            if float(r["count"]) > 0:
                bakta_kos.add(norm(r["ko"]))
                genomes.add(r["genome"])
        bakta["genomes"] = len(genomes)
        bakta["distinct_kos"] = len(bakta_kos)
        bakta["distinct_pfams"] = len(
            {r["pfam"] for r in rows("genome_pfam_long.tsv") if float(r["count"]) > 0}
        )
        bakta["distinct_cazy"] = len(
            {r["cazy"] for r in rows("genome_cazy_long.tsv") if float(r["count"]) > 0}
        )
        sums = {"n_genes_predicted": 0, "n_genes_annotated": 0, "n_with_ko": 0}
        n = 0
        for r in rows("genome_ngenes.tsv"):
            n += 1
            for k in sums:
                sums[k] += int(r[k])
        bakta["ngenes_genomes"] = n
        bakta.update({f"sum_{k}": v for k, v in sums.items()})

    legacy = f"{src}/rep_ko_v2.tsv"
    out["inputs"]["rep_ko_v2.tsv"] = sha(legacy)
    legacy_kos: set = set()
    legacy_genomes = 0
    with open(legacy) as f:
        for line in f:
            _, _, rest = line.rstrip("\n").partition("\t")
            legacy_genomes += 1
            legacy_kos.update(norm(k) for k in rest.split(",") if k.strip())

    pic = f"{src}/picrust2_ko_metagenome_unstrat.tsv"
    out["inputs"]["picrust2_ko_metagenome_unstrat.tsv"] = sha(pic)
    pic_all, pic_nonzero = set(), set()
    with open(pic) as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            k = norm(parts[0])
            pic_all.add(k)
            if any(float(x) > 0 for x in parts[1:]):
                pic_nonzero.add(k)

    out["bakta_eggnog"] = bakta
    out["legacy_rep_ko_v2"] = {
        "genomes": legacy_genomes,
        "distinct_kos": len(legacy_kos),
        "shared_with_picrust2_rows": len(legacy_kos & pic_all),
        "shared_with_picrust2_nonzero": len(legacy_kos & pic_nonzero),
    }
    out["picrust2"] = {"ko_rows": len(pic_all), "ko_nonzero": len(pic_nonzero)}
    out["bakta_vs_legacy"] = {
        "shared": len(bakta_kos & legacy_kos),
        "bakta_only": len(bakta_kos - legacy_kos),
        "legacy_only": len(legacy_kos - bakta_kos),
        "bakta_shared_with_picrust2_rows": len(bakta_kos & pic_all),
    }
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=2, sort_keys=True))
