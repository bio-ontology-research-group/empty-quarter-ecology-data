@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='4.5.26')
import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.io.FileDocumentSource
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.profiles.OWL2ELProfile
import groovy.json.JsonOutput

// This tests the asserted tractable core, NOT the imports closure or taxonomy ABox.
def input = new File(args[0])
def output = new File(args[1])
def files = input.listFiles().findAll { it.name.endsWith('.owl') && it.name.startsWith('rubalkhali') }.sort { it.name }
def manager = OWLManager.createOWLOntologyManager()
def merged = manager.createOntology()
def loader = new OWLOntologyLoaderConfiguration().setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT)
def ignored = new TreeSet<String>()
files.each { file ->
    (file.text =~ /<owl:imports\s+rdf:resource="([^"]+)"/).each { match -> ignored.add(match[1]) }
}
ignored.each { loader = loader.addIgnoredImport(IRI.create(it)) }
def loaded = []
files.each { file ->
    def ontology = manager.loadOntologyFromOntologyDocument(new FileDocumentSource(file), loader)
    manager.addAxioms(merged, ontology.getAxioms())
    loaded.add([file: file.name, axioms: ontology.getAxiomCount()])
}
def report = new OWL2ELProfile().checkOntology(merged)
def violations = report.getViolations().collect { [type: it.class.simpleName, detail: it.toString()] }
def counts = violations.groupBy { it.type }.collectEntries { k,v -> [k,v.size()] }
output.text = JsonOutput.prettyPrint(JsonOutput.toJson([
    scope: 'Asserted tractable core modules only; imports deliberately not loaded; full taxonomy ABox excluded.',
    full_graph_profile_claim: false,
    imported_declaration_caveat: 'Undeclared-entity violations can reflect the excluded import declarations; structural unsupported axioms are reported separately by type.',
    modules: loaded, ignored_imports: ignored, merged_axioms: merged.getAxiomCount(),
    in_owl2_el_profile: report.isInProfile(), violation_counts: counts, violations: violations
])) + '\n'
println "Asserted-core OWL2EL profile: ${report.isInProfile()}, violations=${violations.size()}"
