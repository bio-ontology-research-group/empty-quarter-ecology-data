#!/usr/bin/env bash
# Create a Zenodo draft from zenodo_metadata.json and upload every file listed in SHA256SUMS.
# Usage: ZENODO_TOKEN=... bash upload_to_zenodo.sh   (the draft stays unpublished; publish in the web UI)
set -euo pipefail
cd "$(dirname "$0")"
api=${ZENODO_API:-https://zenodo.org/api}
: "${ZENODO_TOKEN:?set ZENODO_TOKEN to a token with deposit:write}"
sha256sum -c --quiet SHA256SUMS
draft=$(curl -fsS -H "Authorization: Bearer $ZENODO_TOKEN" -H "Content-Type: application/json" \
    -X POST "$api/deposit/depositions" --data @zenodo_metadata.json)
bucket=$(printf '%s' "$draft" | python3 -c 'import json,sys; print(json.load(sys.stdin)["links"]["bucket"])')
printf '%s' "$draft" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("draft", d["id"], "reserved DOI", d["metadata"]["prereserve_doi"]["doi"])'
while read -r _ name; do
    echo "uploading $name"
    curl -fsS -H "Authorization: Bearer $ZENODO_TOKEN" --upload-file "$name" "$bucket/$name" > /dev/null
done < SHA256SUMS
echo "uploading SHA256SUMS"
curl -fsS -H "Authorization: Bearer $ZENODO_TOKEN" --upload-file SHA256SUMS "$bucket/SHA256SUMS" > /dev/null
echo "uploaded; review and publish the draft at https://zenodo.org/deposit"
