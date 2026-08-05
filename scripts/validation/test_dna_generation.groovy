@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import java.io.File

/**
 * Automated test script to verify DNA extraction data in the knowledge base.
 * Checks specific samples for expected Protocol and Concentration values.
 */

// Define expected results (Ground Truth from Excel/Manual verification)
def expectedData = [
    "T1Dr1": [protocol: "Protocol: PowerSoil", conc: "0.6052561008"],
    "T1Dr3": [protocol: "Protocol: Pro",       conc: "0.329"],
    "T1Sr1": [protocol: "Protocol: Pro",       conc: "0.0"],
    "T2PRr1": [protocol: "Protocol: PowerSoil", conc: "23.29766693"]
]

println "Loading RDF models..."
def model = ModelFactory.createDefaultModel()
try {
    RDFDataMgr.read(model, new File("data/processed/ontology/rubalkhali_samples.owl").absolutePath, Lang.RDFXML)
    RDFDataMgr.read(model, new File("data/processed/ontology/rubalkhali_dna.owl").absolutePath, Lang.RDFXML)
} catch (Exception e) {
    println "Error loading ontology files: ${e.message}"
    System.exit(1)
}

println "Executing SPARQL query..."
def sparqlQuery = """
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rak: <http://rubalkhali.science/kb#>
PREFIX rak_kb: <https://rubalkhali.science/kb/>

SELECT ?soilSampleLabel ?protocolLabel ?concentrationValue
WHERE {
  ?dnaExtract a rak:DNAExtract ;
              rdfs:label ?dnaExtractLabel .
  ?extProcess sio:SIO_000229 ?dnaExtract ;
              sio:SIO_000230 ?soilSample .
  ?soilSample rdfs:label ?soilSampleLabel .
  
  OPTIONAL {
    ?extProcess sio:SIO_000339 ?protocol .
    ?protocol rdfs:label ?protocolLabel .
  }
  OPTIONAL {
    ?measProcess sio:SIO_000291 ?dnaExtract ;
                 sio:SIO_000229 ?quantity .
    ?quantity a <http://purl.obolibrary.org/obo/PATO_0000033> ;
              rak_kb:RAK_200002 ?concentrationValue .
  }
}
"""

def qexec = QueryExecutionFactory.create(QueryFactory.create(sparqlQuery), model)
def results = qexec.execSelect()

def actualData = [:]
while (results.hasNext()) {
    def soln = results.nextSolution()
    def fullLabel = soln.getLiteral("soilSampleLabel")?.lexicalForm ?: ""
    // Extract sample ID from label (e.g., "Sample T1Dr1 (Rep 1)...")
    // Assuming the format "Sample ID (Rep..."
    def matcher = (fullLabel =~ /Sample ([a-zA-Z0-9]+) \(/)
    if (matcher.find()) {
        def id = matcher.group(1)
        def proto = soln.getLiteral("protocolLabel")?.lexicalForm ?: "N/A"
        def conc = soln.getLiteral("concentrationValue")?.lexicalForm ?: "N/A"
        actualData[id] = [protocol: proto, conc: conc]
    }
}
qexec.close()

println "Verifying results..."
int failures = 0
expectedData.each { id, expected ->
    def actual = actualData[id]
    if (!actual) {
        println "[FAIL] Sample ${id} not found in query results."
        failures++
    } else {
        boolean protoMatch = actual.protocol == expected.protocol
        boolean concMatch = actual.conc == expected.conc // String comparison matches exact literal representation
        
        // Handle floating point comparison loosely if needed, but for now exact string match from RDF generation
        if (!concMatch) {
             try {
                 double d1 = Double.parseDouble(actual.conc)
                 double d2 = Double.parseDouble(expected.conc)
                 if (Math.abs(d1 - d2) < 0.000001) concMatch = true
             } catch(e) {}
        }

        if (protoMatch && concMatch) {
            println "[PASS] ${id}: Protocol='${actual.protocol}', Conc='${actual.conc}'"
        } else {
            println "[FAIL] ${id}:"
            if (!protoMatch) println "  Expected Protocol: '${expected.protocol}', Got: '${actual.protocol}'"
            if (!concMatch) println "  Expected Conc: '${expected.conc}', Got: '${actual.conc}'"
            failures++
        }
    }
}

if (failures == 0) {
    println "All tests passed."
    System.exit(0)
} else {
    println "${failures} test(s) failed."
    System.exit(1)
}
