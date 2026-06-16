@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.apache.poi.ss.usermodel.*
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import java.io.File

/**
 * Script to generate DNA extraction and DNA concentration measurement RDF data.
 * References terms from rubalkhali.owl.
 */

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def UO = "http://purl.obolibrary.org/obo/UO_"

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()
def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_dna.owl"))

// Annotation Properties
def rdfsLabel = df.getRDFSLabel()
def dcIdentifier = df.getOWLAnnotationProperty(IRI.create("http://purl.org/dc/elements/1.1/identifier"))

def addLabel = { iri, label -> manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(rdfsLabel, df.getOWLLiteral(label)))) }

// Object Properties (Referenced from SIO or rubalkhali.owl)
def hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
def hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
def isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
def hasTarget = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000291"))
def isSpecifiedBy = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000339"))
def hasParticipant = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000132"))
def hasFunction = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000001"))
def isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))
def hasAttribute = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000008"))
def hasUnit = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000221"))
def hasAgent = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000139"))

// Properties from rubalkhali.owl
def usesDNAExtractionKit = df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000014"))
def hasDNAConcentration = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000015"))

// Classes from rubalkhali.owl
def dnaExtractClass = df.getOWLClass(IRI.create(BASE + "RAK_0000040"))
def dnaExtractionProcessClass = df.getOWLClass(IRI.create(SIO + "SIO_000994")) // Experiment
def protocolClass = df.getOWLClass(IRI.create(SIO + "SIO_001043"))
def measurementProcessClass = df.getOWLClass(IRI.create(BASE + "RAK_0000041"))
def nanodropClass = df.getOWLClass(IRI.create(BASE + "RAK_0000042"))
def concentrationClass = df.getOWLClass(IRI.create("http://purl.obolibrary.org/obo/PATO_0000033"))
def powerSoilKitClass = df.getOWLClass(IRI.create(BASE + "RAK_0000051"))
def powerSoilProKitClass = df.getOWLClass(IRI.create(BASE + "RAK_0000052"))
def personClass = df.getOWLClass(IRI.create(SIO + "SIO_000498"))

// 1. Load Sample Mappings from rubalkhali_samples.owl
def sampleIdToIri = [:]
def samplesFile = new File("data/processed/ontology/rubalkhali_samples.owl")
if (samplesFile.exists()) {
    println "Loading sample mappings from rubalkhali_samples.owl..."
    def sOnt = manager.loadOntologyFromOntologyDocument(samplesFile)
    sOnt.getIndividualsInSignature().each { ind ->
        sOnt.getAnnotationAssertionAxioms(ind.getIRI()).each { ax ->
            if (ax.getProperty().equals(dcIdentifier)) {
                def id = ax.getValue().asLiteral().get().getLiteral().trim()
                sampleIdToIri[id] = ind.getIRI()
            }
        }
    }
    manager.removeOntology(sOnt)
}

// 2. Setup Individuals for Device and Agent
def nanodropInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_D000003"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(nanodropClass, nanodropInd))
addLabel(nanodropInd.getIRI(), "Nanodrop Device")

def measureFuncInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_F000003"))
addLabel(measureFuncInd.getIRI(), "to measure")
manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasFunction, nanodropInd, measureFuncInd))

// Agent: Marwa Abdelhakim
def marwaInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_A000006"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(personClass, marwaInd))
addLabel(marwaInd.getIRI(), "Marwa Abdelhakim")

// Kit Instances
def powerSoilKitInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_D000004"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(powerSoilKitClass, powerSoilKitInd))
addLabel(powerSoilKitInd.getIRI(), "PowerSoil Kit Instance")

def powerSoilProKitInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_D000005"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(powerSoilProKitClass, powerSoilProKitInd))
addLabel(powerSoilProKitInd.getIRI(), "PowerSoil Pro Kit Instance")


// Protocol Mapping
def protocolMap = [
    "PowerSoil": "DNA_ext_powersoil",
    "Pro": "DNA_ext_powersoilpro"
]

// Kit Instance Map
def kitInstanceMap = [
    "PowerSoil": powerSoilKitInd,
    "Pro": powerSoilProKitInd
]

// 2b. Load Sequenced Samples from SRA
def sequencedSamples = new HashSet()
def sraFile = new File("data/metadata/sra-submissions/submission-sheet.tsv")
if (sraFile.exists()) {
    sraFile.withReader { reader ->
        def lines = reader.readLines()
        if (lines.size() > 1) {
            def header = lines[0].split("\t")
            def colSample = header.findIndexOf { it == "sample_name" }
            if (colSample != -1) {
                lines.drop(1).each { line ->
                    def parts = line.split("\t")
                    if (parts.size() > colSample) {
                        sequencedSamples.add(parts[colSample].trim())
                    }
                }
            }
        }
    }
    println "Loaded ${sequencedSamples.size()} sequenced samples from SRA sheet."
}

