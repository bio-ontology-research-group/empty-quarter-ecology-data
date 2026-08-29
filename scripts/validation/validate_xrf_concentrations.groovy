@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import java.io.File

def aboxFile = new File("data/processed/semantics/ontology/rubalkhali_xrf.owl")

if (!aboxFile.exists()) {
    println "Error: XRF ABox file not found at ${aboxFile.absolutePath}"
    System.exit(1)
}

println "Loading XRF ABox..."
def model = ModelFactory.createDefaultModel()
RDFDataMgr.read(model, aboxFile.absolutePath, Lang.RDFXML)

def sparqlQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>

SELECT ?process ?processLabel (SUM(?concentration) AS ?totalConc)
WHERE {
  ?process a rak:RAK_0000025 .
  ?process rdfs:label ?processLabel .
  ?process sio:SIO_000229 ?value .
  ?value rak:RAK_2000012 ?concentration .
  
  # Filter out oxides if elements are also present to avoid double counting?
  # Actually, the user wants ALL concentrations for a sample. 
  # But XRF usually reports EITHER elements OR oxides. 
  # In our script we captured both. 
  # A proper check should probably sum either Elements OR Oxides.
  
  # For now, let's just sum all and see. If it's > 200% it's definitely a problem.
  # But if we want to be precise:
  ?value a ?valClass .
  # Values RAK_0000500 and up are elements. 
  # Let's check the analyte name from the label or quality class.
}
GROUP BY ?process ?processLabel
"""

// Better query: group by process and analyte type (Element vs Oxide)
def elementQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>

SELECT ?process ?processLabel (SUM(?concentration) AS ?totalConc)
WHERE {
  ?process a rak:RAK_0000025 .
  ?process rdfs:label ?processLabel .
  ?process sio:SIO_000229 ?value .
  ?value rak:RAK_2000012 ?concentration .
  ?value a ?vClass .
  # SIO-canonical: value sio:SIO_000215 quality (value is subject).
  ?value sio:SIO_000215 ?quality .
  ?quality a ?qClass .
  ?qClass rdfs:label ?qLabel .
  # Elements don't have digits in their Formula (usually)
  # Oxides DO have digits (SiO2, Al2O3)
  FILTER(!REGEX(?qLabel, "[0-9]"))
}
GROUP BY ?process ?processLabel
"""

def oxideQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>

SELECT ?process ?processLabel (SUM(?concentration) AS ?totalConc)
WHERE {
  ?process a rak:RAK_0000025 .
  ?process rdfs:label ?processLabel .
  ?process sio:SIO_000229 ?value .
  ?value rak:RAK_2000012 ?concentration .
  # SIO-canonical: value sio:SIO_000215 quality (value is subject).
  ?value sio:SIO_000215 ?quality .
  ?quality a ?qClass .
  ?qClass rdfs:label ?qLabel .
  FILTER(REGEX(?qLabel, "[0-9]"))
}
GROUP BY ?process ?processLabel
"""

def checkTotals = { query, type ->
    println "Checking total concentration for ${type}..."
    int fails = 0
    def qexec = QueryExecutionFactory.create(QueryFactory.create(query), model)
    def results = qexec.execSelect()
    while (results.hasNext()) {
        def soln = results.nextSolution()
        double total = soln.getLiteral("totalConc").getDouble()
        def label = soln.getLiteral("processLabel").getLexicalForm()
        if (total > 100.001) { // Small epsilon for floating point
            println "  [FAIL] ${label}: Total ${type} Conc = ${total}%"
            fails++
        }
    }
    qexec.close()
    return fails
}

int totalFails = 0
totalFails += checkTotals(elementQuery, "Elements")
totalFails += checkTotals(oxideQuery, "Oxides")

if (totalFails == 0) {
    println "SUCCESS: All XRF measurement sums are <= 100%."
} else {
    println "FAILURE: Found ${totalFails} measurements exceeding 100%."
    System.exit(1)
}
