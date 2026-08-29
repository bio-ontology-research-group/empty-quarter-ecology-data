@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVParser
import java.io.File
import java.io.FileReader

// --- Configuration ---
def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def PATO = "http://purl.obolibrary.org/obo/PATO_"
def UO = "http://purl.obolibrary.org/obo/UO_"
def XSD = "http://www.w3.org/2001/XMLSchema#"
def RDFS = "http://www.w3.org/2000/01/rdf-schema#"

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()
def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_qc.owl"))

// --- TBox Class & Property references ---
// All TBox declarations (labels, parents) live in update_rubalkhali_ontology.groovy.
// This script only writes ABox individuals and class-membership assertions.
def datasetClass = df.getOWLClass(IRI.create(BASE + "RAK_0000063")) // FASTQ Dataset

// QC Process
def qcProcessClass = df.getOWLClass(IRI.create(BASE + "RAK_0000200"))

// Qualities (parent + Fwd/Rev) — moved out of 70-94 range to avoid IRI collisions
def qSeqCountFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000202"))
def qSeqCountRev = df.getOWLClass(IRI.create(BASE + "RAK_0000203"))

def qGCFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000205"))
def qGCRev = df.getOWLClass(IRI.create(BASE + "RAK_0000206"))

def qDupFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000208"))
def qDupRev = df.getOWLClass(IRI.create(BASE + "RAK_0000209"))

def qLenFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000211"))
def qLenRev = df.getOWLClass(IRI.create(BASE + "RAK_0000212"))

// Values
def vSeqCountFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000214"))
def vSeqCountRev = df.getOWLClass(IRI.create(BASE + "RAK_0000215"))

def vGCFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000217"))
def vGCRev = df.getOWLClass(IRI.create(BASE + "RAK_0000218"))

def vDupFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000220"))
def vDupRev = df.getOWLClass(IRI.create(BASE + "RAK_0000221"))

def vLenFwd = df.getOWLClass(IRI.create(BASE + "RAK_0000223"))
def vLenRev = df.getOWLClass(IRI.create(BASE + "RAK_0000224"))


// Datatype Property references — declared in update_rubalkhali_ontology.groovy.
def dpSeqCountFwd = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000071"))
def dpSeqCountRev = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000072"))

def dpGCFwd = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000074"))
def dpGCRev = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000075"))

def dpDupFwd = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000077"))
def dpDupRev = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000078"))

def dpLenFwd = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000080"))
def dpLenRev = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000081"))


// Object Properties
def hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
def hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
def isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000218"))
def hasUnit = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000221"))
def isMeasurementValueOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000215"))

// Units
def uoPercent = df.getOWLNamedIndividual(IRI.create(UO + "0000187"))
def uoCount = df.getOWLNamedIndividual(IRI.create(UO + "0000189"))
def uoBp = df.getOWLNamedIndividual(IRI.create(UO + "0000244"))


// --- Mapping Logic ---

// 1. Load Submission Sheet to map Sample Name -> [Run Accessions]
def submissionFile = new File("data/metadata/sra-submissions/submission-sheet.tsv")
def sampleToRunMap = [:] // Map<String, List<String>>

CSVParser subParser = CSVFormat.TDF.withFirstRecordAsHeader().parse(new FileReader(submissionFile))
subParser.each { record ->
    String sample = record.get("sample_name")
    String run = record.get("run_accession")
    if (sample && run) {
        if (!sampleToRunMap.containsKey(sample)) {
            sampleToRunMap[sample] = []
        }
        sampleToRunMap[sample].add(run)
    }
}
println "Mapped ${sampleToRunMap.size()} unique samples to runs."


// 2. Process MultiQC Data
def multiQcFile = new File("data/metadata/QC_reads/multiqc_general_stats.txt")
CSVParser qcParser = CSVFormat.TDF.withFirstRecordAsHeader().parse(new FileReader(multiQcFile))

int processCounter = 350001
int qualityCounter = 550001
int valueCounter = 450001

