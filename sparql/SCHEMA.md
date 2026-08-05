# Rub al Khali Knowledge Base Schema

This document outlines the types of information represented in the Rub al-Khali Knowledge Base and how they are semantically connected.

## 1. Overview
The Knowledge Base (KB) is a Linked Data graph built on the **Semantic Science Integrated Ontology (SIO)** and **Environment Ontology (ENVO)**. It integrates geographic, temporal, procedural, and chemical information into a unified structure.

## 2. Core Entities (The Nodes)

### Geography & Environment
*   **Sampling Site (`RAK_1...`)**: A physical location in the Rub' al Khali. Contains averaged GPS coordinates (`geo:asWKT`) and links to ENVO biomes and features.

### The Expeditionary Hierarchy
*   **Expedition (`RAK_E...`)**: A high-level scientific campaign (e.g., Trip 1).
*   **Site Visit (`RAK_3...`)**: A specific event where scientific activities occurred at a Site during an Expedition.
*   **Agent (`RAK_A...`)**: The "who". Includes **Persons** and **Collectives** (Expedition Teams).

### Biological & Geological Materials
*   **Sample (`RAK_6...`)**: Physical material collected (Surface Soil, Deep Soil, Rhizosphere, Plant Matter). Includes unique project identifiers (`dc:identifier`).
*   **DNA Extract (`RAK_68nnnn`)**: Purified DNA material extracted from a soil sample.
*   **Collection of Replicates (`RAK_7...`)**: A group of samples of the same type collected together.
*   **Light Elements mixture (`rak:RAK_0000031`)**: Geochemical portion not identified by individual XRF peaks.

### Scientific Measurements
*   **Measuring Process (`RAK_P...`)**: The act of taking a measurement (XRF, Temperature, etc.).
*   **DNA Extraction (`RAK_P2nnnn`)**: The laboratory process of isolating DNA from a sample.
*   **DNA Concentration Measurement (`RAK_P2nnnn`)**: Quantifying the amount of DNA in an extract using a Nanodrop.
*   **Library Preparation Process (`RAK_0000065`)**: Constructing sequencing libraries from DNA extracts.
*   **Sequencing Process (`RAK_0000066`)**: Generating raw read data from prepared libraries.
*   **Measurement Value (`RAK_4...`)**: The numerical result of a measurement (Literal value + Unit).
*   **Quality (`RAK_5...`)**: The specific attribute being measured (e.g., Silicon concentration).
*   **Device (`RAK_D...`)**: The instrument used (Vanta XRF, Testo Thermometer).
*   **Protocol (`RAK_L...`)**: The formal specification followed (Field vs. Lab protocols).

## 3. Key Connections (The Edges)

### Provenance & Hierarchy
*   `Site Visit` — **isPartOf** —> `Expedition`
*   `Measuring/Sampling Process` — **isPartOf** —> `Site Visit`
*   `Site Visit` — **hasTarget** —> `Sampling Site`

### Material Derivation
*   `Sample` — **isDerivedFrom** —> `Sampling Site`
*   `Collection` — **hasMember** —> `Sample`
*   `Sampling Process` — **hasOutput** —> `Collection`

### The Measurement Pattern (Full SIO)
The KB follows a rigorous pattern to separate the process from the result. Note the direction of the `isMeasurementValueOf` property (Quality -> Value) and `hasAttribute` (Sample -> Quality).

1.  **Process** (`RAK_P...`)
    *   **hasAgent**: `Expedition Team` or `Person`
    *   **hasParticipant**: `Device`
    *   **hasInput**: `Sample`, `Generic Soil` (field context), `Light Elements mixture`, or `Site`
    *   **isSpecifiedBy**: `Protocol`
    *   **hasOutput**: `Measurement Value`
    *   **isPartOf**: `Site Visit`
