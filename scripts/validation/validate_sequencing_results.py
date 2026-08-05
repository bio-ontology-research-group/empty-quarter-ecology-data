import os
from pathlib import Path
import argparse


def check_amplicon(sample_path, errors):
    s16_path = sample_path / "16S"
    if not s16_path.exists():
        return False

    err_dirs = [
        d for d in s16_path.iterdir() if d.is_dir() and d.name.startswith("ERR")
    ]
    if not err_dirs:
        errors.append("16S: No ERR run directories found")
        return True

    for err_dir in err_dirs:
        run_id = err_dir.name

        # Check FASTQ
        fastq_dir = err_dir / "fastq"
        if not fastq_dir.exists():
            errors.append(f"16S/{run_id}: Missing fastq directory")
        else:
            files = list(fastq_dir.iterdir())
            fq_files = [
                f
                for f in files
                if (f.name.endswith(".fastq.gz") or f.name.endswith(".fastq"))
                and not f.is_dir()
            ]
            if not fq_files:
                errors.append(f"16S/{run_id}: No FASTQ files in fastq directory")

            # Check FastQC
            fastqc_dir = fastq_dir / "fastqc"
            if not fastqc_dir.exists():
                errors.append(f"16S/{run_id}: Missing fastqc directory")
            else:
                reports = list(fastqc_dir.iterdir())
                if not reports:
                    errors.append(f"16S/{run_id}: fastqc directory is empty")

        # Check QC JSON
        qc_json = err_dir / "qc" / "multiqc_stats.json"
        if not qc_json.exists():
            errors.append(f"16S/{run_id}: Missing qc/multiqc_stats.json")

        # Check Taxon Table
        taxon_table = err_dir / "taxon_table.tsv"
        if not taxon_table.exists():
            errors.append(f"16S/{run_id}: Missing taxon_table.tsv")

    return True


def check_wgs(sample_path, errors):
    wgs_root = sample_path / "WGS"
    if not wgs_root.exists():
        return False

    sample_name = sample_path.name
    wgs_sample_dir = wgs_root / sample_name

    if not wgs_sample_dir.exists():
        subdirs = [d for d in wgs_root.iterdir() if d.is_dir()]
        if not subdirs:
            errors.append("WGS: Empty WGS directory")
            return True
        wgs_sample_dir = subdirs[0]

    # Check FASTQ
    fastq_dir = wgs_sample_dir / "fastq"
    if not fastq_dir.exists():
        errors.append("WGS: Missing fastq directory")
    else:
        fq_files = [f for f in fastq_dir.iterdir() if f.name.endswith(".fastq.gz")]
        if not fq_files:
            errors.append("WGS: No FASTQ files in fastq directory")

        # Check FastQC (FastP)
        fastqc_dir = fastq_dir / "fastqc"
        if not fastqc_dir.exists():
            errors.append("WGS: Missing fastqc directory")
        else:
            if not list(fastqc_dir.iterdir()):
                errors.append("WGS: fastqc directory is empty")

    # Check Assembly
    assembly_dir = wgs_sample_dir / "assembly"
    if not assembly_dir.exists():
        errors.append("WGS: Missing assembly directory")
    else:
        contigs = (
            list(assembly_dir.glob("*contigs.fa"))
            + list(assembly_dir.glob("*.fasta"))
            + list(assembly_dir.glob("*.fa"))
        )
        if not contigs:
            errors.append("WGS: No contigs file found in assembly directory")

    # Check QC (MAGScoT)
    qc_dir = wgs_sample_dir / "qc"
    if not qc_dir.exists():
        errors.append("WGS: Missing qc directory")
    else:
        scores = list(qc_dir.glob("*scores.out"))
        if not scores:
            errors.append("WGS: No MAGScoT scores found in qc directory")

    # Check Bins
    bins_dir = wgs_sample_dir / "bins"
    if not bins_dir.exists():
        errors.append("WGS: Missing bins directory")
    else:
        magscot_bins = bins_dir / "magscot_bins"
        if magscot_bins.exists():
            bin_files = [
                f
                for f in magscot_bins.iterdir()
                if (f.name.endswith(".fasta") or f.name.endswith(".fa"))
                and not f.name.endswith("_qc")
            ]

            # If bins exist, check for QC links
            if bin_files:
                for b in bin_files:
                    qc_link = magscot_bins / f"{b.name}_qc"
                    if not qc_link.exists():
                        errors.append(f"WGS: Missing QC link for bin {b.name}")

    return True


def main(root_path):
    root = Path(root_path)
    if not root.exists():
        print(f"Path {root} not found.")
        return

    total_samples = 0
    samples_with_16s = 0
    samples_with_wgs = 0
    samples_with_issues = 0

    missing_log = []

    sites_root = root / "sites"
    if not sites_root.exists():
        if root.name == "sites":
            sites_root = root
        else:
            print("Could not find 'sites' directory.")
            return

    for trip_dir in sorted(sites_root.iterdir()):
        if not trip_dir.is_dir():
            continue

        for site_dir in sorted(trip_dir.iterdir()):
            if not site_dir.is_dir():
                continue

            for sample_dir in sorted(site_dir.iterdir()):
                if not sample_dir.is_dir():
                    continue

                total_samples += 1
                sample_name = sample_dir.name

                errors = []
                has_16s = check_amplicon(sample_dir, errors)
                has_wgs = check_wgs(sample_dir, errors)

                if has_16s:
                    samples_with_16s += 1
                if has_wgs:
                    samples_with_wgs += 1

                if not has_16s and not has_wgs:
                    errors.append("Sample empty (No 16S or WGS folder found)")

                if errors:
                    samples_with_issues += 1
                    for err in errors:
                        missing_log.append(
                            f"{err} for {trip_dir.name} {site_dir.name} Sample {sample_name}"
                        )

    print("=== Validation Statistics ===")
    print(f"Total Samples Scanned: {total_samples}")
    print(f"Samples with 16S Data: {samples_with_16s}")
    print(f"Samples with WGS Data: {samples_with_wgs}")
    print(f"Samples with Missing/Incomplete Data: {samples_with_issues}")
    print("\n=== Detailed Missing Information ===")
    if missing_log:
        # Limit output if too long? No, user asked for all.
        for line in missing_log:
            print(line)
    else:
        print("No missing data detected!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to processed/sequencing-results")
    args = parser.parse_args()
    main(args.path)
