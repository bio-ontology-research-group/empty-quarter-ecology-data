# SPARQL Queries for Rub al-Khali Knowledge Base

This document provides example SPARQL queries to extract data from the knowledge base, specifically tailored to the schema described in `SCHEMA.md` and `ODP.md`.

## Prefixes
Standard prefixes used in these queries:

```sparql
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX uo: <http://purl.obolibrary.org/obo/UO_>
```

**Note on Inference**: Most scientific relationships (inverses, property chains, transitivity) are **materialized** during the data loading process. This means you generally do not need to use `define input:inference "..."` pragmas in your queries to see inferred links.

## 1. Retrieve Field XRF Measurement for Site 10
This query retrieves the Field XRF measurement data specifically for Site 10. It distinguishes between different test runs by including the process label.

```sparql
SELECT ?processLabel ?analyte ?concentration ?error ?unitLabel
WHERE {
  # 1. Identify the Sample
  ?sample a rak:RAK_0000021 ;
          rdfs:label ?sampleLabel .
  FILTER(REGEX(?sampleLabel, "Site 10"))

  # 2. Get the Process (Test Run)
  ?value sio:SIO_000232 ?process . 
  ?process rdfs:label ?processLabel .
  FILTER(REGEX(?processLabel, "Field", "i"))

  # 3. Get the Measurement Value and Quality
  ?sample sio:SIO_000008 ?quality .
  ?quality sio:SIO_000215 ?value .

  # 4. Extract Data
  ?value rak:RAK_2000012 ?concentration . 
  OPTIONAL { ?value rak:RAK_2000013 ?error . } 
  ?value sio:SIO_000221 ?unit .
  ?unit rdfs:label ?unitLabel .

  # 5. Get Analyte Name
  ?quality a ?qualityClass .
  ?qualityClass rdfs:label ?analyte .
  FILTER(?qualityClass != rak:RAK_0000029) 
}
ORDER BY ?processLabel ?analyte
LIMIT 100
```

## 2. List all Sampling Sites and their Coordinates
Retrieves all entities typed as Sampling Site (`RAK_0000002`) and their GPS coordinates.

```sparql
SELECT ?site ?label ?wkt
WHERE {
  # RAK_0000002 = Sampling Site Class
  ?site a rak:RAK_0000002 ;
        rdfs:label ?label .
  
  # Coordinates are stored as Annotation Property geo:asWKT
  OPTIONAL {
    ?site geo:asWKT ?wkt .
  }
}
ORDER BY ?label
```

## 3. List all Biomes associated with Sites
Retrieves the ENVO biome names linked to sampling sites. It inspects the OWL restrictions used to assert these relationships.

```sparql
SELECT DISTINCT ?siteLabel ?biomeLabel
WHERE {
  ?site a rak:RAK_0000002 ;
        rdfs:label ?siteLabel .
  
  # Navigate OWL restrictions: Site -> type -> [onProperty hasBiome; someValuesFrom BiomeClass]
  ?site a [
    a owl:Restriction ;
    owl:onProperty rak:RAK_2000001 ;
    owl:someValuesFrom ?biomeClass
  ] .
  ?biomeClass rdfs:label ?biomeLabel .
}
ORDER BY ?siteLabel
```

## 4. Retrieve Light Elements (LE) Percentages for all Tests
Retrieves the estimated percentage of Light Elements across all XRF test runs.

```sparql
SELECT ?processLabel ?lePercentage
WHERE {
  # RAK_0000032 = Light Elements concentration class
  ?quality a rak:RAK_0000032 .
  
  # 2. Get the linked measurement value
  ?quality sio:SIO_000215 ?value .
  
  # 3. Extract the percentage
  ?value rak:RAK_2000012 ?lePercentage .
  
  # 4. Link to the specific test run
  ?value sio:SIO_000232 ?process .
  ?process rdfs:label ?processLabel .
}
ORDER BY DESC(?lePercentage)
```

## 5. Retrieve DNA Extraction and Concentration Data
Retrieves DNA extracts, their source soil samples, the extraction agent, protocol, kit used, and the measured concentration.

```sparql
SELECT ?soilSampleLabel ?dnaExtractLabel ?agentLabel ?protocolLabel ?kitLabel ?concentrationValue
WHERE {
  # 1. Start from DNA Extract
  ?dnaExtract a rak:RAK_0000040 ;
              rdfs:label ?dnaExtractLabel .

  # 2. Link back to DNA Extraction Process and Soil Sample
  ?extProcess sio:SIO_000229 ?dnaExtract ;
              sio:SIO_000230 ?soilSample ;
              sio:SIO_000139 ?agent .
  ?soilSample rdfs:label ?soilSampleLabel .
  ?agent rdfs:label ?agentLabel .

  # 3. Optional Protocol and Kit
  OPTIONAL {
    ?extProcess sio:SIO_000339 ?protocol .
    ?protocol rdfs:label ?protocolLabel .
  }
  OPTIONAL {
    ?extProcess rak:RAK_2000014 ?kit .
    ?kit rdfs:label ?kitLabel .
  }

  # 4. Get DNA Concentration Measurement
  OPTIONAL {
    ?measProcess sio:SIO_000291 ?dnaExtract ;
                 sio:SIO_000229 ?quantity .
    ?quantity rak:RAK_2000015 ?concentrationValue .
  }
}
ORDER BY ?soilSampleLabel
```

## 6. Trace Provenance from Soil Sample to Sequencing Run (SRA)

This query traces the full lineage: Soil Sample -> DNA Extract -> 16S Library -> Sequencing Run (ERR) and BioSample (ERS).



