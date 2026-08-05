# Measurement reification pattern

This document codifies the canonical knowledge-graph pattern every Rub al-Khali
ABox generator MUST use to reify a measurement (XRF concentration, DNA
concentration, climate variable, sequencing QC metric, taxon abundance, …).

It is the result of a 2026-05-07 audit + refactor that fixed an
ontology-wide directional bug in `sio:is-measurement-value-of` (SIO_000215)
plus three smaller pattern divergences (DNA collapsed pattern, QC missing
inverse axioms, taxonomy ShEx using SIO_000214 instead of SIO_000216).

The end-to-end design is verified by `tests/measurement_pattern/` which runs
ELK + Jena ShEx; CI invokes this via `groovy tests/measurement_pattern/run_tests.groovy`.

## TL;DR — the four-individual split

A measurement reifies into **four** named individuals:

| Role | RAK prefix | Class hierarchy |
|---|---|---|
| **Bearer** (what the quality inheres in) | domain-specific (e.g. soil sample, DNA extract, FASTQ dataset, site) | domain class |
| **Quality** (the dispositional property being measured) | `RAK_5XXXXXX` | sub-class of `pato:0000033` (PATO concentration) or another suitable PATO quality |
| **Measurement value** (the numeric output) | `RAK_4XXXXXX` | sub-class of `sio:SIO_000070` (quantity) |
| **Measuring process** (the act of measuring) | `RAK_PXXXXXX` | sub-class of `sio:SIO_001054` (measuring) |

The literal value (`xsd:double` etc.) and the unit (`uo:…`) live on the
**measurement value**, never on the quality. The quality is a BFO-realist
quality individual that *inheres in* the bearer; the value is its numeric
record produced by the process.

## SIO direction conventions (canonical, do not invert)

| SIO IRI | Label | Subject → Object |
|---|---|---|
| `SIO_000008` | has attribute | bearer → quality |
| `SIO_000011` | is attribute of | quality → bearer |
| `SIO_000215` | **is measurement value of** | **value → quality** (value is subject) |
| `SIO_000216` | **has measurement value** | **quality → value** (quality is subject; inverse of 215) |
| `SIO_000229` | has output | process → value |
| `SIO_000232` | is output of | value → process |
| `SIO_000291` | has target | process → bearer |
| `SIO_000221` | has unit | value → unit individual |

Three SIO sub-properties commonly appear alongside, equally directional:

- `SIO_000217` "has quality" / `SIO_000218` "is quality of" — for non-measurement quality bearings (e.g. QC qualities of a FASTQ dataset).
- `SIO_000300` "has value" — parent of all RAK numeric data properties.

## ABox: every assertion that must be made per measurement

Given individuals `bearer`, `quality`, `value`, `process`:

```turtle
# Class assertions (domain-specific subclasses)
quality   a   <rak:DomainQualityClass>     .   # ⊑ pato:0000033 (or analogue)
value     a   <rak:DomainValueClass>       .   # ⊑ sio:SIO_000070
process   a   <rak:DomainMeasuringProcess> .   # ⊑ sio:SIO_001054

# Bidirectional bearer ↔ quality (BFO-realist inherence)
bearer    sio:SIO_000008  quality .            # has attribute
quality   sio:SIO_000011  bearer  .            # is attribute of

# Bidirectional quality ↔ value (the SIO measurement-value pair)
value     sio:SIO_000215  quality .            # is measurement value of   (CANONICAL DIRECTION)
quality   sio:SIO_000216  value   .            # has measurement value     (inverse)

# Bidirectional process ↔ value
process   sio:SIO_000229  value   .            # has output
value     sio:SIO_000232  process .            # is output of

# Process targets the bearer
process   sio:SIO_000291  bearer  .            # has target

# Numeric payload + unit on the VALUE (never on the quality)
value     <rak:has-some-value>  "10.5"^^xsd:double .
value     sio:SIO_000221       <uo:0000275>      .   # e.g. ng/uL
```

**Every direction must be asserted directly.** ELK 0.4.3 (the project's
deployment-gate reasoner) is OWL 2 EL — it has no inverse-property reasoning,
so do not rely on `owl:inverseOf` to materialise the reverse triple.
Asserting both directions also makes the data robust under SPARQL queries
that traverse either direction without needing inference.

## TBox property chain

