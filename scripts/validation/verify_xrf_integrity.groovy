@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import java.io.File

def tboxFile = new File("data/processed/ontology/rubalkhali.owl")
def sitesFile = new File("data/processed/ontology/rubalkhali_sites.owl")
def aboxFile = new File("data/processed/ontology/rubalkhali_xrf.owl")
def siteId = "10"
def tests = ["5847", "5848"]

println "Loading RDF Models (TBox and XRF ABox)..."
def model = ModelFactory.createDefaultModel()
if (tboxFile.exists()) RDFDataMgr.read(model, tboxFile.absolutePath, Lang.RDFXML)
if (sitesFile.exists()) RDFDataMgr.read(model, sitesFile.absolutePath, Lang.RDFXML)
if (aboxFile.exists()) RDFDataMgr.read(model, aboxFile.absolutePath, Lang.RDFXML)

def sparqlQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>

SELECT ?testId ?analyte ?concentration ?error
WHERE {
  ?process a rak:RAK_0000025 ;
           sio:SIO_000339 rak:RAK_L000001 ;
           sio:SIO_000291 ?site ;
           dc:identifier ?testId .
  ?site a rak:RAK_0000002 ;
        rdfs:label "Site ${siteId}" ;
        sio:SIO_000008 ?quality .
  ?quality sio:SIO_000011 ?site .
  # SIO-canonical: value sio:SIO_000215 quality (value is subject).
  ?value sio:SIO_000215 ?quality .
  ?value sio:SIO_000232 ?process ; rak:RAK_2000012 ?concentration .
  OPTIONAL { ?value rak:RAK_2000013 ?error . }
  ?quality a ?qualityClass .
  ?qualityClass rdfs:label ?analyte .
  FILTER(?qualityClass != rak:RAK_0000029)
}
"""

def rdfData = [:]
def rdfErrors = [:]
def qexec = QueryExecutionFactory.create(QueryFactory.create(sparqlQuery), model)
def results = qexec.execSelect()
while (results.hasNext()) {
    def soln = results.nextSolution()
    def testId = soln.getLiteral("testId").getLexicalForm()
    def analyte = soln.getLiteral("analyte").getLexicalForm().split(" ")[0]
    rdfData["${testId}|${analyte}"] = soln.getLiteral("concentration").getDouble()
    if (soln.contains("error")) {
        rdfErrors["${testId}|${analyte}"] = soln.getLiteral("error").getDouble()
    }
}
qexec.close()

// Load field XRF merged TSV (source of truth for expected values)
def fieldTsv = new File("data/processed/geochemistry/xrf_field_table.tsv")
if (!fieldTsv.exists()) {
    println "ERROR: Field XRF TSV not found: ${fieldTsv}"
    System.exit(1)
}

def tsvLines = fieldTsv.readLines()
def tsvHeader = tsvLines[0].split("\t") as List
def colSiteId = tsvHeader.indexOf("SiteID")
def colTestId  = tsvHeader.indexOf("TestID")
def colLe      = tsvHeader.indexOf("LE")
def colLeErr   = tsvHeader.indexOf("LE_error")

// Index all rows for this site
def tsvRows = [:]
tsvLines.drop(1).each { line ->
    def parts = line.split("\t")
    if (parts[colSiteId] == siteId) {
        tsvRows[parts[colTestId]] = parts
    }
}

int errors = 0
tests.each { testId ->
    println "Verifying Test ${testId} against field TSV..."
    def parts = tsvRows[testId]
    if (!parts) {
        println "  [FAIL] Test ${testId} not found in field TSV for Site ${siteId}"
        errors++
        return
    }

    // Check LE (key is "Light" because class label starts "Light Elements ..." and we split on space)
    double expectedLe    = parts[colLe].toDouble()
    double expectedLeErr = parts[colLeErr].toDouble()
    def actualLe = rdfData["${testId}|Light"]
    if (actualLe == null) {
        println "  [FAIL] LE not found in RDF for test ${testId}"
        errors++
    } else if (Math.abs(actualLe - expectedLe) > 0.0001) {
        println "  [FAIL] LE Conc mismatch: Expected ${expectedLe}, found ${actualLe}"
        errors++
    } else {
        println "  [OK]   LE Conc = ${actualLe}"
    }

    def actualLeErr = rdfErrors["${testId}|Light"] ?: 0.0
    if (expectedLeErr > 0 && Math.abs(actualLeErr - expectedLeErr) > 0.0001) {
        println "  [FAIL] LE Error mismatch: Expected ${expectedLeErr}, found ${actualLeErr}"
        errors++
    }

    // Check all analyte columns from TSV (skip metadata and _error columns)
    def errorColSet = tsvHeader.findAll { it.endsWith("_error") }.toSet()
    def metaColSet  = ["SiteID", "TestID", "LE", "LE_error"].toSet()

    tsvHeader.eachWithIndex { col, idx ->
        if (metaColSet.contains(col) || errorColSet.contains(col)) return
        double expectedConc = parts[idx].toDouble()
        if (expectedConc == 0) return  // zero values are not stored in RDF

        def errIdx = tsvHeader.indexOf("${col}_error")
        double expectedErr = (errIdx >= 0) ? parts[errIdx].toDouble() : 0.0

        def actualConc = rdfData["${testId}|${col}"]
        if (actualConc == null) {
            println "  [FAIL] ${col} not found in RDF for test ${testId} (expected ${expectedConc})"
            errors++
        } else if (Math.abs(actualConc - expectedConc) > 0.0001) {
            println "  [FAIL] ${col} Conc mismatch: Expected ${expectedConc}, found ${actualConc}"
            errors++
        } else {
            println "  [OK]   ${col} Conc = ${actualConc}"
        }

        if (expectedErr > 0) {
            def actualErr = rdfErrors["${testId}|${col}"] ?: 0.0
            if (Math.abs(actualErr - expectedErr) > 0.0001) {
                println "  [FAIL] ${col} Error mismatch: Expected ${expectedErr}, found ${actualErr}"
                errors++
            }
        }
    }
}

if (errors == 0) println "INTEGRITY CHECK PASSED: RDF values match field TSV expectations."
else {
    println "INTEGRITY CHECK FAILED with ${errors} errors."
    System.exit(1)
}
