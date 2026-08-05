@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.rdf.model.*
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import org.apache.jena.vocabulary.RDF
import org.apache.jena.vocabulary.RDFS
import java.io.File

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def DC = "http://purl.org/dc/elements/1.1/"

def xrfFile = new File("data/processed/semantics/ontology/rubalkhali_xrf.owl")
def sitesFile = new File("data/processed/semantics/ontology/rubalkhali_sites.owl")
def samplesFile = new File("data/processed/semantics/ontology/rubalkhali_samples.owl")
def fieldFile = new File("data/processed/geochemistry/xrf_field_table.tsv")
def labFiles = [
    new File("data/processed/geochemistry/xrf_lab_table_filtered.tsv"),
    new File("data/processed/geochemistry/xrf_lab_table_trips1-4.tsv"),
]

([xrfFile, sitesFile, samplesFile, fieldFile] + labFiles).each { file ->
    if (!file.exists()) {
        println "FAILURE: Required validation input is missing: ${file}"
        System.exit(1)
    }
}

def loadModel = { file ->
    def model = ModelFactory.createDefaultModel()
    RDFDataMgr.read(model, file.absolutePath, Lang.RDFXML)
    return model
}

println "Loading XRF, site, and collected-sample ABoxes..."
def xrfModel = loadModel(xrfFile)
def sitesModel = loadModel(sitesFile)
def samplesModel = loadModel(samplesFile)

def processClass = xrfModel.createResource(BASE + "RAK_0000025")
def samplingSiteClass = sitesModel.createResource(BASE + "RAK_0000002")
def fieldProtocol = xrfModel.createResource(BASE + "RAK_L000001")
def hasInput = xrfModel.createProperty(SIO + "SIO_000230")
def hasTarget = xrfModel.createProperty(SIO + "SIO_000291")
def hasOutput = xrfModel.createProperty(SIO + "SIO_000229")
def isSpecifiedBy = xrfModel.createProperty(SIO + "SIO_000339")
def isMeasurementValueOf = xrfModel.createProperty(SIO + "SIO_000215")
def hasAttribute = xrfModel.createProperty(SIO + "SIO_000008")
def isAttributeOf = xrfModel.createProperty(SIO + "SIO_000011")
def dcIdentifier = xrfModel.createProperty(DC + "identifier")

int errors = 0
def fail = { message ->
    println "  [FAIL] ${message}"
    errors++
}

def siteIdToResource = [:]
sitesModel.listResourcesWithProperty(RDF.type, samplingSiteClass).each { site ->
    def label = site.getProperty(RDFS.label)?.string
    def match = label =~ /^Site (\d+)$/
    if (match) siteIdToResource[match[0][1]] = site
}

def expectedFieldPairs = [] as Set
def fieldLines = fieldFile.readLines()
def fieldHeader = fieldLines[0].split("\t", -1) as List
int fieldSiteColumn = fieldHeader.indexOf("SiteID")
int fieldTestColumn = fieldHeader.indexOf("TestID")
fieldLines.drop(1).findAll { it.trim() }.each { line ->
    def parts = line.split("\t", -1)
    def site = siteIdToResource[parts[fieldSiteColumn]]
    if (!site) {
        fail("Field TestID ${parts[fieldTestColumn]} names unknown Site ${parts[fieldSiteColumn]}")
    } else {
        expectedFieldPairs << "${parts[fieldTestColumn]}|${site.getURI()}"
    }
}

int expectedLabCount = labFiles.sum { file ->
    Math.max(0, file.readLines().count { it.trim() } - 1)
}

def processes = xrfModel.listResourcesWithProperty(RDF.type, processClass).toList()
def fieldProcesses = processes.findAll { it.hasProperty(isSpecifiedBy, fieldProtocol) }
def labProcesses = processes.findAll { !it.hasProperty(isSpecifiedBy, fieldProtocol) }
def actualFieldPairs = [] as Set

