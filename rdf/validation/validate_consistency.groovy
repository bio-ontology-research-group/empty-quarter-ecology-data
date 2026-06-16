@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='4.5.26')
@Grab(group='org.semanticweb.elk', module='elk-owlapi', version='0.4.3')
@Grab(group='org.slf4j', module='slf4j-simple', version='1.7.36')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.elk.owlapi.ElkReasonerFactory
import org.semanticweb.owlapi.reasoner.OWLReasonerFactory
import org.semanticweb.owlapi.reasoner.ConsoleProgressMonitor
import org.semanticweb.owlapi.reasoner.SimpleConfiguration
import org.semanticweb.owlapi.reasoner.InferenceType
import java.io.File

/**
 * Validates logical consistency of one or more OWL files.
 * Usage: groovy scripts/validate_consistency.groovy [file_to_validate]
 * If no file is provided, it scans data/processed/ontology and data/ontologies.
 */

println "Initializing OWL Manager..."
def manager = OWLManager.createOWLOntologyManager()
def merger = OWLManager.createOWLOntologyManager()
def mergedOntology = merger.createOntology()

def targetFile = args.length > 0 ? args[0] : null

println "Loading ontologies..."
int loadedCount = 0

if (targetFile) {
    def file = new File(targetFile)
    if (file.exists()) {
        println "  Loading ${file.name}..."
        def ont = manager.loadOntologyFromOntologyDocument(file)
        merger.addAxioms(mergedOntology, ont.getAxioms())
        loadedCount++
    } else {
        println "  ERROR: Target file ${targetFile} not found."
        System.exit(1)
    }
} else {
    // Default scan
    def dirs = ["data/processed/ontology", "data/ontologies"]
    for (String dirPath : dirs) {
        def dir = new File(dirPath)
        if (dir.exists() && dir.isDirectory()) {
            dir.eachFile { file ->
                if (file.name.endsWith(".owl") || file.name.endsWith(".ttl")) {
                    if (file.name.contains("materialized")) return // skip large materialized file in default scan
                    try {
                        println "  Loading ${file.name}..."
                        def ont = manager.loadOntologyFromOntologyDocument(file)
                        merger.addAxioms(mergedOntology, ont.getAxioms())
                        loadedCount++
                    } catch (Exception e) {
                        println "  ERROR loading ${file.name}: ${e.message}"
                    }
                }
            }
        }
    }
}

if (loadedCount == 0) {
    println "No ontologies loaded. Exiting."
    System.exit(1)
}

println "Total axioms loaded: ${mergedOntology.getAxiomCount()}"

// Configure ELK Reasoner
println "Initializing ELK Reasoner..."
OWLReasonerFactory reasonerFactory = new ElkReasonerFactory()
def progressMonitor = new ConsoleProgressMonitor()
def config = new SimpleConfiguration(progressMonitor)
def reasoner = reasonerFactory.createReasoner(mergedOntology, config)

// Validate Consistency
println "Checking consistency..."
boolean consistent = reasoner.isConsistent()

if (consistent) {
    println "\n✅ Ontology is CONSISTENT."
    println "Computing class hierarchy..."
    reasoner.precomputeInferences(InferenceType.CLASS_HIERARCHY)
    
    def unsatisfiable = reasoner.getUnsatisfiableClasses()
    if (unsatisfiable.getEntitiesMinusBottom().size() > 0) {
         println "⚠️  WARNING: Found ${unsatisfiable.getEntitiesMinusBottom().size()} UNSATISFIABLE classes:"
         unsatisfiable.getEntitiesMinusBottom().each { cls ->
             println "    - ${cls.getIRI().getShortForm()}"
         }
    } else {
        println "✅ No unsatisfiable classes found."
    }
} else {
    println "\n❌ Ontology is INCONSISTENT!"
    System.exit(1)
}

reasoner.dispose()
println "Done."