// 3. Process Sample Mastersheet
def excelFile = new File("data/metadata/samples/Sample_Mastersheet.xlsx")
FileInputStream fis = new FileInputStream(excelFile)
Workbook workbook = new XSSFWorkbook(fis)

int processCounter = 200001
int dnaSampleCounter = 800001
int quantityCounter = 900001

(0..<workbook.getNumberOfSheets()).each { i ->
    Sheet sheet = workbook.getSheetAt(i)
    if (sheet.getSheetName() == "Plants") return
    
    String tripName = sheet.getSheetName()
    println "Processing sheet: ${tripName}"
    
    Row headerRow = sheet.getRow(0)
    if (!headerRow) return
    def headers = [:]
    headerRow.each { cell ->
        try { headers[cell.getStringCellValue().toLowerCase().trim()] = cell.getColumnIndex() } catch(e) {}
    }
    
    def colName = headers["name"]
    def colDna = headers["dna"]
    def colDnaKit = headers["dna kit"]
    def colDnaConc = headers["dna conc."]
    
    if (colName == null || colDna == null) {
        println "Skipping ${tripName}: Name or DNA column missing."
        return
    }
    
    sheet.drop(1).each { row ->
        def nameCell = row.getCell(colName)
        def dnaCell = row.getCell(colDna)
        if (!nameCell) return
        
        String sampleId = nameCell.toString().trim()
        String dnaStatus = dnaCell ? dnaCell.toString().trim() : ""
        
        // If sample is in SRA sheet, assume DNA exists regardless of Master Sheet flag
        if (!sequencedSamples.contains(sampleId) && (dnaStatus == "" || dnaStatus.equalsIgnoreCase("FALSE"))) return
        
        def soilSampleIri = sampleIdToIri[sampleId]
        if (!soilSampleIri) {
            return
        }
        
        // --- DNA Extraction Process ---
        def dnaInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_6" + String.format("%06d", dnaSampleCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(dnaExtractClass, dnaInd))
        addLabel(dnaInd.getIRI(), "DNA extract of sample ${sampleId}")
        
        def extProcInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(dnaExtractionProcessClass, extProcInd))
        addLabel(extProcInd.getIRI(), "DNA extraction process for sample ${sampleId}")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, extProcInd, df.getOWLNamedIndividual(soilSampleIri)))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, extProcInd, dnaInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, extProcInd, marwaInd))
        
        // Extraction Protocol & Kit
        def kit = row.getCell(colDnaKit)?.toString()?.trim()
        if (kit) {
            def protoId = protocolMap[kit] ?: kit.replaceAll(" ", "_")
            def protoInd = df.getOWLNamedIndividual(IRI.create(BASE + protoId))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(protocolClass, protoInd))
            addLabel(protoInd.getIRI(), "Protocol: ${kit}")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isSpecifiedBy, extProcInd, protoInd))
            
            // Link to Kit Instance
            def kitInst = kitInstanceMap[kit]
            if (kitInst) {
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(usesDNAExtractionKit, extProcInd, kitInst))
            }
        }
        
        // --- DNA Concentration Measurement ---
        def concVal = row.getCell(colDnaConc)?.toString()?.trim()
        if (concVal && concVal != "" && concVal != "0" && !concVal.equalsIgnoreCase("NaN")) {
            def measProcInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(measurementProcessClass, measProcInd))
            addLabel(measProcInd.getIRI(), "DNA concentration measurement process for ${sampleId}")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasTarget, measProcInd, dnaInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasParticipant, measProcInd, nanodropInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, measProcInd, marwaInd))
            
            // Output Quantity
            def quantInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", quantityCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(concentrationClass, quantInd))
            addLabel(quantInd.getIRI(), "DNA concentration of ${sampleId}")
            
            try {
                double val = Double.parseDouble(concVal)
                manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasDNAConcentration, quantInd, val))
            } catch (e) {
                manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasDNAConcentration, quantInd, concVal))
            }
            
            // Unit: ng/uL (UO_0000275)
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, quantInd, df.getOWLNamedIndividual(IRI.create(UO + "0000275"))))
            
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, quantInd, measProcInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, measProcInd, quantInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, quantInd, dnaInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, dnaInd, quantInd))
        }
    }
}

manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_dna.owl").toURI()))
println "Success: Generated data/processed/ontology/rubalkhali_dna.owl"