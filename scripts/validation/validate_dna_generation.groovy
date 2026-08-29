@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import org.apache.jena.riot.Lang
import org.apache.jena.riot.RDFDataMgr
import java.io.File

def model = ModelFactory.createDefaultModel()
RDFDataMgr.read(model, new File("data/processed/ontology/rubalkhali_samples.owl").absolutePath, Lang.RDFXML)
RDFDataMgr.read(model, new File("data/processed/ontology/rubalkhali_dna.owl").absolutePath, Lang.RDFXML)

def sparqlQuery = """
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX rak: <http://rubalkhali.science/kb#>
PREFIX rak_kb: <https://rubalkhali.science/kb/>

SELECT ?soilSampleLabel ?dnaExtractLabel ?protocolLabel ?concentrationValue
WHERE {
  ?dnaExtract a rak:DNAExtract ;
              rdfs:label ?dnaExtractLabel .
  ?extProcess sio:SIO_000229 ?dnaExtract ;
              sio:SIO_000230 ?soilSample .
  ?soilSample rdfs:label ?soilSampleLabel .
  FILTER(CONTAINS(?soilSampleLabel, "Trip2"))
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
ORDER BY ?soilSampleLabel
LIMIT 40
"""

def qexec = QueryExecutionFactory.create(QueryFactory.create(sparqlQuery), model)
def results = qexec.execSelect()
println String.format("%-30s | %-40s | %-20s | %-15s", "Soil Sample", "DNA Extract", "Protocol", "Conc (ng/uL)")
println "-" * 115
while (results.hasNext()) {
    def soln = results.nextSolution()
    def sample = soln.getLiteral("soilSampleLabel")?.lexicalForm ?: ""
    def dna = soln.getLiteral("dnaExtractLabel")?.lexicalForm ?: ""
    def proto = soln.getLiteral("protocolLabel")?.lexicalForm ?: ""
    def conc = soln.getLiteral("concentrationValue")?.lexicalForm ?: "N/A"
    println String.format("%-30s | %-40s | %-20s | %-15s", sample, dna, proto, conc)
}
qexec.close()