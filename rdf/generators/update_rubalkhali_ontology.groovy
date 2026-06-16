@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.yaml', module='snakeyaml', version='2.2')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.yaml.snakeyaml.Yaml
import java.io.File

/**
 * Script to update the Rub al-Khali master ontology (TBox & RBox).
 * Centralizes all class and property definitions.
 */

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def ENVO = "http://purl.obolibrary.org/obo/ENVO_"
def PATO = "http://purl.obolibrary.org/obo/PATO_"
def UO = "http://purl.obolibrary.org/obo/UO_"
def DCTERMS = "http://purl.org/dc/terms/"
def DC = "http://purl.org/dc/elements/1.1/"
def DCAT = "http://www.w3.org/ns/dcat#"
def PAV = "http://purl.org/pav/"
def SCHEMA = "http://schema.org/"
def PROV = "http://www.w3.org/ns/prov#"

// Handle robust semantic versioning from a local file
def versionFile = new File("data/processed/ontology/build_version.txt")
def currentVersion = "v2.0.0"
def previousVersion = "v2.0.0"

if (versionFile.exists()) {
    previousVersion = versionFile.text.trim()
    def parts = previousVersion.replaceAll("v", "").split("\\.")
    if (parts.length == 3) {
        def patch = parts[2].toInteger() + 1
        currentVersion = "v${parts[0]}.${parts[1]}.${patch}"
    } else {
        currentVersion = "v2.0.1" // fallback
    }
}
// Write new version
if (!versionFile.parentFile.exists()) {
    versionFile.parentFile.mkdirs()
}
versionFile.text = currentVersion

def version = currentVersion
def authorName = "Robert Hoehndorf (https://orcid.org/0000-0001-8149-5890)"
def license = "https://creativecommons.org/licenses/by/4.0/"
def currentTime = java.time.Instant.now().toString()

def file = new File("data/processed/ontology/rubalkhali.owl")
def manager = OWLManager.createOWLOntologyManager()

def config = new OWLOntologyLoaderConfiguration()
config = config.setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT)

def ontology = manager.loadOntologyFromOntologyDocument(new org.semanticweb.owlapi.io.FileDocumentSource(file), config)
def df = manager.getOWLDataFactory()

def newOntologyIRI = IRI.create(BASE)
def newOntology
if (manager.contains(newOntologyIRI)) {
    newOntology = manager.getOntology(newOntologyIRI)
    // Clear existing axioms to start fresh if needed, or just use it
    manager.removeAxioms(newOntology, newOntology.getAxioms())
} else {
    newOntology = manager.createOntology(newOntologyIRI)
}

// --- Metadata ---
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "creator")), df.getOWLLiteral(authorName))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "publisher")), df.getOWLLiteral(authorName))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "license")), df.getOWLNamedIndividual(IRI.create(license)).getIRI())))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(SCHEMA + "license")), df.getOWLNamedIndividual(IRI.create(license)).getIRI())))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "accessRights")), df.getOWLLiteral("Freely accessible under CC-BY 4.0"))))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLVersionInfo(), df.getOWLLiteral(version))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(PAV + "version")), df.getOWLLiteral(version))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(PAV + "previousVersion")), df.getOWLLiteral(previousVersion))))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "issued")), df.getOWLLiteral(currentTime))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "modified")), df.getOWLLiteral(currentTime))))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(PAV + "createdWith")), df.getOWLNamedIndividual(IRI.create("https://github.com/leechuck/empty-quarter/blob/main/scripts/rdf/update_rubalkhali_ontology.groovy")).getIRI())))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "identifier")), df.getOWLNamedIndividual(IRI.create(BASE + "rubalkhali.owl")).getIRI())))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "title")), df.getOWLLiteral("Rub al-Khali Knowledge Graph"))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "description")), df.getOWLLiteral("A knowledge graph integrating geochemical, environmental, and metagenomic data from the Rub al-Khali desert."))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCAT + "accessURL")), df.getOWLNamedIndividual(IRI.create("https://rubalkhali.science")).getIRI())))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCAT + "endpointURL")), df.getOWLNamedIndividual(IRI.create("https://rubalkhali.science/sparql")).getIRI())))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCAT + "endpointDescription")), df.getOWLLiteral("SPARQL endpoint for the Rub al-Khali Knowledge Graph"))))

// Set Version IRI
def versionIRI = IRI.create(BASE + version + "/")
def oid = new OWLOntologyID(newOntologyIRI, versionIRI)
manager.applyChange(new SetOntologyID(newOntology, oid))

