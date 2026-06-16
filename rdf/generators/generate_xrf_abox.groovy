@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.yaml', module='snakeyaml', version='2.2')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.yaml.snakeyaml.Yaml
import java.io.File

/**
 * Regenerated Script to generate XRF ABox data.
 * Distinguishes between field and lab measurements (surface, deep, rhizosphere).
 */

BASE = "https://rubalkhali.science/kb/"
SIO = "http://semanticscience.org/resource/"
UO = "http://purl.obolibrary.org/obo/UO_"

manager = OWLManager.createOWLOntologyManager()
ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_xrf.owl"))
df = manager.getOWLDataFactory()

// Properties
hasAgent = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000139"))
hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
isMeasurementValueOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000215"))
hasUnit = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000221"))
isSpecifiedBy = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000339"))
isPartOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000068"))
hasAttribute = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000008"))

isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))

hasConcValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000012"))
hasConcError = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000013"))

rdfsLabel = df.getRDFSLabel()

// Classes
xrfProcessClass = df.getOWLClass(IRI.create(BASE + "RAK_0000025"))
fieldProtocolClass = df.getOWLClass(IRI.create(BASE + "RAK_0000027"))
labProtocolClass = df.getOWLClass(IRI.create(BASE + "RAK_0000028"))

// 3 Subclasses for RAK_0000028 (Lab Protocol)
surfaceLabProtocolClass = df.getOWLClass(IRI.create(BASE + "RAK_0000251"))
deepLabProtocolClass = df.getOWLClass(IRI.create(BASE + "RAK_0000252"))
rhizosphereLabProtocolClass = df.getOWLClass(IRI.create(BASE + "RAK_0000253"))

baseConcClass = df.getOWLClass(IRI.create(BASE + "RAK_0000029")) 
baseValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000030")) 

manager.addAxiom(ontology, df.getOWLSubClassOfAxiom(surfaceLabProtocolClass, labProtocolClass))
manager.addAxiom(ontology, df.getOWLSubClassOfAxiom(deepLabProtocolClass, labProtocolClass))
manager.addAxiom(ontology, df.getOWLSubClassOfAxiom(rhizosphereLabProtocolClass, labProtocolClass))

def addLabel = { iri, label ->
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(rdfsLabel, df.getOWLLiteral(label))))
}

addLabel(surfaceLabProtocolClass.getIRI(), "XRF Lab Protocol (Surface Soil)")
addLabel(deepLabProtocolClass.getIRI(), "XRF Lab Protocol (Deep Soil)")
addLabel(rhizosphereLabProtocolClass.getIRI(), "XRF Lab Protocol (Rhizosphere Soil)")

soilTypeClasses = [
    "Surface": df.getOWLClass(IRI.create(BASE + "RAK_0000020")),
    "Deep": df.getOWLClass(IRI.create(BASE + "RAK_0000021")),
    "Rhizosphere": df.getOWLClass(IRI.create(BASE + "RAK_0000022"))
]

soilTypeProtocols = [
    "Surface": surfaceLabProtocolClass,
    "Deep": deepLabProtocolClass,
    "Rhizosphere": rhizosphereLabProtocolClass
]

// Analytes
yaml = new Yaml()
mapping = yaml.load(new File("config/codes/xrf_chemical_mapping.yml").text)
analyteMap = mapping.mappings ?: [:]
analyteClasses = [:]


// LE (Light Elements) has predefined IRIs in the base ontology (RAK_0000032/RAK_0000033)
analyteClasses["LE"] = [
    quality: df.getOWLClass(IRI.create(BASE + "RAK_0000032")),
    value: df.getOWLClass(IRI.create(BASE + "RAK_0000033"))
]

// All other analytes use counter-based IRIs starting at 100/500, skipping LE
// to match the base ontology (update_rubalkhali_ontology.groovy) IRI assignments
int qStart = 100
int vStart = 500
analyteMap.each { name, entry ->
    if (name == "LE") return  // LE handled above with predefined IRIs
    def qClass = df.getOWLClass(IRI.create(BASE + String.format("RAK_0%06d", qStart++)))
    def vClass = df.getOWLClass(IRI.create(BASE + String.format("RAK_0%06d", vStart++)))
    analyteClasses[name] = [quality: qClass, value: vClass]

    // Link quality class to ChEBI/PubChem entities via annotation
    def seeAlso = df.getOWLAnnotationProperty(IRI.create("http://www.w3.org/2000/01/rdf-schema#seeAlso"))
    if (entry.chebi) {
        manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(qClass.getIRI(), df.getOWLAnnotation(seeAlso, IRI.create(entry.chebi))))
    }
    if (entry.pubchem) {
        manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(qClass.getIRI(), df.getOWLAnnotation(seeAlso, IRI.create(entry.pubchem))))
    }
}

