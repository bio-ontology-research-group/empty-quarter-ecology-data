@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.apache.poi.ss.usermodel.*
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import java.io.File
import java.util.regex.Pattern

/**
 * Script to generate Samples ABox.
 * References terms from rubalkhali.owl.
 */

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def DC = "http://purl.org/dc/elements/1.1/"

def SAMPLE_TYPE_MAP = ["surface": "RAK_0000020", "deep": "RAK_0000021", "rhizosphere": "RAK_0000022", "plant": "RAK_0000023", "soil": "RAK_0000020"]
def DISPLAY_TYPE_MAP = ["surface": "surface soil", "deep": "deep soil", "rhizosphere": "rhizosphere soil", "plant": "plant matter"]

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()

// 1. Load Site Mappings from sites.owl
def siteLabelToIri = [:]
def sitesFile = new File("data/processed/ontology/rubalkhali_sites.owl")
if (sitesFile.exists()) {
    println "Mapping site IRIs from sites.owl..."
    def sOnt = manager.loadOntologyFromOntologyDocument(sitesFile)
    sOnt.getIndividualsInSignature().each { ind ->
        sOnt.getAnnotationAssertionAxioms(ind.getIRI()).each { ax ->
            if (ax.getProperty().isLabel()) {
                def label = ax.getValue().asLiteral().get().getLiteral().trim()
                siteLabelToIri[label] = ind.getIRI()
                if (label.startsWith("Site ")) siteLabelToIri[label.substring(5)] = ind.getIRI()
            }
        }
    }
    manager.removeOntology(sOnt)
}
def getSiteIri = { siteId ->
    def cleanId = siteId.toString().replaceAll(/\.0$/, "").trim()
    return siteLabelToIri["Site ${cleanId}"] ?: siteLabelToIri[cleanId]
}

// Numeric source identifiers 61--64 were used only in Trip1.  Their
// coordinate-confirmed aliases point to existing named site individuals.
// Preserve the source identifiers in sample labels and identifiers, but use
// the canonical site IRI for graph links.  Fail closed if a confirmed alias
// no longer agrees with the generated site module.
def siteAliases = [:]
def aliasesFile = new File("data/metadata/samples/site_aliases.tsv")
if (aliasesFile.exists()) {
    def rows = aliasesFile.readLines()
    if (rows.size() > 1) {
        def header = rows[0].split("\t", -1)
        def cSheet = header.findIndexOf { it == "source_sheet" }
        def cSource = header.findIndexOf { it == "source_site_id" }
        def cLabel = header.findIndexOf { it == "canonical_site_label" }
        def cIri = header.findIndexOf { it == "canonical_site_iri" }
        def cStatus = header.findIndexOf { it == "status" }
        def required = [cSheet, cSource, cLabel, cIri, cStatus]
        if (required.any { it < 0 }) {
            throw new IllegalStateException(
                "site_aliases.tsv is missing a required column"
            )
        }
        rows.drop(1).each { line ->
            if (!line.trim()) return
            def parts = line.split("\t", -1)
            if (parts.size() <= required.max()) {
                throw new IllegalStateException(
                    "Malformed row in site_aliases.tsv: ${line}"
                )
            }
            if (!parts[cStatus].equalsIgnoreCase("confirmed")) return
            def sourceSheet = parts[cSheet].trim()
            def sourceSite = parts[cSource].trim()
            def targetLabel = parts[cLabel].trim()
            def declaredIri = IRI.create(parts[cIri].trim())
            def resolvedIri = siteLabelToIri[targetLabel]
            if (!resolvedIri || resolvedIri != declaredIri) {
                throw new IllegalStateException(
                    "Confirmed site alias ${sourceSheet}/${sourceSite} " +
                    "does not match ${targetLabel} in rubalkhali_sites.owl"
                )
            }
            def key = "${sourceSheet}|${sourceSite}"
            if (siteAliases.containsKey(key)) {
                throw new IllegalStateException(
                    "Duplicate confirmed site alias: ${key}"
                )
            }
            siteAliases[key] = [
                label: targetLabel,
                iri: declaredIri,
                visitKey: targetLabel.replaceFirst(/^Site /, "")
            ]
        }
    }
}

def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_samples.owl"))

