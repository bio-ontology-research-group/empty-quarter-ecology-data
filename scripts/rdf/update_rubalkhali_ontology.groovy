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
def currentTime = java.time.Instant.now().toString()

def file = new File("data/processed/ontology/rubalkhali.owl")

// Use a SEPARATE manager just to peek at the existing file's imports + format,
// so the rebuild doesn't inherit accumulated ontology annotations from the
// previous serialization (which was the cause of the multi-pav:version /
// multi-dcterms:modified bug). The output manager is brand new and writes
// only the axioms we explicitly add below.
def loaderManager = OWLManager.createOWLOntologyManager()
def loaderConfig = new OWLOntologyLoaderConfiguration()
        .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT)
def existing = loaderManager.loadOntologyFromOntologyDocument(
        new org.semanticweb.owlapi.io.FileDocumentSource(file), loaderConfig)
def existingFormat = loaderManager.getOntologyFormat(existing)
def existingImports = new ArrayList(existing.getImportsDeclarations())

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()

def newOntologyIRI = IRI.create(BASE)
def newOntology = manager.createOntology(newOntologyIRI)

// --- Metadata ---
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "creator")), df.getOWLLiteral(authorName))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "publisher")), df.getOWLLiteral(authorName))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLVersionInfo(), df.getOWLLiteral(version))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(PAV + "version")), df.getOWLLiteral(version))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(PAV + "previousVersion")), df.getOWLLiteral(previousVersion))))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "issued")), df.getOWLLiteral(currentTime))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "modified")), df.getOWLLiteral(currentTime))))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(PAV + "createdWith")), df.getOWLNamedIndividual(IRI.create("https://github.com/bio-ontology-research-group/empty-quarter/blob/main/scripts/rdf/update_rubalkhali_ontology.groovy")).getIRI())))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "identifier")), df.getOWLNamedIndividual(IRI.create(BASE + "rubalkhali.owl")).getIRI())))

manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "title")), df.getOWLLiteral("Rub al-Khali Knowledge Graph"))))
manager.addAxiom(newOntology, df.getOWLAnnotationAssertionAxiom(newOntologyIRI, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DCTERMS + "description")), df.getOWLLiteral("A knowledge graph integrating geochemical, environmental, and metagenomic data from the Rub al-Khali desert."))))
// Set Version IRI
def versionIRI = IRI.create(BASE + version + "/")
def oid = new OWLOntologyID(newOntologyIRI, versionIRI)
manager.applyChange(new SetOntologyID(newOntology, oid))

// Carry over imports + serialization format from the previous file.
existingImports.each { imp ->
    manager.applyChange(new AddImport(newOntology, imp))
}
if (existingFormat) {
    manager.setOntologyFormat(newOntology, existingFormat)
}


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
defineClass("RAK_0000043", "DNA concentration quality", PATO + "0000033")
defineClass("RAK_0000044", "DNA concentration measurement value", measurementValueClassIri)

defineClass("RAK_0000050", "DNA extraction kit", SIO + "SIO_010462")
defineClass("RAK_0000051", "PowerSoil DNA Extraction Kit", BASE + "RAK_0000050")
defineClass("RAK_0000052", "PowerSoil Pro DNA Extraction Kit", BASE + "RAK_0000050")

defineClass("RAK_0000060", "16S Amplicon Library", BASE + "RAK_0000040")
defineClass("RAK_0000061", "Forward 16S Primer", SIO + "SIO_010093")
defineClass("RAK_0000062", "Reverse 16S Primer", SIO + "SIO_010093")
defineClass("RAK_0000063", "FASTQ Dataset", SIO + "SIO_000089")
defineClass("RAK_0000064", "Sequence Read", SIO + "SIO_000069")
defineClass("RAK_0000065", "library preparation process", SIO + "SIO_000006")
defineClass("RAK_0000066", "sequencing process", SIO + "SIO_000006")