qcParser.each { record ->
    String rawSampleName = record.get("Sample")
    
    // Extract Core Sample Name
    // Pattern: M-25-0323_Ctrl-1-Trip1_UDP0371-UDP0371_L002_R1_001
    // Strategy: Split by '_', take 2nd element? 
    // Wait, Ctrl-1-Trip1 contains hyphens.
    // M-25-xxxx is fixed (part 1). 
    // UDP... starts the suffix.
    // So extracting everything between the first '_' and '_UDP' might work.
    
    // Extract Core Sample Name
    // Strategy: Match against known valid sample names from the submission sheet.
    String coreSampleName = ""
    List<String> candidates = []
    
    sampleToRunMap.keySet().each { knownName ->
        if (rawSampleName.contains("_" + knownName + "_")) {
            candidates.add(knownName)
        }
    }
    
    if (candidates.isEmpty()) {
        println "Warning: Could not identify known sample in ${rawSampleName}"
        return
    }
    
    coreSampleName = candidates.max { it.length() }

    // Determine Orientation
    boolean isFwd = rawSampleName.contains("_R1_")
    boolean isRev = rawSampleName.contains("_R2_")
    if (!isFwd && !isRev) {
        println "Warning: Could not determine R1/R2 from ${rawSampleName}"
        return
    }

    // Retrieve Run Accessions
    List<String> runs = sampleToRunMap[coreSampleName]
    if (!runs) {
        println "Warning: Sample ${coreSampleName} not found in submission sheet."
        return
    }

    // Iterate over mapped runs (handling duplicates)
    runs.each { runAccession ->
        
        // Generate Triples
        
        // Individuals
        IRI runIri = IRI.create(BASE + "RAK_79" + runAccession.replace("ERR", "").substring(3)) // Assuming sequential matching is hard, we use existing mapping? 
        // Wait, I don't have the mapping to RAK_79nnnn here easily unless I assume 
        // I should probably map Run Accession to RAK_79nnnn if possible or just use a look-up.
        // In generate_sra_abox.groovy, I created RAK_79nnnn sequentially. 
        // I DO NOT KNOW THE RAK ID here without the previous map.
        // OPTION: Load rubalkhali_sra.owl? Or Just use RAK_79 + ERR ID? No, the ID was sequential.
        
        // CRITICAL: I need to link to the CORRECT RAK_79nnnn.
        // I will load `rubalkhali_sra.owl` to map ERR -> RAK_79nnnn.
        
    }
}

// --- Helper to Map ERR -> RAK ---
def errToRakMap = [:]
def sraFile = new File("data/processed/ontology/rubalkhali_sra.owl")
if (sraFile.exists()) {
    println "Loading rubalkhali_sra.owl to map ERR to RAK..."
    def sraOnt = manager.loadOntologyFromOntologyDocument(sraFile)
    sraOnt.getIndividualsInSignature().each { ind ->
        // Check for seeAlso annotation
        org.semanticweb.owlapi.search.EntitySearcher.getAnnotationObjects(ind, sraOnt, df.getOWLAnnotationProperty(IRI.create(RDFS + "seeAlso"))).each { ann ->
            String val = ""
            if (ann.getValue().isIRI()) {
                val = ann.getValue().asIRI().get().toString()
            } else if (ann.getValue().isLiteral()) {
                val = ann.getValue().asLiteral().get().getLiteral()
            }

            if (val.contains("insdc.run/ERR")) {
                String err = val.split("insdc.run/")[1]
                errToRakMap[err] = ind.getIRI()
            }
        }
    }
    manager.removeOntology(sraOnt)
    println "Mapped ${errToRakMap.size()} ERRs to RAK IDs."
} else {
    println "Error: SRA Ontology not found. Cannot link to datasets."
    return
}

// --- Resume QC Processing with Map ---
qcParser = CSVFormat.TDF.withFirstRecordAsHeader().parse(new FileReader(multiQcFile)) // Reset parser