// Confirmed corrections are maintained as a transparent overlay so the
// historical workbook remains unchanged and every correction is auditable.
def sampleFieldCorrections = [:]
def correctionsFile = new File("data/metadata/samples/sample_corrections.tsv")
if (correctionsFile.exists()) {
    def rows = correctionsFile.readLines()
    if (rows.size() > 1) {
        def header = rows[0].split("\t", -1)
        def cSample = header.findIndexOf { it == "sample_id" }
        def cField = header.findIndexOf { it == "field" }
        def cValue = header.findIndexOf { it == "corrected_value" }
        def cStatus = header.findIndexOf { it == "status" }
        rows.drop(1).each { line ->
            def parts = line.split("\t", -1)
            if (parts.size() > [cSample, cField, cValue, cStatus].max() &&
                    parts[cStatus].equalsIgnoreCase("confirmed")) {
                sampleFieldCorrections["${parts[cSample]}|${parts[cField]}"] = parts[cValue]
            }
        }
    }
}

// Properties (Referencing rubalkhali.owl)
def hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
def isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
def hasMember = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000059"))
def isDerivedFrom = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000244"))
def isPartOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000068"))
def hasTarget = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000291"))
def dcIdentifier = df.getOWLAnnotationProperty(IRI.create(DC + "identifier"))
def rdfsLabel = df.getRDFSLabel()

// Classes (Referencing rubalkhali.owl)
def samplingProcessClass = df.getOWLClass(IRI.create(BASE + "RAK_0000024"))
def collOfReplicatesClass = df.getOWLClass(IRI.create(SIO + "SIO_001419"))
def replicateClass = df.getOWLClass(IRI.create(SIO + "SIO_001418"))

int sampleCounter = 1; int collCounter = 1; int processCounter = 100001 
def addLabel = { iri, label -> manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(rdfsLabel, df.getOWLLiteral(label)))) }
def addIdentifier = { iri, id -> manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(dcIdentifier, df.getOWLLiteral(id)))) }

def visitMap = [:]
def measurementsFile = new File("data/processed/ontology/rubalkhali_measurements.owl")
if (measurementsFile.exists()) {
    def mOnt = manager.loadOntologyFromOntologyDocument(measurementsFile)
    mOnt.getIndividualsInSignature().each { ind ->
        mOnt.getAnnotationAssertionAxioms(ind.getIRI()).each { ax ->
            if (ax.getProperty().isLabel()) {
                def label = ax.getValue().asLiteral().get().getLiteral()
                def match = label =~ /Visit to Site (.+?) during (Trip\d+)/
                if (match) visitMap["${match[0][2].toLowerCase()}|${match[0][1]}"] = ind.getIRI()
            }
        }
    }
    manager.removeOntology(mOnt)
}

def excelFile = new File("data/metadata/samples/Sample_Mastersheet.xlsx")
FileInputStream fis = new FileInputStream(excelFile)
Workbook workbook = new XSSFWorkbook(fis)