defineClass("RAK_0000070", "bioinformatic workflow", SIO + "SIO_000127")
defineClass("RAK_0000071", "16S amplicon processing workflow", BASE + "RAK_0000070")
defineClass("RAK_0000072", "taxon relative abundance quality", SIO + "SIO_000651")
defineClass("RAK_0000073", "relative abundance measurement value", SIO + "SIO_000070")
defineClass("RAK_0000074", "taxon absolute abundance dataset", SIO + "SIO_000089")
defineClass("RAK_0000075", "taxon relative abundance dataset", SIO + "SIO_000089")
defineClass("RAK_0000076", "absolute abundance measurement value", SIO + "SIO_000070")
defineClass("RAK_0000078", "taxon absolute abundance quality", SIO + "SIO_000651")

// --- XRF lab protocol subclasses (RAK_0000251-0000253) ---
defineClass("RAK_0000251", "XRF Lab Protocol (Surface Soil)", BASE + "RAK_0000028")
defineClass("RAK_0000252", "XRF Lab Protocol (Deep Soil)", BASE + "RAK_0000028")
defineClass("RAK_0000253", "XRF Lab Protocol (Rhizosphere Soil)", BASE + "RAK_0000028")

// --- Laboratory-control model (RAK_0000300-RAK_0000323) ---
// Controls are materials bearing context-specific roles.  Extraction blanks
// belong to laboratory extraction batches, not expeditions; positive controls
// are evaluation inputs and are never contaminant-training classes.
defineClass("RAK_0000300", "laboratory control material", SIO + "SIO_000004")
defineClass("RAK_0000301", "mock-community control material", BASE + "RAK_0000300")
manager.addAxiom(newOntology, df.getOWLSubClassOfAxiom(
        df.getOWLClass(IRI.create(BASE + "RAK_0000301")),
        df.getOWLClass(IRI.create(SIO + "SIO_001050"))))
defineClass("RAK_0000302", "blank control material", BASE + "RAK_0000300")
defineClass("RAK_0000303", "laboratory control role", SIO + "SIO_000016")
defineClass("RAK_0000304", "positive microbiome control role", BASE + "RAK_0000303")
defineClass("RAK_0000305", "negative microbiome control role", BASE + "RAK_0000303")
defineClass("RAK_0000306", "extraction blank role", BASE + "RAK_0000305")
defineClass("RAK_0000307", "PCR blank role", BASE + "RAK_0000305")
defineClass("RAK_0000308", "laboratory processing batch", SIO + "SIO_000006")
defineClass("RAK_0000309", "DNA extraction process", SIO + "SIO_000006")
manager.addAxiom(newOntology, df.getOWLSubClassOfAxiom(
        df.getOWLClass(IRI.create(BASE + "RAK_0000309")),
        df.getOWLClass(IRI.create(SIO + "SIO_000994"))))
defineClass("RAK_0000310", "PCR batch", BASE + "RAK_0000308")
defineClass("RAK_0000311", "amplicon PCR process", SIO + "SIO_000006")
manager.addAxiom(newOntology, df.getOWLSubClassOfAxiom(
        df.getOWLClass(IRI.create(BASE + "RAK_0000311")),
        df.getOWLClass(IRI.create(SIO + "SIO_000994"))))
defineClass("RAK_0000312", "control sequencing assay", SIO + "SIO_000006")
defineClass("RAK_0000313", "control metadata assertion", SIO + "SIO_001183")
defineClass("RAK_0000314", "control metadata status", SIO + "SIO_001326")
defineClass("RAK_0000315", "control assertion confidence", SIO + "SIO_000436")
defineClass("RAK_0000316", "control composition specification", SIO + "SIO_000315")
defineClass("RAK_0000317", "expected-taxon assertion", BASE + "RAK_0000313")
defineClass("RAK_0000318", "control-derived FASTQ dataset", BASE + "RAK_0000063")
defineClass("RAK_0000319", "control metadata disposition", SIO + "SIO_001183")
defineClass("RAK_0000320", "unresolved control metadata disposition", BASE + "RAK_0000319")
defineClass("RAK_0000321", "inapplicable control metadata disposition", BASE + "RAK_0000319")
defineClass("RAK_0000322", "control metadata field descriptor", SIO + "SIO_000136")
defineClass("RAK_0000323", "asserted-relation descriptor", SIO + "SIO_000136")