// Individuals
fieldProtocol = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_L000001"))
marwaAgent = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_A000006"))
trip5Team = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_A000005"))
percentUnit = df.getOWLNamedIndividual(IRI.create(UO + "0000187"))

// Map labels to IRIs for SampleID matching
sampleLabelToIri = [:]
siteIdToIri = [:]

def loadExternalMappings = {
    // Sites
    def sitesFile = new File("data/processed/ontology/rubalkhali_sites.owl")
    if (sitesFile.exists()) {
        def m = OWLManager.createOWLOntologyManager().loadOntologyFromOntologyDocument(sitesFile)
        m.getIndividualsInSignature().each { ind ->
            EntitySearcher.getAnnotationObjects(ind, m, rdfsLabel).each { ann ->
                def label = ann.getValue().asLiteral().get().getLiteral()
                def match = label =~ /Site (\d+)/
                if (match) siteIdToIri[match[0][1]] = ind.getIRI()
            }
        }
    }
    // Samples (for Lab)
    def samplesFile = new File("data/processed/ontology/rubalkhali_samples.owl")
    if (samplesFile.exists()) {
        def m = OWLManager.createOWLOntologyManager().loadOntologyFromOntologyDocument(samplesFile)
        m.getIndividualsInSignature().each { ind ->
            EntitySearcher.getAnnotationObjects(ind, m, rdfsLabel).each { ann ->
                def label = ann.getValue().asLiteral().get().getLiteral()
                // Example: "Sample V4Dr3 (Rep 1) - deep soil from Site 4 (Trip5)"
                def match = label =~ /Sample (\w+)/
                if (match) sampleLabelToIri[match[0][1]] = ind.getIRI()
            }
        }
    }
}
loadExternalMappings()

int xrfProcessCounter = 300001
int xrfValueCounter = 300001
int xrfQualityCounter = 300001

// 1. Process Field Measurements (consolidated TSV)
// Source: data/processed/geochemistry/xrf_field_table.tsv
// Generated by src/process_xrf_field.py from vanta_data_*.csv files.
// Columns: SiteID, TestID, LE, LE_error, <element>, <element>_error,
//          <oxide>, <oxide>_error  (oxide values pre-computed at correct stoichiometry)
// LE (Light Elements) uses predefined IRIs RAK_0000032/RAK_0000033.
def fieldFile = new File("data/processed/geochemistry/xrf_field_table.tsv")
if (fieldFile.exists()) {
    def fieldLines = fieldFile.readLines()
    def fieldHeader = fieldLines[0].split("\t")
    def colSiteId = fieldHeader.findIndexOf { it == "SiteID" }
    def colTestId = fieldHeader.findIndexOf { it == "TestID" }
    def colLe     = fieldHeader.findIndexOf { it == "LE" }
    def colLeErr  = fieldHeader.findIndexOf { it == "LE_error" }

    // Pre-compute which columns are error columns (skip as primary; used via analyte lookup)
    def errorCols = fieldHeader.findAll { it.endsWith("_error") }.toSet()
    def metaCols  = ["SiteID", "TestID", "LE", "LE_error"].toSet()

    fieldLines.drop(1).each { line ->
        def parts = line.split("\t")
        def siteId = parts[colSiteId]
        def testId = parts[colTestId]
        def siteIri = siteIdToIri[siteId]
        if (!siteIri) return

        // Field input material (always Deep in field campaign)
        def inputInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_699" + String.format("%04d", siteId.toInteger())))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(soilTypeClasses["Deep"], inputInd))
        addLabel(inputInd.getIRI(), "Field deep soil material from Site ${siteId}")

        def procInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", xrfProcessCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(xrfProcessClass, procInd))
        addLabel(procInd.getIRI(), "Field XRF analysis (Test ${testId}) for Site ${siteId} (Trip5)")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, procInd, trip5Team))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isSpecifiedBy, procInd, fieldProtocol))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, procInd, inputInd))

        // LE measurement (predefined IRIs RAK_0000032/RAK_0000033)
        double leConc = parts[colLe].toDouble()
        double leErr  = parts[colLeErr].toDouble()
        def leClasses = analyteClasses["LE"]
        def leValInd  = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", xrfValueCounter++)))
        def leQualInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", xrfQualityCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(leClasses.quality, leQualInd))
        addLabel(leQualInd.getIRI(), "Light Elements quality (Field XRF - Test ${testId}) for Site ${siteId}")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, leQualInd, leValInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, inputInd, leQualInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, leQualInd, inputInd))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(leClasses.value, leValInd))
        addLabel(leValInd.getIRI(), "Light Elements measurement value (Field XRF - Test ${testId}) for Site ${siteId}")
        manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasConcValue, leValInd, leConc))
        if (leErr > 0) manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasConcError, leValInd, leErr))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, leValInd, percentUnit))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, leValInd, procInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, leValInd))

        // All other analyte columns (skip metadata and error columns)
        fieldHeader.eachWithIndex { col, idx ->
            if (metaCols.contains(col) || errorCols.contains(col)) return
            def classes = analyteClasses[col]
            if (!classes) return

            double conc = parts[idx].toDouble()
            if (conc == 0) return

            // Look for a corresponding _error column
            def errIdx = fieldHeader.findIndexOf { it == "${col}_error" }
            double err = (errIdx >= 0 && errIdx < parts.size()) ? parts[errIdx].toDouble() : 0.0

            def valInd  = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", xrfValueCounter++)))
            def qualInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", xrfQualityCounter++)))

            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(classes.quality, qualInd))
            addLabel(qualInd.getIRI(), "${col} quality (Field XRF - Test ${testId}) for Site ${siteId}")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, qualInd, valInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, inputInd, qualInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qualInd, inputInd))

            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(classes.value, valInd))
            addLabel(valInd.getIRI(), "${col} measurement value (Field XRF - Test ${testId}) for Site ${siteId}")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, valInd, percentUnit))
            manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasConcValue, valInd, conc))
            if (err > 0) manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasConcError, valInd, err))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, valInd, procInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, valInd))
        }
    }
}

