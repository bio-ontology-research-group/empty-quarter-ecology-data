@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import java.io.File

def manager = OWLManager.createOWLOntologyManager()
def dir = new File("data/processed/ontology")
def base = "https://rubalkhali.science/kb/"

dir.listFiles().each { file ->
    if (!file.name.endsWith(".owl")) return
    println "Checking ${file.name}..."
    try {
        def config = new OWLOntologyLoaderConfiguration().setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT)
        def ontology = manager.loadOntologyFromOntologyDocument(new org.semanticweb.owlapi.io.FileDocumentSource(file), config)
        
        // Allowed RAK ID forms (everything past `RAK_`):
        //   <digit><6 digits>           — TBox classes / properties / standard 7-char individuals (length 11)
        //   <letter><6 digits>          — letter-prefix individuals: P, A, D, E, F, L, R, T, X (length 11)
        //   FN<6 digits>                — measuring-function individuals (length 12)
        //   V<8 digits> / Q<8 digits>   — taxonomy abundance values / qualities (length 13)
        //   UNK_<12 hex>                — md5-hashed Unknown-taxon classes (length 20)
        ontology.getSignature().each { entity ->
            def iri = entity.getIRI().toString()
            if (iri.startsWith(base)) {
                def id = iri.substring(base.length())
                if (!id.startsWith("RAK_")) return
                def body = id.substring(4)
                def ok =
                    (body ==~ /[0-9A-Z]\d{6}/) ||      // 7-char digit/letter + 6 digits
                    (body ==~ /FN\d{6}/) ||             // FN + 6 digits
                    (body ==~ /[VQ]\d{8}/) ||           // V/Q + 8 digits (taxonomy)
                    (body ==~ /UNK_[0-9a-f]{12}/)       // Unknown-taxon md5 prefix
                if (!ok) {
                    println "  Non-standard ID: ${id} (length ${id.length()}) in ${file.name}"
                }
            }
        }
        manager.removeOntology(ontology)
    } catch (e) {
        println "  Error loading ${file.name}: ${e.message}"
    }
}
