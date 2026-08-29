@Grab(group='org.apache.jena', module='jena-arq', version='4.10.0')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.9')

import org.apache.jena.riot.RDFDataMgr
import org.apache.jena.graph.Graph
import org.apache.jena.graph.Node
import org.apache.jena.graph.NodeFactory
import org.apache.jena.query.*
import org.apache.jena.rdf.model.ModelFactory
import java.io.File

/**
 * Validates that every RAK_ entity has exactly one rdfs:label.
 *
 * Strategy:
 *   1. Merge all generated *.owl / *.ttl files under data/processed/semantics/ontology/
 *      (skipping >100MB files to avoid OOM).
 *   2. Pass 1: SPARQL aggregate over the merged graph — finds any RAK IRI
 *      with multiple distinct rdfs:label values. Fast, precise, in-process.
 *   3. Pass 2: ShEx schema validation against label_uniqueness.shex —
 *      run out-of-process via scripts/validation/shexvalidate.sh because
 *      Groovy 2.4's ASM 5 can't generate call sites for Jena 4.10's
 *      modern bytecode (it throws VerifyError on ShexValidator.get()).
 *
 * Exit code 1 if any entity violates label uniqueness in either pass.
 *
 * Usage:
 *   groovy scripts/validation/validate_labels.groovy            # scan all generated files
 *   groovy scripts/validation/validate_labels.groovy <file>     # validate a single file
 */

def RAK = "https://rubalkhali.science/kb/"
def RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

def shexFile = new File("data/processed/semantics/shex/label_uniqueness.shex")
if (!shexFile.exists()) {
    println "ERROR: ShEx schema not found at ${shexFile}"
    System.exit(1)
}

// ---- Load graph(s) ----
def graph = org.apache.jena.sparql.graph.GraphFactory.createDefaultGraph()
def loadedFiles = []
def loadedPaths = []
def defaultExclude = [
    // Retired pre-audit taxonomy modules conflict intentionally with the
    // generated canonical ecosystem module and must never be merged into the
    // same validation graph.
    "rubalkhali_taxonomy_rak.owl",
    "ncbitaxon_module.owl",
    "ncbitaxon_module.ttl",
    // The multi-gigabyte generated taxonomy ABox has a separate streaming
    // validator; the tiny .owl file is only a historical stub.
    "rubalkhali_taxonomy_abox.owl",
    "rubalkhali_taxonomy_abox.ttl",
] as Set

def loadInto = { File f ->
    if (!f.exists()) return
    if (f.length() > 100L * 1024 * 1024) {
        println "  skip ${f.name} (${(f.length() / 1048576) as long} MB — too large)"
        return
    }
    try {
        def g = RDFDataMgr.loadGraph(f.absolutePath)
        org.apache.jena.util.iterator.ExtendedIterator it = g.find()
        while (it.hasNext()) graph.add(it.next())
        loadedFiles << f.name
        loadedPaths << f.absolutePath
    } catch (Exception e) {
        println "  WARN: could not load ${f.name}: ${e.message}"
    }
}

if (args.length > 0) {
    loadInto(new File(args[0]))
} else {
    def ontDir = new File("data/processed/semantics/ontology")
    if (ontDir.exists()) {
        def candidates = ontDir.listFiles().toList().findAll { f ->
            def n = f.name
            (n.endsWith(".owl") || n.endsWith(".ttl")) &&
                !n.contains("materialized") &&
                !defaultExclude.contains(n)
        }.sort { a, b ->
            // Prefer RDF/XML when a module is supplied in both RDF/XML and
            // Turtle with the same stem.
            def aStem = a.name.replaceFirst(/\.(owl|ttl)$/, "")
            def bStem = b.name.replaceFirst(/\.(owl|ttl)$/, "")
            if (aStem == bStem) {
                if (a.name.endsWith(".owl")) return -1
                if (b.name.endsWith(".owl")) return 1
            }
            return a.name <=> b.name
        }
        def loadedStems = new HashSet<String>()
        candidates.each { f ->
            def stem = f.name.replaceFirst(/\.(owl|ttl)$/, "")
            if (loadedStems.add(stem)) {
                loadInto(f)
            } else {
                println "  skip ${f.name} (sibling serialization already loaded)"
            }
        }
    }
}

