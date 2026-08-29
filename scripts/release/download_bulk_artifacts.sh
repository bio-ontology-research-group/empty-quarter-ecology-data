#!/usr/bin/env bash
set -euo pipefail

repo=${EQ_DATA_REPO:-bio-ontology-research-group/empty-quarter-data-paper}
tag=${EQ_DATA_RELEASE_TAG:-v0.6.0-rc32}
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
asset_dir=$(mktemp -d)
trap 'rm -rf "$asset_dir"' EXIT

command -v gh >/dev/null 2>&1 || {
  echo "gh is required to download the private pre-release" >&2
  exit 69
}

gh release download "$tag" --repo "$repo" --dir "$asset_dir" \
  --pattern 'feature-table-trips1-5.tsv.gz' \
  --pattern 'ASV_seqs-trips1-5.fasta.gz' \
  --pattern 'feature-table.tsv.gz' \
  --pattern 'feature_table_filtered_normalized.tsv.gz' \
  --pattern 'feature_table_filtered_raw_w_reps.tsv.gz' \
  --pattern 'eq.emapper.annotations.gz' \
  --pattern 'measured_function_inputs.tar.gz' \
  --pattern 'chebi.owl.gz' \
  --pattern 'ncbitaxon.owl.gz'

install_gzip() {
  local asset=$1
  local destination=$2
  local expected_bytes=$3
  local expected_sha=$4
  mkdir -p "$(dirname "$destination")"
  if [[ -e "$destination" ]]; then
    local observed_bytes observed_sha
    observed_bytes=$(stat -c '%s' "$destination")
    observed_sha=$(sha256sum "$destination" | cut -d' ' -f1)
    if [[ "$observed_bytes" == "$expected_bytes" && "$observed_sha" == "$expected_sha" ]]; then
      return
    fi
    echo "refusing to replace non-matching file: $destination" >&2
    exit 73
  fi
  gzip -dc "$asset_dir/$asset" > "$destination.partial"
  local observed_bytes observed_sha
  observed_bytes=$(stat -c '%s' "$destination.partial")
  observed_sha=$(sha256sum "$destination.partial" | cut -d' ' -f1)
  if [[ "$observed_bytes" != "$expected_bytes" || "$observed_sha" != "$expected_sha" ]]; then
    rm -f "$destination.partial"
    echo "bulk artifact failed verification: $asset" >&2
    exit 65
  fi
  mv "$destination.partial" "$destination"
}

install_exact() {
  local asset=$1
  local destination=$2
  local expected_bytes=$3
  local expected_sha=$4
  mkdir -p "$(dirname "$destination")"
  if [[ -e "$destination" ]]; then
    local observed_bytes observed_sha
    observed_bytes=$(stat -c '%s' "$destination")
    observed_sha=$(sha256sum "$destination" | cut -d' ' -f1)
    if [[ "$observed_bytes" == "$expected_bytes" && "$observed_sha" == "$expected_sha" ]]; then
      return
    fi
    echo "refusing to replace non-matching file: $destination" >&2
    exit 73
  fi
  cp "$asset_dir/$asset" "$destination.partial"
  local observed_bytes observed_sha
  observed_bytes=$(stat -c '%s' "$destination.partial")
  observed_sha=$(sha256sum "$destination.partial" | cut -d' ' -f1)
  if [[ "$observed_bytes" != "$expected_bytes" || "$observed_sha" != "$expected_sha" ]]; then
    rm -f "$destination.partial"
    echo "bulk artifact failed verification: $asset" >&2
    exit 65
  fi
  mv "$destination.partial" "$destination"
}

install_gzip feature-table-trips1-5.tsv.gz \
  "$root/metadata/taxonomy/feature-table-trips1-5.tsv" \
  1801512613 129f47d8f0db8d9afd6f8c67b8d80b5bead90155d8c91d2f43ea6a4139b0cb12
install_gzip ASV_seqs-trips1-5.fasta.gz \
  "$root/metadata/taxonomy/ASV_seqs-trips1-5.fasta" \
  161872009 7b2b6f23a0d80ca004f730b164b9b9b4514aafcb23f8e2019e1d2d3216b88854
install_gzip feature-table.tsv.gz \
  "$root/metadata/taxonomy/feature-table.tsv" \
  262910985 0d13260637e4974072f9efbfad9518a83dfea89cbda2a4a573641fde8dea1b78
install_gzip feature_table_filtered_normalized.tsv.gz \
  "$root/metadata/taxonomy/feature_table_filtered_normalized.tsv" \
  164240448 df5bfbcf21c14c257128294d66a80fcc27e6002c2c8b397bf3a71f3250d60a3e
install_gzip feature_table_filtered_raw_w_reps.tsv.gz \
  "$root/metadata/taxonomy/feature_table_filtered_raw_w_reps.tsv" \
  257774199 cdf236fdeb5f539c6d39cb7f2c48f0aa5e83e82a0f06bd267f91545f63b769a6
install_exact eq.emapper.annotations.gz \
  "$root/metadata/metagenome/eq.emapper.annotations.gz" \
  338664615 b79dc4827d1908af7aef724dbf6904187aa119890d10fe3abd313dee36ed77d6
install_exact measured_function_inputs.tar.gz \
  "$root/metadata/metagenome/measured_function_inputs.tar.gz" \
  120244429 08d8b84ab7331e8bcc62fa6cf0539e4008e6399a39c4bb4f9da5fde3b29bd46a
install_gzip chebi.owl.gz "$root/data/ontologies/chebi.owl" \
  810108957 75679f3e08dec31f926c56b29ef251bbde91236b19c428bf561743d9db8f8cb7
install_gzip ncbitaxon.owl.gz "$root/data/ontologies/ncbitaxon.owl" \
  1646833334 5238897945e50ceb9007a1f96f40d1e8774456c3a0d691292fe7e8e9b5b1287d

python3 "$root/scripts/release/verify_repository.py" "$root" --require-bulk
printf 'PASS: verified bulk artifacts from %s/%s\n' "$repo" "$tag"
