# Rub al Khali Ontology Design Patterns (ODP)

This document describes the design patterns, IRI schemes, and normalization rules used in the Rub al-Khali project Knowledge Graph.

## 1. Unified Namespace and Identifier Scheme

To facilitate Linked Data resolution and simplify architectural management, all entities (TBox and ABox) are unified under a single base namespace. All identifiers follow a fixed-length scheme (11 characters) to ensure consistency.

**Base Namespace**: `https://rubalkhali.science/kb/`
**Pattern**: `RAK_XNNNNNN` where `X` is a prefix character and `NNNNNN` is a 6-digit number.

| Prefix | Range / Pattern | Description |
| :--- | :--- | :--- |
| `RAK_0` | `000000 - 999999` | **TBox Classes**: Subclasses of SIO/ENVO/PATO terms. |
| `RAK_1` | `000000 - 999999` | **Sampling Sites**: Unique physical locations. |
| `RAK_2` | `000000 - 999999` | **Properties**: Custom object and data properties. |
| `RAK_3` | `000000 - 999999` | **Site Visits**: Temporal sampling events (Investigations). |
| `RAK_4` | `000000 - 999999` | **Measurement Values**: Individuals holding literal data. <br> *Note*: `300000+` reserved for XRF Values. |
| `RAK_5` | `000000 - 999999` | **Qualities**: Individuals representing measured attributes. <br> *Note*: `300000+` reserved for XRF Qualities. |
| `RAK_6` | `000000 - 999999` | **Samples**: Individual replicates or material samples. <br> *Note*: `800000+` reserved for DNA Extracts, `690000+` for DNA Libraries. |
| `RAK_7` | `000000 - 999999` | **Collections**: Groupings of samples (e.g., replicates). <br> *Note*: `790000+` reserved for FASTQ Datasets. |
| `RAK_A` | `000000 - 999999` | **Agents**: People or groups (Collectives). |
| `RAK_D` | `000000 - 999999` | **Devices**: Measurement instruments. |
| `RAK_E` | `000000 - 999999` | **Expeditions**: Large-scale sampling campaigns. |
| `RAK_F` | `000000 - 999999` | **Functions**: Capabilities of devices or agents. |
| `RAK_L` | `000000 - 999999` | **Protocols**: Formal specifications of processes. |
| `RAK_P` | `000000 - 999999` | **Processes**: Specific acts (Measuring, Sampling). <br> *Note*: `200000+` reserved for Lab Processes (DNA), `250000+` for Library Prep, `280000+` for Sequencing, `300000+` for XRF Processes. |
| `RAK_T` | `000000 - 999999` | **Time Individuals**: Time instants or intervals. |
| `RAK_GS`| `000000 - 999999` | **Generic Soil**: Placeholder soil materials (Contexts). |

### Stable IRIs for XRF Analytes
While most analyte quality classes are generated sequentially, key classes use permanent IDs:
*   **`rak:RAK_0000031`**: Light Elements mixture (Material)
*   **`rak:RAK_0000032`**: Light Elements concentration (Quality)
*   **`rak:RAK_0000033`**: Light Elements concentration measurement value (Value)

## 2. Sampling Site Pattern

Each physical sampling location is represented as a persistent individual (`RAK_1...`).
- Linked to ENVO terms using `has biome` and `has environmental feature`.
- Logic: `(property some ENVO_term)` and `(property only ENVO_term)`.

## 3. Measurement Pattern (SIO-Compliant)

Measurements follow the full SIO Observation/Measurement pattern.

### Structural Components
- **Measuring Process (`RAK_P...`)**:
    - **isPartOf**: Linked to a **Site Visit** (`RAK_3...`).
    - **hasInput** / **hasTarget**: Linked to the entity being measured (Sample, Material, or Site).
        - *Note*: XRF analysis uses `hasInput` -> Sample/Material. Environmental measurements use `hasTarget` -> Site.
    - **hasOutput**: Linked to a **Measurement Value** (`RAK_4...`).