`scripts/rdf/update_rubalkhali_ontology.groovy` declares two chains so that
`isAttributeOf` between the quality and the bearer can be derived from the
process structure even when not asserted directly:

```
hasMeasurementValue ∘ isOutputOf ∘ hasTarget  ⊑  isAttributeOf
hasMeasurementValue ∘ isOutputOf ∘ hasInput   ⊑  isAttributeOf
```

Read at the class level: `Quality ⊑ ∃isAttributeOf.Bearer` is derivable
through the chain. The validation harness verifies this against ELK by
adding `Quality ⊑ ∃hasMeasurementValue.MeasurementValue`,
`MeasurementValue ⊑ ∃isOutputOf.MeasuringProcess`,
`MeasuringProcess ⊑ ∃hasTarget.Bearer` to the test TBox and asserting
`Quality` becomes a subclass of `∃isAttributeOf.Bearer`.

The chain MUST start with `SIO_000216` (has-measurement-value), NOT
`SIO_000215`. Prior to 2026-05-07 the chain used `SIO_000215`, which only
fired under the (incorrect) reversed-direction ABox usage that XRF and
measurements had at the time.

## ShEx schema

Every per-domain schema in `data/processed/semantics/shex/*.shex` follows
this template (see `tests/measurement_pattern/measurement.shex` for the
reference). Two important Jena-ShEx-specific gotchas, observed during the
2026-05-07 refactor:

1. **`rdf:type IRI ;` defaults to cardinality {1,1}** — but most KG
   individuals carry both a domain class and `owl:NamedIndividual`. Always
   write `rdf:type IRI +` (or use `EXTRA rdf:type` with a single-cardinality
   constraint) so the multi-type case validates.
2. **Mutual recursion (Value↔Quality) does not validate reliably in
   Jena ShEx 4.10.** Enforce the link from one side only — validate
   `Value sio:SIO_000215 @<#QualityShape>` going forward, but use
   `IRI` (not `@<#ValueShape>`) for the reverse check.

## Per-domain TBox classes

| Domain | Quality class | Value class | Process class |
|---|---|---|---|
| XRF (per analyte) | `RAK_0000100`–`191` ⊑ `RAK_0000029` ⊑ `pato:0000033` | `RAK_0000500`–`591` ⊑ `RAK_0000030` ⊑ `sio:SIO_000070` | `RAK_0000025` |
| Climate (temp / pressure / humidity / annual) | `pato:0000146`, `envo:00002005`, etc. | `RAK_0000010`–`15` ⊑ `sio:SIO_000070` | `RAK_0000006`–`9` |
| **DNA concentration (NEW 2026-05-07)** | **`RAK_0000043`** ⊑ `pato:0000033` | **`RAK_0000044`** ⊑ `sio:SIO_000070` | `RAK_0000041` |
| Sequencing QC | `RAK_0000201`–`212` (qualities) | `RAK_0000213`–`224` (values) | `RAK_0000200` |
| Taxon abundance (absolute) | `RAK_0000078` | `RAK_0000076` | `RAK_0000071` (workflow) |
| Taxon abundance (relative) | `RAK_0000072` | `RAK_0000073` | `RAK_0000071` (workflow) |

(See `scripts/validation/check_iri_registry.py` for the full IRI registry.)

## Historical fix log

- **2026-05-07** — codebase-wide direction repair:
  - Flipped 6 ABox assertion sites in `generate_xrf_abox.groovy` and
    `generate_measurements_abox.groovy` from quality→value to value→quality.
  - Added inverse `hasMeasurementValue` (`SIO_000216`) assertions everywhere.
  - Rewrote DNA generator from collapsed (single PATO:0000033 individual) to
    full split (RAK_0000043 quality + RAK_0000044 value).
  - Patched `generate_qc_abox.groovy` to add the missing
    `process↔value isOutputOf` and `dataset↔quality hasAttribute`
    bidirectional assertions.
  - Replaced taxonomy generator's spurious `SIO_000214` (which is
    "is concretization of") with the correct `SIO_000216`.
  - Rewrote the TBox property chain to use `SIO_000216` as head.
  - Updated 6 SPARQL queries (backend + tests + validators + frontend
    presets) to use the canonical direction.
  - Updated DNA / measurements / XRF / QC ShEx schemas to enforce the
    canonical pattern.
  - Added `tests/measurement_pattern/` validation harness (ELK +
    ShEx + reverse-direction negative test).
