@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='com.google.code.gson', module='gson', version='2.10.1')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.semanticweb.owlapi.formats.FunctionalSyntaxDocumentFormat
import com.google.gson.GsonBuilder
import groovy.util.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths

class MapToEcosystem {

    static void main(String[] args) {
        def cli = new CliBuilder(usage: 'groovy MapToEcosystem.groovy -ontology <path> -taxa <path> -outdir <path>')
        cli.ontology(args: 1, required: true, 'Path to final_ecosystem.owl')
        cli.taxa(args: 1, required: true, 'Path to unique_taxa.txt')
        cli.outdir(args: 1, required: true, 'Output directory')
        
        def options = cli.parse(args)
        if (!options) return

        new MapToEcosystem().run(options.ontology, options.taxa, options.outdir)
    }

    void run(String ontologyPath, String taxaPath, String outDir) {
        println "Initializing Manager..."
        def manager = OWLManager.createOWLOntologyManager()
        def df = manager.getOWLDataFactory()

        println "Loading Ecosystem Ontology: $ontologyPath..."
        def ont = manager.loadOntologyFromOntologyDocument(new File(ontologyPath))
        println "Ontology loaded. Axioms: ${ont.getAxiomCount()}"

        // 1. Build Index
        println "Indexing ontology..."
        Map<String, OWLClass> labelIndex = [:]
        Map<OWLClass, String> classToLabel = [:]
        
        ont.getClassesInSignature(true).each { cls ->
            String label = getLabel(ont, cls)
            if (label) {
                labelIndex[normalize(label)] = cls
                classToLabel[cls] = label
            }
            getSynonyms(ont, cls).each { syn ->
                labelIndex[normalize(syn)] = cls
            }
        }
        println "Index size: ${labelIndex.size()}"

        // 2. Process Taxa & Build Module Set
        println "Processing taxa..."
        List<String> uniqueTaxa = Files.readAllLines(Paths.get(taxaPath)).findAll { !it.trim().isEmpty() }
        
        Map<String, List<Map>> finalMapping = [:] 
        Set<OWLClass> moduleClasses = new HashSet<>()
        Map<String, OWLClass> createdRakClasses = [:] // key -> Class
        long rakCounter = 100000 
        
        // Define Ranks
        def rankNames = ["domain", "phylum", "class", "order", "family", "genus", "species"]
        def rankProp = df.getOWLAnnotationProperty(IRI.create("http://purl.obolibrary.org/obo/ncbitaxon#has_rank"))
        
        // Initialize Module Ontology immediately to add new axioms
        def modManager = OWLManager.createOWLOntologyManager()
        def modOnt = modManager.createOntology(IRI.create("https://rubalkhali.science/kb/ecosystem_module.owl"))

        uniqueTaxa.each { taxonStr ->
            def parts = taxonStr.split(";")
            List<Map> pathMapping = []
            OWLClass lastResolved = null
            String lastResolvedLabel = "Root"
            
            parts.eachWithIndex { part, i ->
                String cleaned = cleanName(part)
                String normName = normalize(cleaned)
                
                // Skip NA/Empty gaps in path mapping structure, 
                // but if we are creating new nodes, we might need to handle them?
                // Usually unique_taxa.txt has standard levels.
                // If it is "NA" or "unclassified", we treat it as a placeholder that inherits parent.
                // But for the Module, we need specific nodes if the downstream analysis uses them?
                // Usually taxonomy strings condense NAs. 
                // Let's stick to mapping VALID names to classes, and creating new classes for VALID names not found.
                
                if (normName == "na" || normName == "unclassified" || normName == "") {
                    // Inherit (don't create node)
                    // Store mapping as inherited
                    String effectiveId = lastResolved ? lastResolved.getIRI().toString() : null
                    pathMapping << [name: part, clean: cleaned, iri: effectiveId, rank: (i < 7 ? rankNames[i] : "level_$i")]
                } else {
                    OWLClass match = labelIndex[normName]
                    
                    // Binomial Fallback (Index 6 / Species)
                    if (!match && i == 6 && parts.length >= 6) {
                         String genus = cleanName(parts[5])
                         // Use current part as epithet
                         if (genus.toLowerCase() != "na" && !cleaned.contains(" ")) {
                             String binomial = "${genus} ${cleaned}"
                             match = labelIndex[normalize(binomial)]
                         }
                    }
                    
                    if (match) {
                        pathMapping << [name: part, clean: cleaned, iri: match.getIRI().toString(), rank: (i < 7 ? rankNames[i] : "level_$i")]
                        moduleClasses.add(match)
                        
                        // Safety Graft: Ensure this class is a subclass of the last resolved parent in the module
                        if (lastResolved && lastResolved != match) {
                             // Check if subclass relationship exists? 
                             // For the Module, we can just add it. It won't hurt if it's redundant.
                             // But we must check if we are creating a cycle or conflicting with ontology?
                             // Generally safe to assert the input path structure.
                             modManager.addAxiom(modOnt, df.getOWLSubClassOfAxiom(match, lastResolved))
                        }
                        
                        lastResolved = match
                        lastResolvedLabel = classToLabel[match] ?: cleaned
                    } else {
                        // Create RAK Class (Missing Node)
                        // Check if we already created it in this run
                        String rakKey = "${i}_${normName}_${lastResolved?.getIRI()?.toString()}" // Scoped by parent to allow homonyms?
                        // Or just global unique name?
                        // "CL500-29 marine group" might appear in different contexts? Unlikely.
                        // Let's use name + rank for key.
                        rakKey = "${normName}_${i}" 
                        
                        OWLClass newClass = createdRakClasses[rakKey]
                        
                        if (!newClass) {
                            newClass = df.getOWLClass(IRI.create("https://rubalkhali.science/kb/RAK_${rakCounter++}"))
                            createdRakClasses[rakKey] = newClass
                            
                            // Generate Smart Label
                            String newLabel = cleaned
                            if (i == 6 && !cleaned.contains(" ")) {
                                // Species epithet -> append to parent label
                                newLabel = "${lastResolvedLabel} ${cleaned}"
                            } else {
                                // General check: does it look like an epithet or code?
                                // If parent is Genus, and this has no space, implies epithet.
                                // If generic name "Unknown Family", etc.
                                // The user request: "name must include super-taxon"
                                // If cleanName is very short or generic?
                                // For now, the Species rule covers the user's specific "methylaliphatogenes" case.
                            }
                            
                            // Add axioms to Module Ontology directly
                            modManager.addAxiom(modOnt, df.getOWLDeclarationAxiom(newClass))
                            modManager.addAxiom(modOnt, df.getOWLAnnotationAssertionAxiom(newClass.getIRI(), df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(newLabel))))
                            
                            // Rank
                            String rankName = i < 7 ? rankNames[i] : "level_$i"
                            modManager.addAxiom(modOnt, df.getOWLAnnotationAssertionAxiom(newClass.getIRI(), df.getOWLAnnotation(rankProp, df.getOWLLiteral(rankName))))
                            
                            // Parent
                            if (lastResolved) {
                                modManager.addAxiom(modOnt, df.getOWLSubClassOfAxiom(newClass, lastResolved))
                            }
                        }
                        
                        pathMapping << [name: part, clean: cleaned, iri: newClass.getIRI().toString(), rank: (i < 7 ? rankNames[i] : "level_$i")]
                        moduleClasses.add(newClass) // It's in the module
                        lastResolved = newClass
                        lastResolvedLabel = getLabel(modOnt, newClass) // Get the label we just assigned
                    }
                }
            }
            finalMapping[taxonStr] = pathMapping
        }