// Carry over imports
ontology.getImportsDeclarations().each { imp ->
    manager.applyChange(new AddImport(newOntology, imp))
}
manager.setOntologyFormat(newOntology, manager.getOntologyFormat(ontology))


def defineDataProp = { id, label, description, domainIri = SIO + "SIO_000070" ->
    def iri = IRI.create(BASE + id)
    def prop = df.getOWLDataProperty(iri)
    manager.addAxiom(newOntology, df.getOWLSubDataPropertyOfAxiom(prop, df.getOWLDataProperty(IRI.create(SIO + "SIO_000300"))))
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "description")), df.getOWLLiteral(description))))
    if (domainIri) {
        manager.addAxiom(newOntology, df.getOWLDataPropertyDomainAxiom(prop, df.getOWLClass(IRI.create(domainIri))))
    }
}

def defineObjectProp = { id, label, description, parentIri = null ->
    def iri = IRI.create(BASE + id)
    def prop = df.getOWLObjectProperty(iri)
    if (parentIri) {
        manager.addAxiom(newOntology, df.getOWLSubObjectPropertyOfAxiom(prop, df.getOWLObjectProperty(IRI.create(parentIri))))
    }
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "description")), df.getOWLLiteral(description))))
}

def defineClass = { id, label, parentIri ->
    def iri = IRI.create(BASE + id)
    def cls = df.getOWLClass(iri)
    if (parentIri) {
        manager.addAxiom(newOntology, df.getOWLSubClassOfAxiom(cls, df.getOWLClass(IRI.create(parentIri))))
    }
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
}

def investigationClassIri = SIO + "SIO_000747"
def measuringClassIri = SIO + "SIO_001054"
def measurementValueClassIri = SIO + "SIO_000070"

// --- TBox Class definitions (RAK_0XXXXXX) ---
defineClass("RAK_0000001", "site quality", SIO + "SIO_000026")
defineClass("RAK_0000002", "sampling site", SIO + "SIO_000019")
defineClass("RAK_0000003", "site visit", investigationClassIri)
defineClass("RAK_0000004", "Mitsubishi Pajero Barometer", SIO + "SIO_001236")
defineClass("RAK_0000005", "Testo Thermometer", SIO + "SIO_001236")

defineClass("RAK_0000006", "temperature measuring", measuringClassIri)
defineClass("RAK_0000007", "atmospheric pressure measuring", measuringClassIri)
defineClass("RAK_0000008", "relative humidity measuring", measuringClassIri)
defineClass("RAK_0000009", "annual climate measuring", measuringClassIri)

defineClass("RAK_0000010", "temperature measurement value", measurementValueClassIri)
defineClass("RAK_0000011", "atmospheric pressure measurement value", measurementValueClassIri)
defineClass("RAK_0000012", "relative humidity measurement value", measurementValueClassIri)
defineClass("RAK_0000013", "annual mean temperature value", measurementValueClassIri)
defineClass("RAK_0000014", "annual total precipitation value", measurementValueClassIri)
defineClass("RAK_0000015", "annual total rain value", measurementValueClassIri)

defineClass("RAK_0000016", "Rub al-Khali Expedition Team", SIO + "SIO_000620")
defineClass("RAK_0000017", "measuring function", SIO + "SIO_000017")
defineClass("RAK_0000018", "expedition", investigationClassIri)
defineClass("RAK_0000019", "person", SIO + "SIO_000498")

defineClass("RAK_0000020", "surface soil sample", SIO + "SIO_001050")
defineClass("RAK_0000021", "deep soil sample", SIO + "SIO_001050")
defineClass("RAK_0000022", "rhizosphere sample", SIO + "SIO_001050")
defineClass("RAK_0000023", "plant matter sample", SIO + "SIO_001050")
defineClass("RAK_0000024", "sampling process", SIO + "SIO_000006")

defineClass("RAK_0000025", "XRF measuring process", measuringClassIri)
defineClass("RAK_0000026", "XRF device", SIO + "SIO_001236")
defineClass("RAK_0000027", "Field XRF protocol", SIO + "SIO_000091")
defineClass("RAK_0000028", "Lab XRF protocol", SIO + "SIO_000091")
defineClass("RAK_0000029", "chemical analyte concentration", PATO + "0000033")
manager.addAxiom(newOntology, df.getOWLSubClassOfAxiom(df.getOWLClass(IRI.create(BASE + "RAK_0000029")), df.getOWLClass(IRI.create(SIO + "SIO_001088"))))
defineClass("RAK_0000030", "analyte concentration measurement value", SIO + "SIO_000070")
defineClass("RAK_0000031", "Light Elements mixture", SIO + "SIO_000004")

