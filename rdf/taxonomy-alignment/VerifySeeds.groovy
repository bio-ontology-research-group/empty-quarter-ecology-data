@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.slf4j', module='slf4j-simple', version='2.0.7')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')
@Grab(group='commons-cli', module='commons-cli', version='1.5.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVParser
import org.apache.commons.csv.CSVPrinter
import groovy.cli.commons.CliBuilder
import java.nio.file.Files
import java.nio.file.Paths

class VerifySeeds {

    // known rank properties
    static final List<String> RANK_PROPS = [
        "http://purl.obolibrary.org/obo/ncbitaxon#has_rank",
        "http://gtdb.ecogenomic.org/taxonomy/rank", 
        "http://www.geneontology.org/formats/oboInOwl#has_rank"
    ]
    
    // Explicit Rank mapping for NCBI subclass check
    static final Map<String, String> NCBI_RANK_CLASSES = [
        "http://purl.obolibrary.org/obo/NCBITaxon_species": "species",
        "http://purl.obolibrary.org/obo/NCBITaxon_genus": "genus",
        "http://purl.obolibrary.org/obo/NCBITaxon_family": "family",
        "http://purl.obolibrary.org/obo/NCBITaxon_order": "order",
        "http://purl.obolibrary.org/obo/NCBITaxon_class": "class",
        "http://purl.obolibrary.org/obo/NCBITaxon_phylum": "phylum",
        "http://purl.obolibrary.org/obo/NCBITaxon_superkingdom": "domain" // normalize to domain
    ]

    static void main(String[] args) {
        def cli = new CliBuilder(usage: 'groovy VerifySeeds.groovy -source <path> -target <path> -seeds <path>')
        cli.source(args: 1, required: true, 'Path to source ontology')
        cli.target(args: 1, required: true, 'Path to target ontology')
        cli.seeds(args: 1, required: true, 'Path to lexical_seed.csv')
        
        def options = cli.parse(args)
        if (!options) return

        new VerifySeeds().run(options.source, options.target, options.seeds)
    }

    void run(String sourcePath, String targetPath, String seedsPath) {
        println "Loading ontologies..."
        def manager = OWLManager.createOWLOntologyManager()
        def sourceOnt = manager.loadOntologyFromOntologyDocument(new File(sourcePath))
        def targetOnt = manager.loadOntologyFromOntologyDocument(new File(targetPath))
        
        println "Loading seeds from $seedsPath..."
        List<Map<String, String>> seeds = []
        Set<String> seedPairs = new HashSet<>()
        
        Files.newBufferedReader(Paths.get(seedsPath)).withCloseable { reader ->
            CSVParser parser = new CSVParser(reader, CSVFormat.DEFAULT.withFirstRecordAsHeader())
            parser.each { record ->
                def row = record.toMap()
                seeds << row
                seedPairs.add(key(row.source_iri, row.target_iri))
            }
        }
        println "Loaded ${seeds.size()} seeds."

        println "Verifying seeds..."
        def verified = []
        def conflict = []
        def rankMismatches = []
        
        int strongCount = 0
        int weakCount = 0
        int rankMismatchCount = 0
        int rankShiftCount = 0

        seeds.eachWithIndex { seed, index ->
            if (index % 1000 == 0) print "."
            
            def sIRI = IRI.create(seed.source_iri)
            def tIRI = IRI.create(seed.target_iri)
            
            // 1. Rank Check
            String sRank = getRank(sourceOnt, sIRI, true) // isSource=true
            String tRank = getRank(targetOnt, tIRI, false)
            
            boolean ranksMatch = true
            if (sRank && tRank) {
                 if (normalizeRank(sRank) != normalizeRank(tRank)) {
                     ranksMatch = false
                 }
            }
            
            // 2. Topology Check
            boolean parentMatch = false
            
            def sParents = getParents(sourceOnt, sIRI)
            def tParents = getParents(targetOnt, tIRI)

            if (sParents.isEmpty() && tParents.isEmpty()) {
                parentMatch = true
            } else {
                // Check if any parent pair matches by Name or is a known Seed
                sParents.each { sp ->
                    tParents.each { tp ->
                        // Check if this pair is a seed
                        if (seedPairs.contains(key(sp.toString(), tp.toString()))) {
                            parentMatch = true
                        }
                        // Check if names match (normalized)
                        else {
                            String spName = normalize(getLabel(sourceOnt, sp))
                            String tpName = normalize(getLabel(targetOnt, tp))
                            if (spName && tpName && spName == tpName) {
                                parentMatch = true
                            }
                        }
                    }
                }
            }

            // Classification Logic
            seed.s_rank = sRank
            seed.t_rank = tRank

            if (ranksMatch && parentMatch) {
                strongCount++
                seed.status = "STRONG_ANCHOR"
                verified << seed
            } else if (!ranksMatch && parentMatch) {
                // Rank Shift (Parents match, ranks differ)
                rankShiftCount++
                seed.status = "RANK_SHIFT"
                verified << seed // Treat as verified for now
            } else if (ranksMatch && !parentMatch) {
                // Weak Anchor (Ranks match, Parents differ)
                weakCount++
                seed.status = "WEAK_ANCHOR"
                conflict << seed
            } else {
                // Rank Mismatch (Ranks differ, Parents differ) - likely wrong match
                rankMismatchCount++
                seed.status = "RANK_MISMATCH"
                rankMismatches << seed
            }
        }
        println ""

        // Stats
        println "\n=== Verification Statistics ==="
        println "Total Seeds: ${seeds.size()}"
        println "Strong Anchors (Match Rank+Parent): $strongCount"
        println "Rank Shifts (Match Parent): $rankShiftCount"
        println "Weak Anchors (Match Rank, Diff Parent): $weakCount"
        println "Rank Mismatches (Diff Rank, Diff Parent): $rankMismatchCount"

        // Write Outputs
        writeCsv("verified_anchors.csv", verified, ["source_iri", "target_iri", "match_string", "match_type", "status", "s_rank", "t_rank"])
        writeCsv("conflict_seeds.csv", conflict, ["source_iri", "target_iri", "match_string", "match_type", "status", "s_rank", "t_rank"])
        writeCsv("rank_mismatches.csv", rankMismatches, ["source_iri", "target_iri", "match_string", "match_type", "status", "s_rank", "t_rank"])
    }
    
    String key(String s, String t) {
        return "${s}|${t}"
    }

    String getRank(OWLOntology ont, IRI iri, boolean isSource) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        String rank = null
        
        // Check 1: Explicit Annotation
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            def propStr = ann.getProperty().getIRI().toString()
            if (isRankProperty(propStr) && ann.getValue().isLiteral()) {
                rank = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        if (rank) return rank

        // Check 2: GTDB Prefix (if target/GTDB or simply if matches pattern)
        if (!isSource || rank == null) {
            String label = getLabel(ont, iri)
            if (label) {
                if (label.startsWith("d__")) return "domain"
                if (label.startsWith("p__")) return "phylum"
                if (label.startsWith("c__")) return "class"
                if (label.startsWith("o__")) return "order"
                if (label.startsWith("f__")) return "family"
                if (label.startsWith("g__")) return "genus"
                if (label.startsWith("s__")) return "species"
            }
        }

        // Check 3: NCBI Subclasses (if source)
        if (isSource && rank == null) {
             // Expensive check? iterate supers.
             EntitySearcher.getSuperClasses(cls, ont).each { ce ->
                 if (!ce.isAnonymous()) {
                     def sIRI = ce.asOWLClass().getIRI().toString()
                     if (NCBI_RANK_CLASSES.containsKey(sIRI)) {
                         rank = NCBI_RANK_CLASSES[sIRI]
                     }
                 }
             }
        }
        
        return rank
    }

    boolean isRankProperty(String propIri) {
        if (RANK_PROPS.contains(propIri)) return true
        if (propIri.toLowerCase().endsWith("rank") || propIri.contains("has_rank")) return true
        return false
    }
    
    String normalizeRank(String r) {
        String n = r.trim().toLowerCase()
        if (n == "superkingdom") return "domain"
        return n
    }

    String getLabel(OWLOntology ont, IRI iri) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        String label = null
        EntitySearcher.getAnnotations(cls, ont).each { ann ->
            if (ann.getProperty().isLabel() && ann.getValue().isLiteral()) {
                label = ann.getValue().asLiteral().get().getLiteral()
            }
        }
        return label
    }
    
    String getLabel(OWLOntology ont, OWLClass cls) { // overload
        return getLabel(ont, cls.getIRI())
    }

    String normalize(String label) {
        if (!label) return ""
        String s = label.trim().toLowerCase()
        s = s.replaceAll(/^[dpcofgs]__/, "")
        s = s.replaceAll(/_[a-z0-9]+$/, "") // remove GTDB suffixes
        s = s.replaceAll(/^candidatus\s+/, "")
        s = s.replaceAll(/^ca\.\s+/, "")
        return s.trim()
    }

    Set<OWLClass> getParents(OWLOntology ont, IRI iri) {
        def cls = ont.getOWLOntologyManager().getOWLDataFactory().getOWLClass(iri)
        def parents = new HashSet<OWLClass>()
        EntitySearcher.getSuperClasses(cls, ont).each {
             if (!it.isAnonymous()) {
                 parents.add(it.asOWLClass())
             }
        }
        return parents
    }

    void writeCsv(String filename, List<Map> rows, List<String> headers) {
        def writer = Files.newBufferedWriter(Paths.get(filename))
        def printer = new CSVPrinter(writer, CSVFormat.DEFAULT.withHeader(*headers.toArray(new String[0])))
        
        rows.each { row ->
            def values = headers.collect { h -> row[h] }
            printer.printRecord(values)
        }
        printer.flush()
        printer.close()
        println "Written $filename"
    }
}