- **Quality (`RAK_5...`)**: Typed with a specific analyte quality class.
- **Measurement Value (`RAK_4...`)**:
    - Typed with a specific analyte value class.
    - Carries literal data and `sio:hasUnit`.

### Analyte-Specific Classes
Analytes (e.g., Al, Si) have dedicated TBox classes (`RAK_0...`) linked to ChEBI via `sio:isAttributeOf`.

### XRF Normalization Logic
To account for detector sensitivity while maintaining a 100% total composition:
1.  **Extract LE**: The Light Elements (LE) percentage is taken from raw instrument data.
2.  **Correct Identified**: Identified elements are corrected using sensitivity factors.
3.  **Scale**: Corrected identified elements are scaled to fill the space not occupied by LE: `Conc_final = Conc_corrected * ((100 - LE) / 100)`.
4.  **Result**: `Sum(Final Concentrations) + LE = 100%`.

## 4. Reasoning (OWL-Horst / pD*)
Relationships are inferred using property chains and standard OWL-Horst rules. These inferences are **materialized** during the Virtuoso loading process (`load_data.sql`), expanding the knowledge base from its asserted core to a fully explicit semantic graph.

### Materialized Patterns
*   **Inverses**: `sio:SIO_000229` (has output) $\leftrightarrow$ `sio:SIO_000232` (is output of).
*   **Transitivity**: `sio:SIO_000068` (is part of).
*   **Property Chains**:
    - `isPartOf o hasTarget -> hasTarget`
    - `isMeasurementValueOf o isOutputOf o (hasInput | hasTarget) -> isAttributeOf`
    - (Quality -> Value -> Process -> Sample/Site) => (Quality isAttributeOf Sample/Site)

## 5. Labeling Conventions

- **Sites**: `Site {ID}` or `Site {Name} (location {N})`.
- **Visits**: `Visit to Site {ID} during {Expedition} on {Date} {Time}`.
- **Samples**: `Sample {ID} (Rep {N}) - {Type} from Site {ID} ({Expedition})`.

### Measurement Values
- **XRF/Analytes**: `{Analyte} measurement value ({Method}) for Site {ID}`.
- **Environmental**: `{Parameter} Measurement Value for Site {ID}`.

### Processes
- **Sampling**: `Sampling process for {Type} at Site {ID} ({Expedition})`.
- **XRF Analysis**: `{Method} analysis for Site {ID} ({Expedition})`.
- **Environmental Measurement**: `Measuring process for {Value Label}`.

## 6. DNA Extraction & Measurement Pattern
This data is generated by `scripts/generate_dna_abox.groovy` and deals with the laboratory phase of analysis.

### Entities
- **DNA Extract (`RAK_68nnnn`)**: Represents the extracted material.
  - Subclass of `sio:SIO_001173` (DNA extract).
  - Linked to original soil sample via `isDerivedFrom` (inferred) or process input/output.
- **DNA Extraction Process (`RAK_P2nnnn`)**:
  - `hasAgent`: Marwa Abdelhakim (`RAK_A000006`)
  - `hasInput`: Soil Sample (`RAK_6...`)
  - `hasOutput`: DNA Extract (`RAK_68nnnn`)
  - `isSpecifiedBy`: Extraction Protocol (e.g., `DNA_ext_powersoil`) - uses `SIO_000339`.
  - `uses DNA extraction kit`: Links to a specific kit instance (e.g., `RAK_D000004` for PowerSoil).
- **DNA Extraction Kits**:
  - Class: `DNAExtractionKit` (`RAK_000050`), subclass of `SIO_010462`.
  - Subclasses: `PowerSoilKit` (`RAK_000051`), `PowerSoilProKit` (`RAK_000052`).
  - Instances: `RAK_D000004` (PowerSoil), `RAK_D000005` (Pro).
- **DNA Concentration Measurement (`RAK_P2nnnn`)**:
  - `hasAgent`: Marwa Abdelhakim (`RAK_A000006`)
  - `hasTarget`: DNA Extract
  - `hasParticipant`: Nanodrop Device (`RAK_D000003`)
  - `hasOutput`: Concentration Quantity (`RAK_49nnnn`)
