@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import java.io.File

def manager = OWLManager.createOWLOntologyManager()
def ontologyFile = new File("data/processed/ontology/rubalkhali_taxonomy_abox.owl")
if (!ontologyFile.exists()) {
    println "File not found: ${ontologyFile}"
    return
}

println "Loading ontology..."
def config = new OWLOntologyLoaderConfiguration()
    .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT)

def ontology = manager.loadOntologyFromOntologyDocument(new org.semanticweb.owlapi.io.FileDocumentSource(ontologyFile), config)
println "Ontology loaded."

def isAttributeOf = manager.getOWLDataFactory().getOWLObjectProperty(IRI.create("http://semanticscience.org/resource/SIO_000011"))

// Find individuals that have multiple isAttributeOf relations to FASTQ datasets
// FASTQ datasets usually have IRIs like RAK_79... or contain "FASTQ dataset" in label (though labels might not be in this file if they are in SRA ontology)
// We'll assume the user's report is about things that look like datasets.

def qualities = ontology.getIndividualsInSignature()
int issuesFound = 0
int debugCount = 0

qualities.each { ind ->
    def attributes = EntitySearcher.getObjectPropertyValues(ind, isAttributeOf, ontology).collect(java.util.stream.Collectors.toList())
    
    def datasetAttributes = attributes.findAll { it.toString().contains("RAK_779") } 
    
    if (datasetAttributes.size() > 1) {
        println "Issue found: Individual ${ind} has ${datasetAttributes.size()} dataset attributes: ${datasetAttributes}"
        issuesFound++
    }
}

if (issuesFound == 0) {
    println "No qualities with multiple RAK_79... attributes found."
} else {
    println "Total issues found: ${issuesFound}"
}