(0..<workbook.getNumberOfSheets()).each { i ->
    Sheet sheet = workbook.getSheetAt(i); if (sheet.getSheetName() == "Plants") return
    String tripSheetName = sheet.getSheetName().toLowerCase()
    String tripDisplayName = sheet.getSheetName().replace("-", " ").capitalize()
    Row headerRow = sheet.getRow(0); if (!headerRow) return
    def headers = [:]; headerRow.each { cell -> try { headers[cell.getStringCellValue().toLowerCase().trim()] = cell.getColumnIndex() } catch(e){}
    }
    def colSite = headers["site"]; def colId = headers["name"]; def colType = headers["compartment"]
    if (colSite == null || colType == null || colId == null) return
    def groupedRows = [: ]
    sheet.drop(1).each { row ->
        def sC = row.getCell(colSite); def tC = row.getCell(colType); def iC = row.getCell(colId)
        if (sC && tC && iC) {
            String sampleId = iC.toString().trim()
            String sId = (sampleFieldCorrections["${sampleId}|site"] ?: sC.toString()).replaceAll(/\.0$/, "").trim()
            String type = tC.toString().toLowerCase().trim()
            if (sId && type) { def key = "${sId}|${type}"; if (!groupedRows[key]) groupedRows[key] = []; groupedRows[key] << row }
        }
    }
    groupedRows.each {
        key, rows ->
        def parts = key.split(Pattern.quote("|")); def siteId = parts[0]; def type = parts[1]; def displayType = DISPLAY_TYPE_MAP[type] ?: type
        def siteAlias = siteAliases["${sheet.getSheetName()}|${siteId}"]
        def siteIri = siteAlias?.iri ?: getSiteIri(siteId); if (!siteIri) return
        def siteInd = df.getOWLNamedIndividual(siteIri)
        def visitKey = siteAlias?.visitKey ?: siteId
        def visitIri = visitMap["${tripSheetName}|${visitKey}"]
        def procInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(samplingProcessClass, procInd))
        addLabel(procInd.getIRI(), "Sampling process for ${displayType} at Site ${siteId} (${tripDisplayName})")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasTarget, procInd, siteInd))
        if (visitIri) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isPartOf, procInd, df.getOWLNamedIndividual(visitIri)))
        def collInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_7" + String.format("%06d", collCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(collOfReplicatesClass, collInd))
        addLabel(collInd.getIRI(), "Collection of ${displayType} replicates from Site ${siteId} (${tripDisplayName})")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, collInd, procInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, collInd))
        rows.eachWithIndex {
            row, idx ->
            String sId = row.getCell(colId).toString().trim(); int repNum = idx + 1
            def sInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_6" + String.format("%06d", sampleCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(replicateClass, sInd))
            def typeId = SAMPLE_TYPE_MAP[type] ?: "SIO_001050"
            def typeIri = typeId.startsWith("RAK") ? BASE + typeId : SIO + typeId
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLClass(IRI.create(typeIri)), sInd))
            addLabel(sInd.getIRI(), "Sample ${sId} (Rep ${repNum}) - ${displayType} from Site ${siteId} (${tripDisplayName})")
            addIdentifier(sInd.getIRI(), sId)
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMember, collInd, sInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isDerivedFrom, sInd, siteInd))
        }
    }
}

def plantsTsv = new File("data/metadata/samples/plants.tsv")
if (plantsTsv.exists()) {
    def lines = plantsTsv.readLines()
    if (lines.size() > 1) {
        def header = lines[0].split("\t")
        def cS = header.findIndexOf { it.equalsIgnoreCase("site") }; def cT = header.findIndexOf { it.equalsIgnoreCase("trip") }
        def cI = header.findIndexOf { it.equalsIgnoreCase("identifier") }; def cTy = header.findIndexOf { it.equalsIgnoreCase("compartment") }
        lines.drop(1).each {
            line ->
            def parts = line.split("\t"); if (parts.size() <= cI) return
            def sId = parts[cS]; def tripKey = parts[cT].toLowerCase(); def sampleId = parts[cI]; def type = parts[cTy]; def displayType = DISPLAY_TYPE_MAP[type] ?: type
            def siteIri = getSiteIri(sId); if (!siteIri) return
            def siteInd = df.getOWLNamedIndividual(siteIri); def visitIri = visitMap["${tripKey}|${sId}"]
            def procInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(samplingProcessClass, procInd))
            addLabel(procInd.getIRI(), "Sampling process for ${displayType} at Site ${sId} (${parts[cT]})")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasTarget, procInd, siteInd))
            if (visitIri) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isPartOf, procInd, df.getOWLNamedIndividual(visitIri)))
            def collInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_7" + String.format("%06d", collCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(collOfReplicatesClass, collInd))
            addLabel(collInd.getIRI(), "Collection of ${displayType} replicates from Site ${sId} (${parts[cT]})")
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, collInd, procInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, collInd))
            def sInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_6" + String.format("%06d", sampleCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(replicateClass, sInd))
            def typeIri = BASE + (SAMPLE_TYPE_MAP[type] ?: "RAK_0000023")
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLClass(IRI.create(typeIri)), sInd))
            addLabel(sInd.getIRI(), "Sample ${sampleId} (Rep 1) - ${displayType} from Site ${sId} (${parts[cT]})")
            addIdentifier(sInd.getIRI(), sampleId)
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMember, collInd, sInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isDerivedFrom, sInd, siteInd))
        }
    }
}
manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_samples.owl").toURI()))
println "Success: Generated rubalkhali_samples.owl using centralized TBox."