2.  **Measurement Value** (`RAK_4...`)
    *   **isOutputOf**: `Process`
    *   **hasUnit**: `UO_...` (e.g., percent, Celsius)
    *   **hasConcValue**: Literal (Double) - The measured numeric value.
    *   **hasConcError**: Literal (Double) - The margin of error (if available).
3.  **Quality** (`RAK_5...`)
    *   **isMeasurementValueOf**: `Measurement Value` (Asserted direction: Quality describes the Value)
    *   **isAttributeOf**: `Sample` or `Site` (Inferred from `Sample hasAttribute Quality`)
4.  **Sample/Site**
    *   **hasAttribute**: `Quality` (Asserted)

## 4. Inferred Relationships (Materialized)
The KB uses **OWL-Horst** and **Property Chains** to simplify queries. These are materialized during load, meaning direct links are explicitly stored in the database:
*   **Target Propagation**: If a Process is part of a Visit that targets a Site, the Process also **targets** that Site.
*   **Quality Attribution**: If a Quality has a Value that is the output of a Process that has a specific Input (Sample), the Quality is automatically linked as an **attribute of** that Sample.
*   **Symmetry & Inverses**: Inverse properties (e.g., `has output` / `is output of`) are expanded so queries work in both directions.
*   **Transitive Provenance**: `isPartOf` is expanded transitively, allowing a Process to be traced all the way back to its parent `Expedition`.

## 5. Naming & IRI Scheme
All project entities use the fixed-length pattern: `https://rubalkhali.science/kb/RAK_XNNNNNN`.
See [ODP.md](./ODP.md) for the full prefix and numbering reference.

## 6. Data Validation (ShEx)
The Knowledge Base is validated against Shape Expressions (ShEx) definitions located in `data/processed/shex/`. These shapes enforce strict structural constraints on the RDF data.

### 6.1 Sites (`sites.shex`)
*   **SamplingSiteShape**: Ensures every site has an IRI, label, description, and WKT Point geometry.
*   **RegionShape**: Ensures the Rub' al Khali region is defined as a Desert with a Polygon WKT.

### 6.2 Samples (`samples.shex`)
*   **SamplingProcessShape**: Must target a Site and output a Collection.
*   **CollectionShape**: Must contain at least one Sample member.
*   **SampleShape**: Must be derived from a Site and have a unique `dc:identifier`.

### 6.3 Measurements (`measurements.shex`)
*   **ExpeditionShape**: Must have a Team agent and optional Time interval.
*   **VisitShape**: Must target a Site and be part of an Expedition.
*   **MeasurementProcessShape**: Defines structure for Temp, Pressure, Humidity, and Annual climate measurements.
*   **MeasurementValueShape**: Enforces correct Data Types (Double) and Units (UO) for each measurement type.

### 6.4 DNA (`dna.shex`)
*   **DNAExtractShape**: Must have a Concentration attribute.
*   **ExtractionProcessShape**: Must input a Soil Sample and output a DNA Extract.
*   **ConcentrationShape**: Enforces value and unit (`ng/uL`) for DNA concentration.

### 6.5 XRF (`xrf.shex`)
*   **XRFProcessShape**: Must input a Soil Sample, reference a Protocol, and output multiple Values.
    *   **Process ID**: `RAK_P3nnnnn`
*   **XRFValueShape**: Enforces `hasConcValue` (Double), optional Error, and Unit (`percent`).
    *   **Value ID**: `RAK_43nnnnn`
    *   **Quality ID**: `RAK_53nnnnn`

### 6.6 SRA Data (`sra.shex`)
*   **LibraryShape**: Subclass of DNA extract, has cross-reference to BioSample.
*   **LibraryPrepShape**: Experiment that inputs DNA Extract, uses Primers, specified by Protocol, outputs Library.
*   **SequencingShape**: Experiment that inputs Library, part of 16S Project, outputs FASTQ Dataset.
*   **FASTQDatasetShape**: Dataset cross-referenced to SRA Run, contains Sequence Reads.

