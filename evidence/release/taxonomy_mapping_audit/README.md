# Taxonomy mapping audit bundle

The files listed in `SHA256SUMS` are the outputs of the passing canonical
Trips 1--5 taxonomy build. Regenerate them through the Nextflow
`BUILD_TAXONOMY_MAPPING` process; do not edit them manually.

`historical_taxonomy_mapping_violations.tsv` is retained separately as
evidence for why the former mapping was retired. Its 46 findings describe
the historical input, not failures of the corrected mapping, and it is
intentionally outside the generated PASS checksum set.

The historical audit can be reproduced in a separate directory with:

```bash
python scripts/validation/audit_taxonomy_mapping.py \
  --mapping data/processed/ontology/mapped_taxonomy.tsv \
  --ncbi-taxonomy data/ontologies/ncbitaxon.owl \
  --output-dir /tmp/historical-taxonomy-audit
```
