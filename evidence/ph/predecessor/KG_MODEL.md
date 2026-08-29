# Versioned soil-pH representation

## Ecology version

`EQ-PH-ECOLOGY-v1.0.0` is frozen for the amplicon ecology manuscript. The
versioned graph is validated but is not imported into the released knowledge
graph. This distinction allows the ecology analysis to remain reproducible
while a later Scientific Data release adds measurements.

## Measurement pattern

Each admitted observation follows the existing Rub al-Khali four-individual
SIO measurement pattern:

| Role | Type and links |
|---|---|
| Existing specimen | `sio:SIO_000008` to its acidity quality |
| Acidity quality | `pato:PATO_0001842`; `sio:SIO_000011` specimen; `sio:SIO_000216` value |
| pH value | `sio:SIO_000070` and `sio:SIO_001089`; `sio:SIO_000300` numeric value; `sio:SIO_000221 uo:UO_0000196`; `sio:SIO_000215` quality; `sio:SIO_000232` process |
| Measuring process | `sio:SIO_001054`; input and target specimen; output value; specified protocol; participating device; containing session; source evidence |

The protocol identifies dry soil below 2 mm, an independent 1 g scoop in
2.5 mL 0.01 M CaCl2, two-point pH 7/10 calibration, a pH-10 read-back within
0.1, slope from 95 to 102%, and automatic temperature compensation.

Process, quality and value IRIs hash the schema role, trip, specimen
identifier, accepted measurement date and protocol key. Workbook hashes and
dataset-version labels do not enter measurement identity. An unchanged
measurement can therefore retain its IRI in a successor version.

## Admission boundary

The ecology version admits 653 observations. It excludes 421 rows without a
measurement, 51 marked depleted, 36 with ambiguous dates, and seven candidate
column shifts. Excluded source rows remain in the audit table; no value is
imputed, moved between columns or silently corrected.

## Successor data-paper version

When the extended workbook arrives:

1. copy it to a new `data/metadata/samples/ph/versions/EQ-PH-DATA-*` directory
   and record its byte hash without changing the ecology source;
2. append the new version to `version_registry.tsv` with `data-paper` purpose;
3. run the generic pH generator with the successor version and a separate
   output directory;
4. compare shared measurement IRIs and values, classify additions and explicit
   revisions, and produce a cross-version membership table;
5. update the data paper's Data Records, KG module and release manifest from
   the successor version only; and
6. report any material conflict with the fixed ecology conclusions to the
   authors. Do not silently revise or conceal it.

The data paper should publish both the expanded measurement resource and the
membership of the immutable ecology-paper view.