qcParser.each { record ->
    String rawSampleName = record.get("Sample")
    String coreSampleName = ""
    List<String> candidates = []
    
    sampleToRunMap.keySet().each { knownName ->
        if (rawSampleName.contains("_" + knownName + "_")) {
            candidates.add(knownName)
        }
    }
    
    if (candidates.isEmpty()) {
        return
    }
    
    coreSampleName = candidates.max { it.length() }

    boolean isFwd = rawSampleName.contains("_R1_")
    
    // Get Runs
    List<String> runs = sampleToRunMap[coreSampleName]
    if (!runs) return

    runs.each { runAccession ->
        IRI datasetIri = errToRakMap[runAccession]
        if (!datasetIri) return 

        // 1. Process
        // Unique ID: Base + P35 + (Hash of rawSampleName + runAccession abs) ? 
        // No, let's just increment. But we have loops. 
        // We create a NEW process for each Run+Read pair? 
        // Or one process per Run? 
        // MultiQC is one process analyzing both. 
        // Let's create one process per Row (R1 or R2) for simplicity? 
        // Or better: One Process per Run, with multiple outputs.
        // But the input file splits R1/R2. 
        // I will create distinct processes for R1 analysis and R2 analysis to match the input rows.
        
        IRI processIri = IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++))
        def processInd = df.getOWLNamedIndividual(processIri)
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(qcProcessClass, processInd))
        
        String label = "MultiQC Analysis for ${coreSampleName} (${isFwd ? 'R1' : 'R2'}) - ${runAccession}"
        manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(processIri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, processInd, df.getOWLNamedIndividual(datasetIri)))

        // 2. Metrics
        // GC
        if (record.isSet("fastqc-percent_gc")) {
            double val = Double.parseDouble(record.get("fastqc-percent_gc"))
            createMeasurement(manager, df, ontology, processInd, datasetIri, runAccession,
                isFwd ? qGCFwd : qGCRev, 
                isFwd ? vGCFwd : vGCRev,
                isFwd ? dpGCFwd : dpGCRev,
                val, uoPercent, "GC Content", qualityCounter++, valueCounter++)
        }
        
        // Count (MultiQC total_sequences is in millions usually? No, check values. 0.797067. 
        // Usually MultiQC General Stats export is in Millions. 
        // Wait, example: 746256 Sequences -> 0.746 M.
        // The value in file: 0.797067. This is Million.
        // We want Integer count. 0.797067 * 1,000,000 = 797067.
        if (record.isSet("fastqc-total_sequences")) {
            double rawVal = Double.parseDouble(record.get("fastqc-total_sequences"))
            int countVal = (int) (rawVal * 1000000)
            createMeasurement(manager, df, ontology, processInd, datasetIri, runAccession,
                isFwd ? qSeqCountFwd : qSeqCountRev,
                isFwd ? vSeqCountFwd : vSeqCountRev,
                isFwd ? dpSeqCountFwd : dpSeqCountRev,
                countVal, uoCount, "Sequence Count", qualityCounter++, valueCounter++)
        }

        // Duplicates
        if (record.isSet("fastqc-percent_duplicates")) {
            double val = Double.parseDouble(record.get("fastqc-percent_duplicates"))
            createMeasurement(manager, df, ontology, processInd, datasetIri, runAccession,
                isFwd ? qDupFwd : qDupRev,
                isFwd ? vDupFwd : vDupRev,
                isFwd ? dpDupFwd : dpDupRev,
                val, uoPercent, "Duplicate Rate", qualityCounter++, valueCounter++)
        }

        // Length
        if (record.isSet("fastqc-avg_sequence_length")) {
            double val = Double.parseDouble(record.get("fastqc-avg_sequence_length"))
            createMeasurement(manager, df, ontology, processInd, datasetIri, runAccession,
                isFwd ? qLenFwd : qLenRev,
                isFwd ? vLenFwd : vLenRev,
                isFwd ? dpLenFwd : dpLenRev,
                val, uoBp, "Mean Read Length", qualityCounter++, valueCounter++)
        }
        
        // Increment globals
        qualityCounter += 4 
        valueCounter += 4
    }
}

// Save
manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_qc.owl").toURI()))
println "Generated rubalkhali_qc.owl"


// --- Helper Function ---
def createMeasurement(manager, df, ontology, processInd, datasetIri, runAccession, qClass, vClass, dProp, value, unitInd, labelBase, qId, vId) {
    def BASE = "https://rubalkhali.science/kb/"
    def SIO = "http://semanticscience.org/resource/"
    
    // Quality
    def qInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", qId)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(qClass, qInd))
    String qLabel = "${labelBase} Quality of ${runAccession}"
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(qInd.getIRI(), df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(qLabel))))
    
    // Bearer (dataset) ↔ quality: assert both is-quality-of (specific) and
    // is-attribute-of (generic) so SPARQL queries that traverse either work.
    def isQualityOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000218"))
    def hasQuality  = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000217"))
    def isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))
    def hasAttribute  = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000008"))
    def datasetInd = df.getOWLNamedIndividual(datasetIri)
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isQualityOf, qInd, datasetInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasQuality, datasetInd, qInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qInd, datasetInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, datasetInd, qInd))

    // Value
    def vInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", vId)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(vClass, vInd))
    String vLabel = "${labelBase} Measurement Value for ${runAccession}"
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(vInd.getIRI(), df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(vLabel))))

    // Properties
    if (value instanceof Integer) {
        manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(dProp, vInd, value))
    } else {
        manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(dProp, vInd, (double)value))
    }

    def hasUnit = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000221"))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, vInd, unitInd))

    // Quality ↔ value: SIO-canonical bidirectional pair (215 + 216).
    def isMeasurementValueOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000215"))
    def hasMeasurementValue  = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000216"))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, vInd, qInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMeasurementValue, qInd, vInd))

    // Process ↔ value: bidirectional (229 + 232).
    def hasOutput  = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
    def isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, processInd, vInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, vInd, processInd))
}