```sparql

PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

PREFIX sio: <http://semanticscience.org/resource/>

PREFIX rak: <https://rubalkhali.science/kb/>



SELECT ?soilSample ?library ?bioSample ?run

WHERE {

  # 1. Soil Sample to DNA Extract

  ?extProcess sio:SIO_000230 ?soilInd ;

              sio:SIO_000229 ?dnaInd .

  ?soilInd rdfs:label ?soilSample .



  # 2. DNA Extract to 16S Library

  ?libPrep sio:SIO_000230 ?dnaInd ;

           sio:SIO_000229 ?libInd .

  ?libInd rdfs:label ?library ;

          rdfs:seeAlso ?bioSample .



  # 3. 16S Library to FASTQ Dataset (Run)

  ?seqProcess sio:SIO_000230 ?libInd ;

              sio:SIO_000229 ?fastqInd .

  ?fastqInd rdfs:seeAlso ?run .

}

ORDER BY ?soilSample

LIMIT 5

```



### Validation Results (Sample Output)

| soilSample | library | bioSample | run |

|:---|:---|:---|:---|

| Sample 10Dr1 (Rep 1) ... | 10Dr1_amp_lib1 | ERS28393004 | ERR16062319 |

| Sample 10Dr2 (Rep 2) ... | 10Dr2_amp_lib1 | ERS28393005 | ERR16062320 |

| Sample 10PRr2 (Rep 2)... | 10PRr2_amp_lib1 | ERS28393008 | ERR16062323 |

| Sample 10PRr3 (Rep 3)... | 10PRr3_amp_lib1 | ERS28393009 | ERR16062324 |

| Sample 10Sr2 (Rep 2) ... | 10Sr2_amp_lib1 | ERS28393008 | ERR16062321 |

## 7. Retrieve Taxonomic Composition and Abundance
Retrieves the absolute and relative abundance of taxa within specific sequencing datasets (runs).

```sparql
SELECT DISTINCT ?run ?taxonLabel ?count ?relativeAbundance
WHERE {
  # 1. Identify the Process and its Dataset outputs
  ?proc a rak:RAK_0000071 ;
        sio:SIO_000230 ?fastq ;
        sio:SIO_000229 ?dsAbs , ?dsRel .
  
  ?dsAbs a rak:RAK_0000074 . # Taxon absolute abundance measurement dataset
  ?dsRel a rak:RAK_0000075 . # Taxon relative abundance measurement dataset
  
  ?fastq rdfs:label ?runLabel .
  BIND(REPLACE(?runLabel, "FASTQ dataset for ", "") AS ?run)

  # 2. Get Absolute Abundance
  ?dsAbs sio:SIO_000059 ?valAbs .
  ?valAbs rak:RAK_2000021 ?count .
  
  # 3. Get Relative Abundance (linked via the same taxon quality)
  ?valAbs sio:SIO_000215 ?qualAbs .
  ?qualAbs sio:SIO_000011 ?taxon .
  ?taxon rdfs:label ?taxonLabel .
  
  # Link to relative abundance using the taxon attribute
  ?qualRel sio:SIO_000011 ?taxon ;
           a rak:RAK_0000072 ; # taxon relative abundance quality
           sio:SIO_000214 ?valRel .
  ?valRel rak:RAK_2000020 ?relativeAbundance .

  FILTER(?taxon != ?fastq)
}
ORDER BY ?run DESC(?count)
LIMIT 100
```

## 8. Reproduce Taxon Table for a specific Sample
This query reproduces the full list of taxa and their counts for a single sample (e.g., `10Dr2`).

```sparql
SELECT DISTINCT ?taxonLabel ?count ?relativeAbundance
WHERE {
  # 1. Identify the FASTQ dataset
  ?fastq rdfs:label "FASTQ dataset for ERR16062320" .
  
  # 2. Identify the Absolute Abundance Value through its Quality
  ?qualAbs sio:SIO_000011 ?fastq ;
           a rak:RAK_0000078 ; # taxon absolute abundance quality
           sio:SIO_000214 ?valAbs .
  ?valAbs rak:RAK_2000021 ?count .
  
  # 3. Identify the Taxon
  ?qualAbs sio:SIO_000011 ?taxon .
  ?taxon rdfs:label ?taxonLabel .
  
  # 4. Link to Relative Abundance
  ?qualRel sio:SIO_000011 ?taxon ;
           sio:SIO_000011 ?fastq ;
           a rak:RAK_0000072 ; # taxon relative abundance quality
           sio:SIO_000214 ?valRel .
  ?valRel rak:RAK_2000020 ?relativeAbundance .

  FILTER(?taxon != ?fastq)
}
ORDER BY DESC(?count)
```

## 9. Query Sequencing QC Metrics
Retrieves MultiQC data (GC content and Read Count) for a specific sample (e.g., `10Dr2`).

```sparql
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?datasetLabel ?metric ?value ?unit
WHERE {
  # 1. Find the FASTQ Dataset for the sample
  ?dataset a rak:RAK_0000063 ;
           rdfs:label ?datasetLabel .
  FILTER(CONTAINS(?datasetLabel, "10Dr2"))

  # 2. Find attributes (Qualities) of the dataset
  ?quality sio:SIO_000218 ?dataset ;
           a ?qualityType ;
           rdfs:label ?metric .

  # 3. Find Measurement Values of those qualities
  ?measure sio:SIO_000215 ?quality ;
           sio:SIO_000221 ?unitEntity .
  
  ?unitEntity rdfs:label ?unit .

  # 4. Extract the literal value
  { ?measure rak:RAK_2000071 ?value . } # Forward Count
  UNION
  { ?measure rak:RAK_2000072 ?value . } # Reverse Count
  UNION
  { ?measure rak:RAK_2000074 ?value . } # Forward GC
  UNION
  { ?measure rak:RAK_2000075 ?value . } # Reverse GC
  
} ORDER BY ?metric
```

