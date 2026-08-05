@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import java.io.File

def owlFile = new File("data/processed/ontology/rubalkhali_xrf.owl")
def model = ModelFactory.createDefaultModel()
RDFDataMgr.read(model, owlFile.absolutePath, Lang.RDFXML)

def sparqlQuery = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rak: <https://rubalkhali.science/kb/>
PREFIX sio: <http://semanticscience.org/resource/>

SELECT ?processLabel ?lePercentage
WHERE {
  ?quality a ?qualityClass .
  ?qualityClass rdfs:label "Light Elements concentration" .
  # SIO-canonical: value sio:SIO_000215 quality (value is subject).
  ?value sio:SIO_000215 ?quality .
  ?value rak:RAK_2000012 ?lePercentage .
  ?value sio:SIO_000232 ?process .
  ?process rdfs:label ?processLabel .
}
ORDER BY DESC(?lePercentage)
"""

def qexec = QueryExecutionFactory.create(QueryFactory.create(sparqlQuery), model)
def results = qexec.execSelect()
int count = 0
println "Results for LE query:"
println "Process | Percentage"
println "--------------------"
while (results.hasNext()) {
    def soln = results.nextSolution()
    println "${soln.getLiteral("processLabel").getLexicalForm()} | ${soln.getLiteral("lePercentage").getLexicalForm()}"
    count++
}
qexec.close()
println "Total results: ${count}"