manager.addAxiom(newOntology, df.getOWLDisjointClassesAxiom(
        df.getOWLClass(IRI.create(BASE + "RAK_0000304")),
        df.getOWLClass(IRI.create(BASE + "RAK_0000305"))))
manager.addAxiom(newOntology, df.getOWLDisjointClassesAxiom(
        df.getOWLClass(IRI.create(BASE + "RAK_0000306")),
        df.getOWLClass(IRI.create(BASE + "RAK_0000307"))))

// --- Sequencing QC TBox classes (RAK_0000200-0000224) ---
// Process
defineClass("RAK_0000200", "Sequencing QC Process", SIO + "SIO_000006")
// Qualities (parent + forward/reverse)
defineClass("RAK_0000201", "sequence count quality", PATO + "0000070")
defineClass("RAK_0000202", "forward sequence count quality", BASE + "RAK_0000201")
defineClass("RAK_0000203", "reverse sequence count quality", BASE + "RAK_0000201")
defineClass("RAK_0000204", "GC content quality", PATO + "0000033")
defineClass("RAK_0000205", "forward GC content quality", BASE + "RAK_0000204")
defineClass("RAK_0000206", "reverse GC content quality", BASE + "RAK_0000204")
defineClass("RAK_0000207", "duplicate rate quality", PATO + "0001470")
defineClass("RAK_0000208", "forward duplicate rate quality", BASE + "RAK_0000207")
defineClass("RAK_0000209", "reverse duplicate rate quality", BASE + "RAK_0000207")
defineClass("RAK_0000210", "read length quality", PATO + "0000122")
defineClass("RAK_0000211", "forward read length quality", BASE + "RAK_0000210")
defineClass("RAK_0000212", "reverse read length quality", BASE + "RAK_0000210")
// Values (parent + forward/reverse)
defineClass("RAK_0000213", "sequence count value", SIO + "SIO_000794")
defineClass("RAK_0000214", "forward sequence count value", BASE + "RAK_0000213")
defineClass("RAK_0000215", "reverse sequence count value", BASE + "RAK_0000213")
defineClass("RAK_0000216", "GC content value", SIO + "SIO_001088")
defineClass("RAK_0000217", "forward GC content value", BASE + "RAK_0000216")
defineClass("RAK_0000218", "reverse GC content value", BASE + "RAK_0000216")
defineClass("RAK_0000219", "duplicate rate value", SIO + "SIO_000052")
defineClass("RAK_0000220", "forward duplicate rate value", BASE + "RAK_0000219")
defineClass("RAK_0000221", "reverse duplicate rate value", BASE + "RAK_0000219")
defineClass("RAK_0000222", "read length value", SIO + "SIO_000041")
defineClass("RAK_0000223", "forward read length value", BASE + "RAK_0000222")
defineClass("RAK_0000224", "reverse read length value", BASE + "RAK_0000222")

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
defineObjectProp("RAK_2000090", "has control metadata status", "Links a control assertion or disposition to its controlled status.", SIO + "SIO_000008")
defineObjectProp("RAK_2000091", "has control assertion confidence", "Links a control metadata assertion to an evidence-calibrated confidence descriptor.", SIO + "SIO_000008")
defineObjectProp("RAK_2000092", "has expected taxon", "Links a confirmed control composition specification to a taxon expected in that material.", SIO + "SIO_000332")
defineObjectProp("RAK_2000093", "has assertion subject", "Identifies the subject of a reified control metadata assertion.")
defineObjectProp("RAK_2000094", "has asserted relation descriptor", "Links a control metadata assertion to a controlled relation descriptor.")
defineObjectProp("RAK_2000095", "has assertion object", "Identifies the IRI object of a reified control metadata assertion.")
defineObjectProp("RAK_2000097", "concerns control metadata field", "Links a metadata disposition to the controlled field it concerns.")

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
defineDataProp("RAK_2000025", "has lineage string", "The taxonomic lineage as a semicolon-separated rank string.", SIO + "SIO_000300")
defineDataProp("RAK_2000026", "has absolute abundance value", "The numerical value of an absolute taxon abundance (read-count) measurement.", SIO + "SIO_000070")

