@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import java.io.File

def aboxFile = new File("data/processed/semantics/ontology/rubalkhali_xrf.owl")

println "Loading XRF ABox..."
def model = ModelFactory.createDefaultModel()
RDFDataMgr.read(model, aboxFile.absolutePath, Lang.RDFXML)

def checkType = { label, soilClass, protocolClass ->
    println "Validating ${label}..."
    def query = """
    PREFIX rak: <https://rubalkhali.science/kb/>
    PREFIX sio: <http://semanticscience.org/resource/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT (COUNT(DISTINCT ?process) AS ?count)
    WHERE {
      ?process a rak:RAK_0000025 .
      ?process sio:SIO_000339 ?protocolInd .
      ?protocolInd a <${protocolClass}> .
      ?process sio:SIO_000230 ?input .
      ?input a <${soilClass}> .
    }
    """
    def qexec = QueryExecutionFactory.create(QueryFactory.create(query), model)
    def results = qexec.execSelect()
    int count = results.nextSolution().getLiteral("count").getInt()
    qexec.close()
    println "  Found ${count} processes."
    return count
}

def BASE = "https://rubalkhali.science/kb/"
int surface = checkType("Surface Lab", BASE + "RAK_0000020", BASE + "RAK_0000128")
int deep = checkType("Deep Lab", BASE + "RAK_0000021", BASE + "RAK_0000228")
int rhizosphere = checkType("Rhizosphere Lab", BASE + "RAK_0000022", BASE + "RAK_0000328")

// Field measurements (should be deep soil and RAK_L000001)
println "Validating Field Deep..."
def fieldQuery = """
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>
SELECT (COUNT(DISTINCT ?process) AS ?count)
WHERE {
  ?process a rak:RAK_0000025 .
  ?process sio:SIO_000339 rak:RAK_L000001 .
  ?process sio:SIO_000230 ?input .
  ?input a rak:RAK_0000021 . # Deep soil
}
"""
def qexec = QueryExecutionFactory.create(QueryFactory.create(fieldQuery), model)
int fieldCount = qexec.execSelect().nextSolution().getLiteral("count").getInt()
qexec.close()
println "  Found ${fieldCount} field processes."

if (surface > 0 && deep > 0 && rhizosphere > 0 && fieldCount > 0) {
    println "SUCCESS: All measurement categories reproduced."
} else {
    println "FAILURE: Some categories are empty."
    System.exit(1)
}
