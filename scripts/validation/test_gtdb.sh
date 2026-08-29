#!/bin/bash
module load gtdb-tk/2.6.1

echo "Testing GTDB-Tk..."

: "${GTDBTK_REFERENCE_ROOT:?Set GTDBTK_REFERENCE_ROOT to the directory containing release226, release220 and/or release214}"
for release in release226 release220 release214; do
    export GTDBTK_DATA_PATH="$GTDBTK_REFERENCE_ROOT/$release"
    echo "Trying $GTDBTK_DATA_PATH"
    if [[ -d "$GTDBTK_DATA_PATH" ]] && gtdbtk check_install; then
        echo "SUCCESS: $release"
        exit 0
    fi
    echo "FAILED: $release"
done

echo "ALL FAILED"
