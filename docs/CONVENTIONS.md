# Project Conventions

This document outlines the global conventions used across the Empty Quarter project for sample naming, data organization, and identification.

## 1. Sample Naming Convention

All samples follow a standardized naming convention based on the expedition Trip number. This prefix is used consistently across field notes, metadata, sequencing files (FASTQ), and the Knowledge Graph.

| Trip Number | Year | Letter Prefix | Example Sample ID |
| :--- | :--- | :--- | :--- |
| **Trip 1** | 2023 | *None* | `61PRr1` |
| **Trip 2** | 2023 | **T** | `T1PRr3` |
| **Trip 3** | 2024 | **F** | `F21Dr1` |
| **Trip 4** | 2024 | **S** | `S41Sr2` |
| **Trip 5** | 2025 | **V** | `V1Dr1` |

### Sample ID Structure
A typical Sample ID is composed of: `[Prefix][SiteNumber][Compartment][Replicate]`

*   **Prefix**: Trip-specific letter (T, F, S, V).
*   **SiteNumber**: Numeric ID of the sampling site.
*   **Compartment**: Type of sample environment (e.g., `D` for Dune, `S` for Slack, `P` for Playa/Saline Pan).
*   **Replicate**: Replicate number (e.g., `r1`, `r2`, `r3`).

**Example:** `V32PRr1`
*   `V`: Trip 5
*   `32`: Site 32
*   `PR`: Playa (Compartment)
*   `r1`: Replicate 1

## 2. Infrastructure & Paths

*   **IBEX Root**: `/ibex/scratch/projects/c2014/EmptyQuarter_Data/`
*   **Knowledge Base**: `https://rubalkhali.science/`
*   **Primary Ontology**: `rubalkhali.owl` (using the `rak:` namespace)
