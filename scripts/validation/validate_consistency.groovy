@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='4.5.26')
@Grab(group='org.semanticweb.elk', module='elk-owlapi', version='0.4.3')
@Grab(group='org.slf4j', module='slf4j-simple', version='1.7.36')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.io.FileDocumentSource
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.util.AutoIRIMapper
import org.semanticweb.owlapi.util.SimpleIRIMapper
import org.semanticweb.elk.owlapi.ElkReasonerFactory
import org.semanticweb.owlapi.reasoner.OWLReasonerFactory
import org.semanticweb.owlapi.reasoner.ConsoleProgressMonitor
import org.semanticweb.owlapi.reasoner.SimpleConfiguration
import org.semanticweb.owlapi.reasoner.InferenceType
import java.io.File

/**
 * Validates logical consistency of one or more OWL files.
 *
 * Usage:
 *   groovy scripts/validation/validate_consistency.groovy             # lite (default; deployment gate)
 *   groovy scripts/validation/validate_consistency.groovy <file>      # validate a single file
 *   FULL=1 groovy scripts/validation/validate_consistency.groovy      # full reasoning (slow)
 *
 * Two modes:
 *   - LITE (default, ~minutes):
 *       Loads the project's own RDF files from `data/processed/semantics/ontology/`
 *       only — skipping heavyweight OBO bundles (rubalkhali_taxonomy_rak which
 *       imports 1.6 GB of NCBITaxon, ncbitaxon_module, etc.). The ELK reasoner
 *       checks satisfiability, but we DON'T precompute the full class
 *       hierarchy. This is fast enough to gate a deployment.
 *
 *   - FULL (FULL=1, ~hours):
 *       Loads everything in `data/processed/semantics/ontology/` AND
 *       `data/ontologies/`, then computes consistency + full class hierarchy.
 *       Useful for periodic deep checks; not meant for the gate.
 *
 * Two precautions over the naive load:
 *
 *   1. Local ontology cache wired into the OWLOntologyManager via
 *      AutoIRIMapper + explicit pins, so imports such as
 *      `http://purl.obolibrary.org/obo/uo/releases/2023-05-25/uo.owl`
 *      (whose upstream redirect 404s) resolve from `data/ontologies/`.
 *
 *   2. De-duplicate ontology IRIs.  `ecosystem_module.owl` and
 *      `ecosystem_module.ttl` both declare the same OntologyIRI;
 *      loading both crashes OWLAPI. We track loaded IRIs and skip duplicates,
 *      preferring .owl over .ttl.
 */

def isFull = System.getenv("FULL") == "1"
println "Mode: ${isFull ? 'FULL (deep, slow)' : 'LITE (deployment gate, fast)'}"

println "Initializing OWL Manager..."
def manager = OWLManager.createOWLOntologyManager()

// (1) Local ontology cache → IRI mappers
def cacheDir = new File("data/ontologies")
def generatedDir = new File("data/processed/semantics/ontology")
if (generatedDir.exists()) {
    println "Wiring generated-module cache: ${generatedDir.absolutePath}"
    manager.getIRIMappers().add(new AutoIRIMapper(generatedDir, true))
}
if (cacheDir.exists()) {
    println "Wiring local ontology cache: ${cacheDir.absolutePath}"
    manager.getIRIMappers().add(new AutoIRIMapper(cacheDir, true))

    def pin = { String url, String localFile ->
        def f = new File(cacheDir, localFile)
        if (f.exists()) {
            manager.getIRIMappers().add(
                new SimpleIRIMapper(IRI.create(url), IRI.create(f))
            )
        }
    }
    pin("http://purl.obolibrary.org/obo/uo/releases/2023-05-25/uo.owl", "uo.owl")
    pin("http://purl.obolibrary.org/obo/uo.owl", "uo.owl")
    pin("http://purl.obolibrary.org/obo/envo/releases/2025-10-20/envo.owl", "envo.owl")
    pin("http://purl.obolibrary.org/obo/envo.owl", "envo.owl")
    pin("http://purl.obolibrary.org/obo/pato/releases/2025-05-14/pato.owl", "pato.owl")
    pin("http://purl.obolibrary.org/obo/pato.owl", "pato.owl")
    pin("http://purl.obolibrary.org/obo/ro.owl", "ro.owl")
    pin("http://purl.obolibrary.org/obo/sio.owl", "sio.owl")
    pin("http://semanticscience.org/ontology/sio/v1.59/sio-release.owl", "sio.owl")
    pin("http://purl.obolibrary.org/obo/chebi.owl", "chebi.owl")
    pin("http://purl.obolibrary.org/obo/ncbitaxon.owl", "ncbitaxon.owl")
}