defineClass("RAK_0000032", "Light Elements concentration", BASE + "RAK_0000029")
defineClass("RAK_0000033", "Light Elements concentration measurement value", BASE + "RAK_0000030")
defineClass("RAK_0000034", "monthly climate measuring", measuringClassIri)
defineClass("RAK_0000035", "monthly mean temperature value", measurementValueClassIri)
defineClass("RAK_0000036", "monthly total precipitation value", measurementValueClassIri)
defineClass("RAK_0000037", "monthly total rain value", measurementValueClassIri)
defineClass("RAK_0000038", "monthly mean humidity value", measurementValueClassIri)

defineClass("RAK_0000040", "DNA extract", SIO + "SIO_001173")
defineClass("RAK_0000041", "DNA concentration measurement process", measuringClassIri)
defineClass("RAK_0000042", "Nanodrop device", SIO + "SIO_001236")

defineClass("RAK_0000050", "DNA extraction kit", SIO + "SIO_010462")
defineClass("RAK_0000051", "PowerSoil DNA Extraction Kit", BASE + "RAK_0000050")
defineClass("RAK_0000052", "PowerSoil Pro DNA Extraction Kit", BASE + "RAK_0000050")

defineClass("RAK_0000060", "16S Amplicon Library", BASE + "RAK_0000040")
defineClass("RAK_0000061", "Forward 16S Primer", SIO + "SIO_010093")
defineClass("RAK_0000062", "Reverse 16S Primer", SIO + "SIO_010093")
defineClass("RAK_0000063", "FASTQ Dataset", SIO + "SIO_000089")
defineClass("RAK_0000064", "Sequence Read", SIO + "SIO_000069")

defineClass("RAK_0000070", "bioinformatic workflow", SIO + "SIO_000127")
defineClass("RAK_0000071", "16S amplicon processing workflow", BASE + "RAK_0000070")
defineClass("RAK_0000072", "taxon relative abundance quality", SIO + "SIO_000651")
defineClass("RAK_0000073", "relative abundance measurement value", SIO + "SIO_000070")
// 4. Analytes
yaml = new Yaml()
mapping = yaml.load(new File("config/codes/xrf_chemical_mapping.yml").text)
analyteMap = mapping.mappings ?: [:]

int qualityStart = 100
int valueStart = 500
analyteMap.each { name, entry ->
    if (name == "LE") return
    def qId = String.format("RAK_0%06d", qualityStart++)
    def vId = String.format("RAK_0%06d", valueStart++)
    defineClass(qId, "${name} concentration", BASE + "RAK_0000029")
    defineClass(vId, "${name} concentration measurement value", BASE + "RAK_0000030")
}

// --- ENVO Labels ---
def addEnvoLabel = { id, label ->
    def iri = IRI.create("http://purl.obolibrary.org/obo/" + id)
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
}
addEnvoLabel("ENVO_01000179", "desert biome")
addEnvoLabel("ENVO_01000183", "tropical desert biome")
addEnvoLabel("ENVO_01001838", "arid biome")
addEnvoLabel("ENVO_00000192", "desert")
addEnvoLabel("ENVO_00000170", "sand dune")
addEnvoLabel("ENVO_01000018", "gravel")
addEnvoLabel("ENVO_00000019", "saline lake")
addEnvoLabel("ENVO_00000279", "saline pan")
addEnvoLabel("ENVO_01000935", "campground")
addEnvoLabel("ENVO_00000064", "road")

// --- UO Labels ---
def addUOLabel = { id, label ->
    def iri = IRI.create(UO + id)
    manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
}
addUOLabel("0000187", "percent")

// --- Properties (RAK_2XXXXXX) ---
defineObjectProp("RAK_2000001", "has biome", "Associates a site with a biome type.")
defineObjectProp("RAK_2000002", "has environmental feature", "Associates a site with a specific environmental feature.")
defineObjectProp("RAK_2000014", "uses DNA extraction kit", "A relation between an extraction process and a kit used.", SIO + "SIO_000132")
defineObjectProp("RAK_2000016", "uses primer", "A relation between a process and a primer used in that process.", SIO + "SIO_000132")
defineObjectProp("RAK_2000018", "uses forward primer", "A relation between a process and a forward primer used.", BASE + "RAK_2000016")
defineObjectProp("RAK_2000019", "uses reverse primer", "A relation between a process and a reverse primer used.", BASE + "RAK_2000016")