- **Concentration Quantity (`RAK_49nnnn`)**:
  - Typed as `PATO_0000033` (Concentration quality).
  - `hasDNAConcentration` (`RAK_200002`): Literal numeric value (subproperty of `hasValue`).
  - `hasUnit`: `UO_0000275` (ng/µL).
  - `isAttributeOf`: DNA Extract.

## 7. SRA Submission Data Pattern
This data is generated by `scripts/generate_sra_abox.groovy` and represents the sequencing and submission metadata.

### Entities
- **16S Amplicon Library (`RAK_69nnnn`)**:
  - Subclass of `SIO_001173` (DNA extract).
  - Represents the BioSample in SRA (cross-referenced via `rdfs:seeAlso`).
  - Output of a **Library Preparation Process**.
- **Library Preparation Process (`RAK_P25nnnn`)**:
  - Subclass of `SIO_000994` (Experiment).
  - **Inputs**: `DNA Extract` (`RAK_68nnnn`).
  - **Participants**: `Forward 16S Primer` (`RAK_DFnnnnnn`) and `Reverse 16S Primer` (`RAK_DRnnnnnn`).
  - **Protocol**: `RAK_L000010` (Illumina 16S Prep Guide).
- **Sequencing Process (`RAK_P28nnnn`)**:
  - Subclass of `SIO_000994` (Experiment).
  - **Input**: `16S Amplicon Library`.
  - **Output**: `FASTQ Dataset`.
  - **Agent**: KAUST Bioscience Corelabs (`RAK_A000020`).
  - Part of the **16S Amplicon Sequencing Project** (`RAK_E000011`).
- **FASTQ Dataset (`RAK_79nnnn`)**:
  - Subclass of `SIO_000089` (Dataset).
  - Represents the Sequencing Run (ERR) in SRA.
  - Has member only **Sequence Reads** (`RAK_000064`).

## 8. Sequencing Quality Control (MultiQC)
This data is generated by `scripts/generate_qc_abox.groovy` and represents Quality Control metrics for SRA sequencing runs (FASTQ Datasets).

### Entities
- **Sequencing QC Process (`RAK_P35nnnn`)**:
  - Subclass of `SIO_000006` (Process).
  - Represents the computational analysis (FastQC/MultiQC).
  - **Input**: `FASTQ Dataset` (`RAK_79nnnn`) from the SRA ontology.
  - **Output**: Various Measurement Values (`RAK_45nnnn`).

### Quality & Value Hierarchy
Measurements are modeled as pairs of **Quality** (PATO/RAK subclass) and **Measurement Value** (SIO/RAK subclass). Each metric is split into **Forward (R1)** and **Reverse (R2)** subclasses.

| Metric | Parent Quality (PATO) | Parent Value (SIO) | Datatype Property |
| :--- | :--- | :--- | :--- |
| **Sequence Count** | `RAK_0000071` (Amount) | `RAK_0000083` (Count) | `has sequence count` (`RAK_2000070`) |
| **GC Content** | `RAK_0000074` (Concentration) | `RAK_0000086` (Concentration) | `has GC content` (`RAK_2000073`) |
| **Duplicate Rate** | `RAK_0000077` (Proportion) | `RAK_0000089` (Quantity) | `has duplicate rate` (`RAK_2000076`) |
| **Read Length** | `RAK_0000080` (Length) | `RAK_0000092` (Length) | `has read length` (`RAK_2000079`) |

**Subclassing Pattern**:
- Every parent class (e.g., `RAK_0000071`) has two subclasses:
  - `Forward ...` (e.g., `RAK_0000072`)
  - `Reverse ...` (e.g., `RAK_0000073`)
- Instances are typed with the specific subclass (e.g., `RAK_55nnnn a RAK_0000072`).

### Relations
- **Value** `is measurement value of` **Quality**.
- **Quality** `is attribute of` **FASTQ Dataset**.
- **Value** `hasUnit` (from Unit Ontology: `%`, `count`, `bp`).