println "Loaded ${loadedFiles.size()} files: ${loadedFiles.join(', ')}"
println "Total triples in merged graph: ${graph.size()}"

// ---- Pass 1: SPARQL aggregate (fast, precise) ----
println "\n[Pass 1] Counting labels per RAK_ entity via SPARQL..."
def model = ModelFactory.createModelForGraph(graph)
def query = QueryFactory.create("""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?entity (COUNT(DISTINCT ?label) AS ?n) (GROUP_CONCAT(DISTINCT STR(?label); separator=" || ") AS ?labels)
    WHERE {
      ?entity rdfs:label ?label .
      FILTER(STRSTARTS(STR(?entity), "${RAK}RAK_"))
    }
    GROUP BY ?entity
    HAVING (COUNT(DISTINCT ?label) > 1)
    ORDER BY DESC(?n) ?entity
""")
def violations = []
QueryExecution qexec = QueryExecutionFactory.create(query, model)
try {
    qexec.execSelect().each { sol ->
        violations << [
            iri: sol.getResource("entity").getURI(),
            n: sol.getLiteral("n").getInt(),
            labels: sol.getLiteral("labels").getString()
        ]
    }
} finally {
    qexec.close()
}

if (violations) {
    println "\n❌ FAILED: Found ${violations.size()} RAK entit${violations.size() == 1 ? 'y' : 'ies'} with multiple distinct labels:\n"
    violations.each { v ->
        println "  ${v.iri}"
        println "    ${v.n} labels: ${v.labels}"
    }
} else {
    println "  ✅ No multi-label violations found by SPARQL pass."
}

// ---- Pass 2: ShEx schema validation (out-of-process; see header) ----
println "\n[Pass 2] ShEx validation against label_uniqueness.shex..."
def shapeUri = shexFile.toURI().toString() + "#RAKLabeledEntityShape"

// Collect every RAK_ subject that has at least one rdfs:label
def labelNode = NodeFactory.createURI(RDFS_LABEL)
def rakSubjects = new HashSet<String>()
def it = graph.find(Node.ANY, labelNode, Node.ANY)
while (it.hasNext()) {
    def t = it.next()
    if (t.getSubject().isURI() && t.getSubject().getURI().startsWith("${RAK}RAK_")) {
        rakSubjects.add(t.getSubject().getURI())
    }
}
println "  ${rakSubjects.size()} RAK_ subjects carry rdfs:label"

def shexFailed = false
if (rakSubjects.isEmpty()) {
    println "  ⚠️  No subjects to validate — ShEx pass skipped."
} else {
    File mapFile = File.createTempFile("label_shape_map", ".shexmap")
    mapFile.text = rakSubjects.collect { "<${it}>@<${shapeUri}>" }.join(",\n")

    File listFile = File.createTempFile("label_inputs", ".list")
    listFile.text = loadedPaths.join("\n")

    try {
        def shim = new File("scripts/validation/shexvalidate.sh").absolutePath
        new File(shim).setExecutable(true)
        def proc = new ProcessBuilder(
            shim, listFile.absolutePath, shexFile.absolutePath, mapFile.absolutePath, "--list"
        ).redirectErrorStream(true).start()
        def stdout = proc.inputStream.text
        int rc = proc.waitFor()
        if (rc == 0 && stdout.contains("CONFORM")) {
            println "  ✅ All ${rakSubjects.size()} subjects conform to RAKLabeledEntityShape."
        } else {
            shexFailed = true
            println "  ❌ ShEx report (non-conformant or error):"
            stdout.eachLine { println "    " + it }
        }
    } finally {
        mapFile.delete()
        listFile.delete()
    }
}

if (violations || shexFailed) {
    System.exit(1)
}
println "\n✅ Label uniqueness validation PASSED."