### 6.7 Taxonomy Analysis (`taxonomy.shex`)
*   **BioinformaticWorkflowShape**: Process that inputs a FASTQ Dataset and outputs Relative Abundance values.
    *   **Process ID**: `RAK_P29nnnn`
*   **RelativeAbundanceValueShape**: Enforces `hasRelativeAbundanceValue` (Double) and links to a Quality.
    *   **Value ID**: `RAK_44nnnn`
*   **RelativeAbundanceQualityShape**: Individual describing the abundance of a specific Taxon in a Dataset.
    *   **Quality ID**: `RAK_54nnnn`

| `RAK_0000063` | FASTQ Dataset | `sio:SIO_000089` |
| `RAK_0000065` | Library Preparation Process | `sio:SIO_000994` |
| `RAK_0000066` | Sequencing Process | `sio:SIO_000994` |

### Sequencing QC (MultiQC)

**Classes**

| IRI | Label | Parent Class |
| :--- | :--- | :--- |
| `RAK_0000070` | Sequencing QC Process | `sio:SIO_000006` |
| `RAK_0000071` | Sequence Count Quality | `pato:PATO_0000070` |
| `RAK_0000072` | Forward Sequence Count Quality | `RAK_0000071` |
| `RAK_0000073` | Reverse Sequence Count Quality | `RAK_0000071` |
| `RAK_0000074` | GC Content Quality | `pato:PATO_0000033` |
| `RAK_0000075` | Forward GC Content Quality | `RAK_0000074` |
| `RAK_0000076` | Reverse GC Content Quality | `RAK_0000074` |
| `RAK_0000077` | Duplicate Rate Quality | `pato:PATO_0001470` |
| `RAK_0000078` | Forward Duplicate Rate Quality | `RAK_0000077` |
| `RAK_0000079` | Reverse Duplicate Rate Quality | `RAK_0000077` |
| `RAK_0000080` | Read Length Quality | `pato:PATO_0000122` |
| `RAK_0000081` | Forward Read Length Quality | `RAK_0000080` |
| `RAK_0000082` | Reverse Read Length Quality | `RAK_0000080` |
| `RAK_0000083` | Sequence Count Value | `sio:SIO_000794` |
| `RAK_0000084` | Forward Sequence Count Value | `RAK_0000083` |
| `RAK_0000085` | Reverse Sequence Count Value | `RAK_0000083` |
| `RAK_0000086` | GC Content Value | `sio:SIO_001088` |
| `RAK_0000087` | Forward GC Content Value | `RAK_0000086` |
| `RAK_0000088` | Reverse GC Content Value | `RAK_0000086` |
| `RAK_0000089` | Duplicate Rate Value | `sio:SIO_000052` |
| `RAK_0000090` | Forward Duplicate Rate Value | `RAK_0000089` |
| `RAK_0000091` | Reverse Duplicate Rate Value | `RAK_0000089` |
| `RAK_0000092` | Read Length Value | `sio:SIO_000041` |
| `RAK_0000093` | Forward Read Length Value | `RAK_0000092` |
| `RAK_0000094` | Reverse Read Length Value | `RAK_0000092` |

**Data Properties**

| IRI | Label | Range |
| :--- | :--- | :--- |
| `RAK_2000070` | has sequence count | `xsd:int` |
| `RAK_2000071` | has forward sequence count | `xsd:int` |
| `RAK_2000072` | has reverse sequence count | `xsd:int` |
| `RAK_2000073` | has GC content | `xsd:float` |
| `RAK_2000074` | has forward GC content | `xsd:float` |
| `RAK_2000075` | has reverse GC content | `xsd:float` |
| `RAK_2000076` | has duplicate rate | `xsd:float` |
| `RAK_2000077` | has forward duplicate rate | `xsd:float` |
| `RAK_2000078` | has reverse duplicate rate | `xsd:float` |
| `RAK_2000079` | has read length | `xsd:float` |
| `RAK_2000080` | has forward read length | `xsd:float` |
| `RAK_2000081` | has reverse read length | `xsd:float` |