defineDataProp("RAK_2000003", "has temperature value", "The numerical value of a temperature measurement.")
defineDataProp("RAK_2000004", "has pressure value", "The numerical value of an atmospheric pressure measurement.")
defineDataProp("RAK_2000005", "has humidity value", "The numerical value of a relative humidity measurement.")
defineDataProp("RAK_2000006", "has time value", "The date and time value of a temporal measurement.")
defineDataProp("RAK_2000007", "has annual mean temperature value", "The numerical value of the annual mean temperature at a site.")
defineDataProp("RAK_2000008", "has annual total precipitation value", "The numerical value of the annual total precipitation at a site.")
defineDataProp("RAK_2000009", "has annual total rain value", "The numerical value of the annual total rain at a site.")
defineDataProp("RAK_2000010", "has start time value", "The start date and time of a temporal interval.")
defineDataProp("RAK_2000011", "has end time value", "The end date and time of a temporal interval.")
defineDataProp("RAK_2000012", "has concentration value", "The numerical value of a chemical analyte concentration.")
defineDataProp("RAK_2000013", "has concentration error", "The numerical value of the error in a concentration measurement.")
defineDataProp("RAK_2000015", "has DNA concentration", "The numerical value of a DNA concentration measurement.", SIO + "SIO_000300")
defineDataProp("RAK_2000017", "has sequence value", "The literal nucleotide sequence string.", SIO + "SIO_000300")
defineDataProp("RAK_2000020", "has relative abundance value", "The numerical value of a relative taxon abundance measurement.", SIO + "SIO_000070")
defineDataProp("RAK_2000021", "has monthly mean temperature value", "The numerical value of the monthly mean temperature at a site.")
defineDataProp("RAK_2000022", "has monthly total precipitation value", "The numerical value of the monthly total precipitation at a site.")
defineDataProp("RAK_2000023", "has monthly total rain value", "The numerical value of the monthly total rain at a site.")
defineDataProp("RAK_2000024", "has monthly mean humidity value", "The numerical value of the monthly mean relative humidity at a site.")

// Property Chains
OWLObjectProperty isMeasurementValueOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000215"))
OWLObjectProperty isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
OWLObjectProperty hasTarget = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000291"))
OWLObjectProperty hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
OWLObjectProperty isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))
OWLObjectProperty isPartOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000068"))

manager.addAxiom(newOntology, df.getOWLSubPropertyChainOfAxiom([isMeasurementValueOf, isOutputOf, hasTarget], isAttributeOf))
manager.addAxiom(newOntology, df.getOWLSubPropertyChainOfAxiom([isMeasurementValueOf, isOutputOf, hasInput], isAttributeOf))
manager.addAxiom(newOntology, df.getOWLSubPropertyChainOfAxiom([isPartOf, hasTarget], hasTarget))
manager.addAxiom(newOntology, df.getOWLSubPropertyChainOfAxiom([isPartOf, isPartOf], isPartOf))

// Save ontology
manager.saveOntology(newOntology, IRI.create(file.toURI()))
println "rubalkhali.owl TBox updated. Version: ${version}"

// Regenerate VoID file with current version
def voidFile = new File("void.ttl")
voidFile.text = """\
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix void: <http://rdfs.org/ns/void#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix pav: <http://purl.org/pav/> .
@prefix schema: <http://schema.org/> .
@prefix rak: <https://rubalkhali.science/kb/> .

rak:Dataset a void:Dataset ;
    dcterms:title "Rub al-Khali Knowledge Graph" ;
    dcterms:description "A knowledge graph integrating geochemical, environmental, and metagenomic data from the Rub al-Khali desert." ;
    dcterms:creator "Robert Hoehndorf (https://orcid.org/0000-0001-8149-5890)" ;
    dcterms:publisher "Robert Hoehndorf (https://orcid.org/0000-0001-8149-5890)" ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
    schema:license <https://creativecommons.org/licenses/by/4.0/> ;
    dcterms:accessRights "Freely accessible under CC-BY 4.0" ;
    dcterms:version "${version}" ;
    pav:version "${version}" ;
    pav:previousVersion "${previousVersion}" ;
    dcterms:issued "${currentTime}"^^xsd:dateTime ;
    dcterms:modified "${currentTime}"^^xsd:dateTime ;
    dcat:accessURL <https://rubalkhali.science> ;
    dcat:endpointURL <https://rubalkhali.science/sparql> ;
    dcat:endpointDescription "SPARQL endpoint for the Rub al-Khali Knowledge Graph" ;
    void:sparqlEndpoint <https://rubalkhali.science/sparql> ;
    void:dataDump <https://rubalkhali.science/data/ontology.ttl> ;
    dcterms:identifier <https://rubalkhali.science/kb/rubalkhali.owl> .
"""
println "void.ttl regenerated. Version: ${version}"