// --- Sequencing QC data properties (RAK_2000070-2000081) ---
defineDataProp("RAK_2000070", "has sequence count", "The total number of sequences in a FASTQ dataset.", SIO + "SIO_000300")
defineDataProp("RAK_2000071", "has forward sequence count", "The number of forward (R1) sequences in a paired-end FASTQ dataset.", SIO + "SIO_000300")
defineDataProp("RAK_2000072", "has reverse sequence count", "The number of reverse (R2) sequences in a paired-end FASTQ dataset.", SIO + "SIO_000300")
defineDataProp("RAK_2000073", "has GC content", "The percentage GC content of a FASTQ dataset.", SIO + "SIO_000300")
defineDataProp("RAK_2000074", "has forward GC content", "The percentage GC content of forward (R1) reads.", SIO + "SIO_000300")
defineDataProp("RAK_2000075", "has reverse GC content", "The percentage GC content of reverse (R2) reads.", SIO + "SIO_000300")
defineDataProp("RAK_2000076", "has duplicate rate", "The fraction of duplicated reads in a FASTQ dataset.", SIO + "SIO_000300")
defineDataProp("RAK_2000077", "has forward duplicate rate", "The fraction of duplicated forward (R1) reads.", SIO + "SIO_000300")
defineDataProp("RAK_2000078", "has reverse duplicate rate", "The fraction of duplicated reverse (R2) reads.", SIO + "SIO_000300")
defineDataProp("RAK_2000079", "has read length", "The mean read length of a FASTQ dataset.", SIO + "SIO_000300")
defineDataProp("RAK_2000080", "has forward read length", "The mean length of forward (R1) reads.", SIO + "SIO_000300")
defineDataProp("RAK_2000081", "has reverse read length", "The mean length of reverse (R2) reads.", SIO + "SIO_000300")
defineDataProp("RAK_2000096", "has assertion literal object", "Identifies the literal object of a reified control metadata assertion.", null)
defineDataProp("RAK_2000098", "has relation IRI lexical value", "The validated IRI lexical value represented by an asserted-relation descriptor.", null)

