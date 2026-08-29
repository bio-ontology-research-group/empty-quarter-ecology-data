#!/bin/bash
# 1. Set the path to your Vanta .sqlite database
DB_PATH="841307.sqlite" 

# 2. Process the log file
grep "COMPLETE" metadata.tsv | awk '{
    # Iterate through columns to find the Date anchor (YYYY-MM-DD)
    for(i=1; i<=NF; i++) {
        if ($i ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/) {
            # Site is always $1
            # ID is always the column immediately before the Date (i-1)
            print $1, $(i-1)
        }
    }
}' | while read -r site id; do
    
    # 3. Define output directory structure: Site_X / Test_Y
    outdir="output/Site_${site}/Test_${id}"
    mkdir -p "$outdir"
    
    echo "Processing Test ID: $id (Site: $site) -> $outdir"
    
    # 4. Run your python parser
    uv run parse_vanta_xrf.py spectra_files/$id-1.spec --db "$DB_PATH" --id "$id" -o "$outdir"

done