// In LITE mode, exclude files that pull in the very large reference
// ontologies (NCBITaxon, GTDB, CHEBI). These are upstream-validated and
// reasoning over them dominates wall-time.
def liteExclude = [
    "rubalkhali_taxonomy_rak.owl",
    "rubalkhali_taxonomy_abox.owl",
    "rubalkhali_taxonomy_abox.ttl",
    "rubalkhali_taxonomy_abox_full.owl",  // 3.7 GB materialised taxonomy — OOMs LITE
    "ncbitaxon_module.owl",
    "ncbitaxon_module.ttl",
    "ecosystem_module.owl",  // the .ttl variant covers the same content
] as Set

// LITE is a fast deployment gate. Loading a multi-GB ontology blows the JVM
// heap, and the OOM surfaces as java.lang.OutOfMemoryError — an Error, not an
// Exception, so the per-file try/catch below does NOT catch it and the whole
// run dies non-zero ("Consistency check execution error" in the deploy log).
// Guard by size so any future large file is skipped automatically, not just by
// name.
long LITE_MAX_BYTES = 1_000_000_000L  // 1 GB

def merger = OWLManager.createOWLOntologyManager()
def mergedOntology = merger.createOntology()

def targetFile = args.length > 0 ? args[0] : null

println "Loading ontologies..."
int loadedCount = 0
def loadedIRIs = new HashSet<String>()
def loadErrors = []
def loaderConfig = new OWLOntologyLoaderConfiguration()
    .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT)

def loadInto = { File file ->
    if (!file.exists()) return
    if (!isFull && liteExclude.contains(file.name)) {
        println "  skip ${file.name} (LITE mode — large or covered by sibling)"
        return
    }
    if (!isFull && file.length() > LITE_MAX_BYTES) {
        println "  skip ${file.name} (LITE mode — ${String.format('%.2f', file.length() / 1e9)} GB exceeds ${LITE_MAX_BYTES / 1_000_000_000L} GB cap)"
        return
    }
    try {
        println "  Loading ${file.name}..."
        def ont = manager.loadOntologyFromOntologyDocument(
            new FileDocumentSource(file), loaderConfig
        )
        def id = ont.getOntologyID()
        def iri = id.getOntologyIRI().isPresent()
            ? id.getOntologyIRI().get().toString()
            : "anonymous:" + file.name
        if (loadedIRIs.contains(iri)) {
            println "    skip (already loaded as another file)"
            manager.removeOntology(ont)
            return
        }
        loadedIRIs.add(iri)
        merger.addAxioms(mergedOntology, ont.getAxioms())
        loadedCount++
    } catch (Exception e) {
        println "  ERROR loading ${file.name}: ${e.message}"
        loadErrors << "${file.name}: ${e.message}"
    }
}

if (targetFile) {
    def file = new File(targetFile)
    if (file.exists()) {
        loadInto(file)
    } else {
        println "  ERROR: Target file ${targetFile} not found."
        System.exit(1)
    }
} else {
    // LITE: only the project's own outputs. FULL: also the cached upstream OBO bundles.
    def dirs = isFull
        ? ["data/processed/semantics/ontology", "data/ontologies"]
        : ["data/processed/semantics/ontology"]

    for (String dirPath : dirs) {
        def dir = new File(dirPath)
        if (dir.exists() && dir.isDirectory()) {
            def files = dir.listFiles().toList().findAll { f ->
                (f.name.endsWith(".owl") || f.name.endsWith(".ttl")) &&
                !f.name.contains("materialized")
            }
            // .owl preferred over .ttl when both share a stem (same OntologyIRI).
            files.sort { a, b ->
                if (a.name.endsWith(".owl") && !b.name.endsWith(".owl")) return -1
                if (b.name.endsWith(".owl") && !a.name.endsWith(".owl")) return 1
                return a.name <=> b.name
            }
            files.each { loadInto(it) }
        }
    }
}

if (loadedCount == 0) {
    println "No ontologies loaded. Exiting."
    System.exit(1)
}
if (!loadErrors.isEmpty()) {
    println "Ontology loading failed for ${loadErrors.size()} file(s):"
    loadErrors.each { println "  ${it}" }
    System.exit(1)
}

println "Total axioms loaded: ${mergedOntology.getAxiomCount()}"
println "Distinct OntologyIRIs: ${loadedIRIs.size()}"

println "Initializing ELK Reasoner..."
OWLReasonerFactory reasonerFactory = new ElkReasonerFactory()
def progressMonitor = new ConsoleProgressMonitor()
def config = new SimpleConfiguration(progressMonitor)
def reasoner = reasonerFactory.createReasoner(mergedOntology, config)

println "Checking consistency..."
boolean consistent = reasoner.isConsistent()

if (consistent) {
    println "\n✅ Ontology is CONSISTENT."
    if (isFull) {
        println "Computing class hierarchy (FULL mode)..."
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
        println "(skipping class-hierarchy precompute in LITE mode — set FULL=1 for the deep check)"
    }
} else {
    println "\n❌ Ontology is INCONSISTENT!"
    System.exit(1)
}

reasoner.dispose()
println "Done."