// Control-property domains/ranges are stated explicitly.  RAK_2000090 has no
// domain because it is shared by assertion and disposition statement classes.
def controlStatus = df.getOWLClass(IRI.create(BASE + "RAK_0000314"))
def controlConfidence = df.getOWLClass(IRI.create(BASE + "RAK_0000315"))
def controlAssertion = df.getOWLClass(IRI.create(BASE + "RAK_0000313"))
def controlDisposition = df.getOWLClass(IRI.create(BASE + "RAK_0000319"))
def compositionSpecification = df.getOWLClass(IRI.create(BASE + "RAK_0000316"))
def relationDescriptor = df.getOWLClass(IRI.create(BASE + "RAK_0000323"))
def fieldDescriptor = df.getOWLClass(IRI.create(BASE + "RAK_0000322"))
manager.addAxiom(newOntology, df.getOWLObjectPropertyRangeAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000090")), controlStatus))
manager.addAxiom(newOntology, df.getOWLObjectPropertyDomainAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000091")), controlAssertion))
manager.addAxiom(newOntology, df.getOWLObjectPropertyRangeAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000091")), controlConfidence))
manager.addAxiom(newOntology, df.getOWLObjectPropertyDomainAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000092")), compositionSpecification))
manager.addAxiom(newOntology, df.getOWLObjectPropertyDomainAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000093")), controlAssertion))
manager.addAxiom(newOntology, df.getOWLObjectPropertyDomainAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000094")), controlAssertion))
manager.addAxiom(newOntology, df.getOWLObjectPropertyRangeAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000094")), relationDescriptor))
manager.addAxiom(newOntology, df.getOWLObjectPropertyDomainAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000095")), controlAssertion))
manager.addAxiom(newOntology, df.getOWLDataPropertyDomainAxiom(
        df.getOWLDataProperty(IRI.create(BASE + "RAK_2000096")), controlAssertion))
manager.addAxiom(newOntology, df.getOWLObjectPropertyDomainAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000097")), controlDisposition))
manager.addAxiom(newOntology, df.getOWLObjectPropertyRangeAxiom(
        df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000097")), fieldDescriptor))
manager.addAxiom(newOntology, df.getOWLDataPropertyDomainAxiom(
        df.getOWLDataProperty(IRI.create(BASE + "RAK_2000098")), relationDescriptor))
manager.addAxiom(newOntology, df.getOWLDataPropertyRangeAxiom(
        df.getOWLDataProperty(IRI.create(BASE + "RAK_2000098")),
        df.getOWLDatatype(IRI.create("http://www.w3.org/2001/XMLSchema#anyURI"))))

// Property Chains
//
// Direction conventions (canonical, per SIO):
//   SIO_000215  is measurement value of      value   -> quality   (subPropOf SIO_000011 is-attribute-of)
//   SIO_000216  has measurement value        quality -> value     (subPropOf SIO_000008 has-attribute; inverse of 215)
//
// The chain below derives  quality —is-attribute-of→ bearer  from the process
// structure. It must START at the quality, so the first hop has to be
// hasMeasurementValue (000216), not isMeasurementValueOf (000215). Prior to
// 2026-05-07, this chain used 000215 as the head and was only consistent with
// reversed-direction ABox assertions in XRF/measurements (now fixed). See
// tests/measurement_pattern/ for the validation harness and
// docs/MEASUREMENT_PATTERN.md for the full design rationale.
//
//   hasMeasurementValue ∘ isOutputOf ∘ hasTarget ⊑ isAttributeOf
//   hasMeasurementValue ∘ isOutputOf ∘ hasInput  ⊑ isAttributeOf
OWLObjectProperty hasMeasurementValue = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000216"))
OWLObjectProperty isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
OWLObjectProperty hasTarget = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000291"))
OWLObjectProperty hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
OWLObjectProperty isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))
OWLObjectProperty isPartOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000068"))

manager.addAxiom(newOntology, df.getOWLSubPropertyChainOfAxiom([hasMeasurementValue, isOutputOf, hasTarget], isAttributeOf))
manager.addAxiom(newOntology, df.getOWLSubPropertyChainOfAxiom([hasMeasurementValue, isOutputOf, hasInput], isAttributeOf))
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
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix pav: <http://purl.org/pav/> .
@prefix rak: <https://rubalkhali.science/kb/> .

rak:Dataset a void:Dataset ;
    dcterms:title "Rub al-Khali Knowledge Graph" ;
    dcterms:description "A knowledge graph integrating geochemical, environmental, and metagenomic data from the Rub al-Khali desert." ;
    dcterms:creator "Robert Hoehndorf (https://orcid.org/0000-0001-8149-5890)" ;
    dcterms:publisher "Robert Hoehndorf (https://orcid.org/0000-0001-8149-5890)" ;
    dcterms:version "${version}" ;
    pav:version "${version}" ;
    pav:previousVersion "${previousVersion}" ;
    dcterms:issued "${currentTime}"^^xsd:dateTime ;
    dcterms:modified "${currentTime}"^^xsd:dateTime ;
    dcterms:identifier <https://rubalkhali.science/kb/rubalkhali.owl> .
"""
println "void.ttl regenerated. Version: ${version}"