// 2. Process Lab Measurements (New combined table)
def labFile = new File("data/processed/geochemistry/xrf_lab_table_filtered.tsv")
if (labFile.exists()) {
    def lines = labFile.readLines()
    def header = lines[0].split("\t")
    def colSample = header.findIndexOf { it == "SampleID" }
    def colSoil = header.findIndexOf { it == "SoilType" }
    
    lines.drop(1).each { line ->
        def parts = line.split("\t")
        def sid = parts[colSample]
        def soilType = parts[colSoil]
        
        // Find input individual (linked to Sample ABox if possible)
        def inputIri = sampleLabelToIri[sid]
        def isExistingSample = (inputIri != null)
        if (!inputIri) {
            // Fallback: create a specific individual for this measurement input if not in samples.owl
            inputIri = IRI.create(BASE + "RAK_X" + sid)
        }
        def inputInd = df.getOWLNamedIndividual(inputIri)
        if (!isExistingSample) {
            // Only add type/label for individuals NOT already defined in samples.owl
            // Existing samples already have their type and label from generate_samples_abox
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(soilTypeClasses[soilType], inputInd))
            addLabel(inputInd.getIRI(), "Lab XRF input material: ${sid} (${soilType})")
        }

        def procInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", xrfProcessCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(xrfProcessClass, procInd))
        addLabel(procInd.getIRI(), "Lab XRF analysis for Sample ${sid} (${soilType})")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, procInd, marwaAgent))
        
        // Link to specific soil-type protocol subclass
        def protocolClass = soilTypeProtocols[soilType]
        def protocolInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_L_" + soilType + "_Lab"))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(protocolClass, protocolInd))
        addLabel(protocolInd.getIRI(), "Lab Protocol for ${soilType} XRF")
        
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isSpecifiedBy, procInd, protocolInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, procInd, inputInd))

        header.eachWithIndex { analyte, idx ->
            if (analyte in ["SampleID", "SoilType", "Material", "Mode", "Diameter", "Method"]) return
            def classes = analyteClasses[analyte]
            if (!classes) return

            double conc = parts[idx].toDouble()
            if (conc == 0) return
            
            def valInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", xrfValueCounter++)))
            def qualInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", xrfQualityCounter++)))
            
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(classes.quality, qualInd))
            addLabel(qualInd.getIRI(), "${analyte} quality (Lab XRF) for ${sid}")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, qualInd, valInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, inputInd, qualInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qualInd, inputInd))

            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(classes.value, valInd))
            addLabel(valInd.getIRI(), "${analyte} measurement value (Lab XRF) for ${sid}")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, valInd, percentUnit))
            manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasConcValue, valInd, conc))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, valInd, procInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, valInd))
        }
    }
}

manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_xrf.owl").toURI()))
println "Success: Regenerated rubalkhali_xrf.owl with soil-type distinction."
