# Soil-pH dataset versions

`EQ-PH-SHARED-v1.0.0` is the frozen source used by both the amplicon ecology
paper and the Scientific Data descriptor. It contains every measurement that
was available when the measurement campaign closed on 3 August 2026. The
source is complete as available, not complete for every listed specimen:
missing, depleted, date-ambiguous and QC-incomplete rows remain explicit in the
audit table and are not imputed.

`EQ-PH-ECOLOGY-v1.0.0` is a retained predecessor snapshot. It supported the
initial ecology-paper sensitivity analysis but has been superseded for both
manuscripts at the author's request. Its workbook, normalized outputs and
analysis remain immutable provenance records and cannot be compiled into the
current papers.

Measurement IRIs depend on the specimen, measurement date and protocol rather
than on a workbook hash. An unchanged observation can therefore retain its IRI
across versions. A corrected value must be recorded as a revision with explicit
provenance; no released source snapshot or normalized table may be overwritten.

Every successor requires a cross-version comparison. Existing observations
must remain unchanged unless an explicit source correction is documented, and
the two manuscripts must identify the same current version. Future corrections
or recovered measurements require a new version rather than replacement of a
frozen source.
