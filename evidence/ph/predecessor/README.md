# Frozen ecology pH analysis

Dataset `EQ-PH-ECOLOGY-v1.0.0` is the immutable pH input for the amplicon
ecology manuscript. Its source workbook has SHA-256
`0986fdde4af4635252ead8f601e8725749228c0adf4f906e08b364801ab08398`.

Reproduce normalization, RDF generation, ecology models, manuscript-value
rendering, ShEx validation and focused tests with:

```bash
./scripts/analysis/run_ph_ecology_v1.sh
```

The workflow requires the repository `.venv`. It records exact analysis
inputs, software versions and output hashes. The ecology manuscript imports
generated values from
`empty-quarter-amplicon/generated/ph_ecology_v1_values.tex`.

pH availability is incomplete and non-random. The analysis is an
available-case environmental sensitivity, not a complete pH survey. Later
measurements belong to a successor data-paper version and cannot replace this
directory or its source snapshot.