        // 3. Expand Module (Ancestors)
        println "Extracting ancestors for ${moduleClasses.size()} classes..."
        Set<OWLClass> visited = new HashSet<>(moduleClasses)
        Queue<OWLClass> queue = new ArrayDeque<>(moduleClasses)
        
        while (!queue.isEmpty()) {
            OWLClass cls = queue.poll()
            
            // Skip RAK classes created in this session (we already added their parents)
            if (createdRakClasses.values().contains(cls)) continue
            
            EntitySearcher.getSuperClasses(cls, ont).each { ce ->
                if (!ce.isAnonymous()) {
                    OWLClass parent = ce.asOWLClass()
                    if (!visited.contains(parent)) {
                        visited.add(parent)
                        moduleClasses.add(parent)
                        queue.add(parent)
                    }
                }
            }
        }
        println "Total Module size: ${moduleClasses.size()} classes."

        // 4. Copy Axioms for Existing Classes
        println "Copying axioms to module..."
        moduleClasses.each { cls ->
            // Skip newly created ones (axioms already added)
            if (createdRakClasses.values().contains(cls)) return
            
            modManager.addAxiom(modOnt, df.getOWLDeclarationAxiom(cls))
            
            EntitySearcher.getAnnotationAssertionAxioms(cls, ont).each { ax ->
                modManager.addAxiom(modOnt, ax)
            }
            
            ont.getSubClassAxiomsForSubClass(cls).each { ax ->
                if (!ax.getSuperClass().isAnonymous()) {
                    OWLClass parent = ax.getSuperClass().asOWLClass()
                    if (moduleClasses.contains(parent)) {
                        modManager.addAxiom(modOnt, ax)
                    }
                }
            }
        }

        // 5. Save
        Files.createDirectories(Paths.get(outDir))
        
        String modPath = "$outDir/ecosystem_module.owl"
        println "Saving module to $modPath..."
        modManager.saveOntology(modOnt, new FunctionalSyntaxDocumentFormat(), IRI.create(new File(modPath).toURI()))
        
        String jsonPath = "$outDir/mapped_taxonomy.json"
        println "Saving mapping to $jsonPath..."
        def gson = new GsonBuilder().setPrettyPrinting().create()
        Files.newBufferedWriter(Paths.get(jsonPath)).withCloseable { writer ->
            writer.write(gson.toJson(finalMapping))
        }
        
        println "Done."
    }
    
    // --- Helpers ---

    String getLabel(OWLOntology ont, OWLClass cls) {
        String label = null
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                label = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        return label
    }
    
    Set<String> getSynonyms(OWLOntology ont, OWLClass cls) {
        Set<String> syns = new HashSet<>()
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            String prop = ann.getProperty().getIRI().toString()
            if ((prop.contains("Synonym") || prop.contains("altLabel")) && ann.getValue().isLiteral()) {
                syns.add(ann.getValue().asLiteral().get().getLiteral())
            }
        }
        return syns
    }

    String normalize(String label) {
        if (!label) return ""
        String s = label.trim().toLowerCase()
        s = s.replaceAll(/^[dpcofgs]__/, "")
        s = s.replaceAll(/_[a-z0-9]+$/, "") 
        s = s.replaceAll(/^candidatus\s+/, "")
        s = s.replaceAll(/^ca\.\s+/, "")
        return s.trim()
    }
    
    String cleanName(String part) {
        return part.replaceAll(/^[kpcofgs]__/, "")
    }
}