println "Validating ${fieldProcesses.size()} field XRF sessions..."
fieldProcesses.each { process ->
    def targets = process.listProperties(hasTarget).toList()
    def inputs = process.listProperties(hasInput).toList()
    def identifiers = process.listProperties(dcIdentifier).toList()

    if (targets.size() != 1) fail("${process.getURI()} has ${targets.size()} field targets; expected exactly one")
    if (!inputs.isEmpty()) fail("${process.getURI()} fabricates a field material/sample input")
    if (identifiers.size() != 1 || !identifiers[0].object.isLiteral()) {
        fail("${process.getURI()} does not retain exactly one literal TestID")
        return
    }
    if (targets.size() != 1 || !targets[0].object.isResource()) return

    def target = targets[0].resource
    def targetInSites = sitesModel.getResource(target.getURI())
    if (!sitesModel.contains(targetInSites, RDF.type, samplingSiteClass)) {
        fail("${process.getURI()} target ${target.getURI()} is not a recorded SamplingSite")
    }
    def testId = identifiers[0].literal.string
    actualFieldPairs << "${testId}|${target.getURI()}"

    process.listProperties(hasOutput).each { outputStatement ->
        def value = outputStatement.resource
        def qualityStatements = value.listProperties(isMeasurementValueOf).toList()
        if (qualityStatements.size() != 1 || !qualityStatements[0].object.isResource()) {
            fail("${value.getURI()} does not identify exactly one measured quality")
            return
        }
        def quality = qualityStatements[0].resource
        if (!target.hasProperty(hasAttribute, quality) ||
                !quality.hasProperty(isAttributeOf, target)) {
            fail("${quality.getURI()} is not attributed to field target ${target.getURI()}")
        }
    }
}

if (actualFieldPairs != expectedFieldPairs) {
    def missing = expectedFieldPairs - actualFieldPairs
    def extra = actualFieldPairs - expectedFieldPairs
    fail("Field TestID/site mapping differs from TSV; missing=${missing}, extra=${extra}")
}

println "Validating ${labProcesses.size()} laboratory XRF processes..."
labProcesses.each { process ->
    def inputs = process.listProperties(hasInput).toList()
    def targets = process.listProperties(hasTarget).toList()
    if (inputs.size() != 1 || !inputs[0].object.isResource()) {
        fail("${process.getURI()} has ${inputs.size()} laboratory inputs; expected one collected sample")
        return
    }
    if (!targets.isEmpty()) fail("${process.getURI()} incorrectly uses a field-site target")

    def input = inputs[0].resource
    if (!samplesModel.containsResource(samplesModel.getResource(input.getURI()))) {
        fail("${process.getURI()} input ${input.getURI()} is not a collected sample")
    }
    process.listProperties(hasOutput).each { outputStatement ->
        def value = outputStatement.resource
        def qualityStatements = value.listProperties(isMeasurementValueOf).toList()
        if (qualityStatements.size() == 1 && qualityStatements[0].object.isResource()) {
            def quality = qualityStatements[0].resource
            if (!input.hasProperty(hasAttribute, quality) ||
                    !quality.hasProperty(isAttributeOf, input)) {
                fail("${quality.getURI()} is not attributed to laboratory input ${input.getURI()}")
            }
        }
    }
}

def fabricatedFieldLabels = xrfModel.listStatements(null, RDFS.label, (RDFNode) null)
    .toList()
    .findAll { it.object.isLiteral() && it.object.asLiteral().string.startsWith("Field deep soil material") }
if (!fabricatedFieldLabels.isEmpty()) {
    fail("Found ${fabricatedFieldLabels.size()} fabricated field-material individuals")
}

if (fieldProcesses.size() != expectedFieldPairs.size()) {
    fail("Generated ${fieldProcesses.size()} field processes; expected ${expectedFieldPairs.size()}")
}
if (labProcesses.size() != expectedLabCount) {
    fail("Generated ${labProcesses.size()} laboratory processes; expected ${expectedLabCount}")
}

if (errors == 0) {
    println "SUCCESS: ${fieldProcesses.size()} field sessions target recorded sites with TestIDs; " +
        "${labProcesses.size()} laboratory processes retain collected-sample inputs."
} else {
    println "FAILURE: XRF field/laboratory separation has ${errors} error(s)."
    System.exit(1)
}
