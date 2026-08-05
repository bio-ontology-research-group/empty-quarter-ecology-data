@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='4.5.26')
@Grab(group='org.semanticweb.elk', module='elk-owlapi', version='0.4.3')
@Grab(group='org.slf4j', module='slf4j-simple', version='1.7.36')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.elk.owlapi.ElkReasonerFactory
import org.semanticweb.owlapi.reasoner.OWLReasonerFactory
import org.semanticweb.owlapi.reasoner.SimpleConfiguration
import org.semanticweb.owlapi.reasoner.InferenceType

// Benchmark wrapper for ELK over the merged Empty Quarter ontology.
// Loads every .owl/.ttl in data/processed/ontology (skipping the
// pre-materialized graph), runs an ELK consistency check, then
// computes the class hierarchy. Reports wall-clock time and the
// number of axioms loaded.

def t = System.currentTimeMillis()
def stamp = { label ->
    def now = System.currentTimeMillis()
    println String.format("[BENCH] %-30s %.3f s", label, (now - t) / 1000.0)
    t = now
}

println "[BENCH] Java max heap: ${Runtime.runtime.maxMemory() / (1024*1024)} MB"
def manager = OWLManager.createOWLOntologyManager()
def merger = OWLManager.createOWLOntologyManager()
def mergedOntology = merger.createOntology()
stamp "init managers"

// Accept an optional --with-inferred flag.
// When set, also load rubalkhali_inferred.nt from the ontology dir.
boolean withInferred = false
for (String a : args) {
    if (a == '--with-inferred') withInferred = true
}
println "[BENCH] withInferred: ${withInferred}"

def dir = new File("data/processed/ontology")
println "[DEBUG] listing dir: ${dir.absolutePath} (exists=${dir.exists()}, isDir=${dir.isDirectory()})"
dir.eachFile { f -> println "[DEBUG] file: ${f.name}" }
int loaded = 0
dir.eachFile { file ->
    boolean matchOwl = file.name.endsWith(".owl")
    boolean matchTtl = file.name.endsWith(".ttl")
    boolean matchNt = withInferred && file.name.endsWith(".nt")
    if (!(matchOwl || matchTtl || matchNt)) {
        println "[DEBUG] SKIP (ext): ${file.name}  owl=${matchOwl} ttl=${matchTtl} nt=${matchNt}"
        return
    }
    if (file.name.contains("materialized")) {
        println "[DEBUG] SKIP (materialized): ${file.name}"
        return
    }
    if (file.name.contains("inferred") && !withInferred) {
        println "[DEBUG] SKIP (inferred, flag not set): ${file.name}"
        return
    }
    println "[DEBUG] LOADING: ${file.name}"
    try {
        def ont = manager.loadOntologyFromOntologyDocument(file)
        merger.addAxioms(mergedOntology, ont.getAxioms())
        loaded++
        println "  loaded ${file.name} (${ont.getAxiomCount()} axioms)"
    } catch (Exception e) {
        println "  ERROR loading ${file.name}: ${e.message}"
    }
}
println "[BENCH] modules loaded: ${loaded}"
println "[BENCH] total axioms:   ${mergedOntology.getAxiomCount()}"
println "[BENCH] logical axioms: ${mergedOntology.getLogicalAxiomCount()}"
println "[BENCH] classes:        ${mergedOntology.getClassesInSignature().size()}"
println "[BENCH] individuals:    ${mergedOntology.getIndividualsInSignature().size()}"
stamp "load all modules"

OWLReasonerFactory factory = new ElkReasonerFactory()
def reasoner = factory.createReasoner(mergedOntology, new SimpleConfiguration())
stamp "instantiate ELK"

boolean consistent = reasoner.isConsistent()
stamp "isConsistent (${consistent})"

reasoner.precomputeInferences(InferenceType.CLASS_HIERARCHY)
stamp "precompute CLASS_HIERARCHY"

def unsat = reasoner.getUnsatisfiableClasses().getEntitiesMinusBottom().size()
println "[BENCH] unsatisfiable classes: ${unsat}"

reasoner.dispose()
println "[BENCH] done"
