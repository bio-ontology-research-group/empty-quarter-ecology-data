@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')
@Grab(group='com.google.code.gson', module='gson', version='2.10.1')
@Grab(group='commons-cli', module='commons-cli', version='1.6.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.search.EntitySearcher
import org.apache.commons.csv.*
import com.google.gson.Gson
import org.apache.commons.cli.*
import java.io.File
import java.security.MessageDigest

def cli = new DefaultParser().parse(new Options()
    .addOption("s", "small", false, "Build a small version (first 3 samples only)")
    .addOption("h", "help", false, "Show help"), args)

if (cli.hasOption("h")) {
    println "Usage: groovy scripts/generate_taxonomy_abox.groovy [-s/--small]"
    return
}

boolean smallVersion = cli.hasOption("s")

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def PATO = "http://purl.obolibrary.org/obo/PATO_"
def NCBITAXON = "http://purl.obolibrary.org/obo/NCBITaxon_"

def manager = OWLManager.createOWLOntologyManager()
def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_taxonomy_abox.owl"))
def df = manager.getOWLDataFactory()

// Add imports
manager.applyChange(new AddImport(ontology, df.getOWLImportsDeclaration(IRI.create(BASE + "ecosystem_module.owl"))))

def rdfsLabel = df.getRDFSLabel()
def hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
def hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
def isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
def hasMeasurementValue = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000214"))
def isMeasurementValueOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000215"))
def isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))
def isSpecifiedBy = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000339"))
def hasMember = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000059"))

// New Data Property for Lineage
def hasLineageString = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000025"))

// Datatype properties
def hasRelativeAbundanceValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000020"))
def hasAbsoluteAbundanceValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000021"))

// TBox Classes
def workflowClass = df.getOWLClass(IRI.create(BASE + "RAK_0000071"))
def absoluteDatasetClass = df.getOWLClass(IRI.create(BASE + "RAK_0000074"))
def relativeDatasetClass = df.getOWLClass(IRI.create(BASE + "RAK_0000075"))
def absoluteValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000076"))
def relativeValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000073"))
def amountQualityClass = df.getOWLClass(IRI.create(PATO + "0000070"))
def concentrationQualityClass = df.getOWLClass(IRI.create(PATO + "0000033"))
def absoluteQualityClass = df.getOWLClass(IRI.create(BASE + "RAK_0000078"))
def relativeQualityClass = df.getOWLClass(IRI.create(BASE + "RAK_0000072"))

def protocolInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_L000012"))

def addLabel = { iri, label ->
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(rdfsLabel, df.getOWLLiteral(label))))
}

addLabel(protocolInd.getIRI(), "16S amplicon processing protocol")

// 1. Load Mappings
def mappedTaxonomy = new Gson().fromJson(new File("data/processed/ontology/mapped_taxonomy.json").text, Map.class)

// 2. Load SRA Mappings
def sampleToRuns = [:].withDefault { [] }
def sraTsv = new File("data/metadata/sra-submissions/submission-sheet.tsv")
if (sraTsv.exists()) {
    sraTsv.withReader { reader ->
        CSVFormat.TDF.withFirstRecordAsHeader().parse(reader).each { record ->
            sampleToRuns[record.get("sample_name")] << record.get("run_accession")
        }
    }
}

// 3. Load FASTQ Dataset IRIs
def fastqMap = [:]
def sraOntFile = new File("data/processed/ontology/rubalkhali_sra.owl")
if (sraOntFile.exists()) {
    def sraOnt = manager.loadOntologyFromOntologyDocument(sraOntFile)
    sraOnt.getIndividualsInSignature().each { ind ->
        EntitySearcher.getAnnotationObjects(ind, sraOnt, rdfsLabel).each { ann ->
            def label = ann.getValue().asLiteral().get().getLiteral()
            if (label.startsWith("FASTQ dataset for ")) {
                fastqMap[label.substring("FASTQ dataset for ".length())] = ind.getIRI()
            }
        }
    }
    manager.removeOntology(sraOnt)
}

// 4. Resolve taxonomic IRIs and labels
def featureToTaxonStr = [:]
// Use trips1-5 consolidated files (includes Trip 5 amplicon data)
def taxonomyFile = new File("data/processed/taxonomy/taxon-tables/taxonomy-trips1-5.tsv")
if (!taxonomyFile.exists()) {
    taxonomyFile = new File("data/processed/taxon-tables/taxonomy.tsv")
}
println "Loading taxonomy from: ${taxonomyFile.absolutePath}"
taxonomyFile.withReader { reader ->
    CSVFormat.TDF.withFirstRecordAsHeader().parse(reader).each { record ->
        featureToTaxonStr[record.get("Feature ID")] = record.get("Taxon")
    }
}

// Data structures for aggregation
// Sample -> Rank -> IRI -> Count
def sampleRankIriCounts = [:].withDefault { [:].withDefault { [:].withDefault { 0.0 } } }
def sampleTotals = [:]
def samples = []
def ranks = ["domain", "phylum", "class", "order", "family", "genus", "species"]
def iriToLabel = [:] 
def iriToLineage = [:]

// Helper to generate a consistent IRI for "Unknown" taxa
def getUnknownIri = { parentIriStr, rank ->
    def input = parentIriStr + "_" + rank + "_Unknown"
    def digest = MessageDigest.getInstance("MD5")
    digest.update(input.getBytes("UTF-8"))
    def hash = new BigInteger(1, digest.digest()).toString(16).padLeft(32, '0')
    return IRI.create(BASE + "RAK_UNK_" + hash.substring(0, 12))
}

def featureTableFile = new File("data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv")
if (!featureTableFile.exists()) {
    featureTableFile = new File("data/processed/taxon-tables/feature-table.tsv")
}
println "Loading feature table from: ${featureTableFile.absolutePath}"
featureTableFile.withReader { reader ->
    reader.readLine() // Skip comment
    def parser = CSVFormat.TDF.withFirstRecordAsHeader().parse(reader)
    samples = parser.getHeaderNames().findAll { it != "#OTU ID" }
    
    if (smallVersion) {
        samples = samples.take(3)
        println "Mode: SMALL (3 samples)"
    } else {
        println "Mode: FULL (${samples.size()} samples)"
    }

    samples.each { col -> sampleTotals[col] = 0.0 }

    parser.each { record ->
        def taxonStr = featureToTaxonStr[record.get("#OTU ID")]
        def mapping = mappedTaxonomy[taxonStr]
        if (!mapping) return
        
        samples.each { col ->
            def val = record.get(col) ? Double.parseDouble(record.get(col)) : 0.0
            if (val > 0) {
                sampleTotals[col] += val
                
                // Aggregate per rank
                def lineageParts = []
                def currentParentIri = "ROOT" // Placeholder for top level

                ranks.eachWithIndex { rankName, i ->
                    def item = null
                    if (i < mapping.size()) {
                        item = mapping[i]
                    } else {
                        // Inherit last known for structure, but handle as unknown if we ran out of mapping
                        // Actually, if we ran out of mapping, item is null
                    }

                    // Determine if we have a valid known taxon at this rank
                    def isUnknown = false
                    def taxonIri = null
                    def taxonLabel = "Unknown"

                    if (item) {
                        def name = item.clean ?: item.name
                        if (!name || name == "NA" || name == "Unclassified" || name == "unclassified" || name == "uncultured") {
                            isUnknown = true
                        } else {
                            taxonIri = IRI.create(item.iri)
                            taxonLabel = name
                        }
                    } else {
                        isUnknown = true
                    }

                    if (isUnknown) {
                        // Generate a unique IRI for this "Unknown" node based on its parent
                        // effectively creating "Unknown Family (child of Order X)"
                        taxonIri = getUnknownIri(currentParentIri, rankName)
                        taxonLabel = "Unknown"
                    }

                    // Build Lineage String
                    lineageParts << "${rankName.capitalize()}: ${taxonLabel}"
                    def fullLineage = lineageParts.join("; ")

                    // Store counts
                    sampleRankIriCounts[col][rankName][taxonIri] += val
                    
                    // Store Metadata
                    if (!iriToLabel.containsKey(taxonIri)) {
                        iriToLabel[taxonIri] = taxonLabel
                    }
                    // Only store lineage if not present or overwrite? 
                    // Overwriting is fine as the lineage for a specific IRI (especially the unknowns) 
                    // is constant in this context.
                    iriToLineage[taxonIri] = fullLineage

                    // Update parent for next iteration
                    currentParentIri = taxonIri.toString()
                }
            }
        }
    }
}

// 6. Generate RDF
long procCounter = 290001
long dsCounter = 740001 
long valCounter = 40000000
long qualCounter = 50000000

def columnsPerSample = [:].withDefault { 0 }
sampleRankIriCounts.keySet().each { col ->
    columnsPerSample[col.split('_')[-1]]++
}

def sampleUsageCount = [:].withDefault { 0 }

sampleRankIriCounts.each { sampleCol, rankMap ->
    def sampleName = sampleCol.split('_')[-1]
    def runs = sampleToRuns[sampleName]
    if (!runs) {
        println "Warning: No run found for sample ${sampleName} (from ${sampleCol})"
        return
    }
    
    def targetRuns = []
    if (columnsPerSample[sampleName] == 1 && runs.size() > 1) {
        targetRuns = runs
    } else {
        int index = sampleUsageCount[sampleName]
        if (index < runs.size()) {
            targetRuns = [runs[index]]
        } else {
             targetRuns = [runs.last()]
        }
        sampleUsageCount[sampleName]++
    }
    
    targetRuns.each { runAccession ->
    
        def fastqIri = fastqMap[runAccession]
        if (!fastqIri) {
            println "Warning: No FASTQ IRI found for run ${runAccession} (sample ${sampleName})"
            return
        }
        
        def total = sampleTotals[sampleCol] ?: 1.0
        
        // Process
        def procInd = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_P%06d", procCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(workflowClass, procInd))
        addLabel(procInd.getIRI(), "16S amplicon processing of ${sampleName} (${runAccession})")
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, procInd, df.getOWLNamedIndividual(fastqIri)))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isSpecifiedBy, procInd, protocolInd))
        
        // Iterate Ranks
        rankMap.each { rankName, iriMap ->
            // Format rank name for label (Capitalize)
            String rankLabel = rankName.capitalize()
            
            // Output Datasets per Rank
            def dsAbsInd = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_7%06d", dsCounter++)))
            def dsRelInd = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_7%06d", dsCounter++)))
            
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(absoluteDatasetClass, dsAbsInd))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(relativeDatasetClass, dsRelInd))
            
            addLabel(dsAbsInd.getIRI(), "Taxon absolute abundance dataset for ${sampleName} (${rankLabel})")
            addLabel(dsRelInd.getIRI(), "Taxon relative abundance dataset for ${sampleName} (${rankLabel})")
            
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, dsAbsInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, procInd, dsRelInd))

            iriMap.each { iri, count ->
                def label = iriToLabel[iri]
                def lineage = iriToLineage[iri]
                
                // Absolute
                def vAbs = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_%d", valCounter++)))
                def qAbs = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_%d", qualCounter++)))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(absoluteValueClass, vAbs))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(absoluteQualityClass, qAbs))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(amountQualityClass, qAbs))
                
                addLabel(vAbs.getIRI(), "Absolute abundance of ${label} in ${sampleName} (${rankLabel})")
                
                manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasAbsoluteAbundanceValue, vAbs, count))
                manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasLineageString, vAbs, lineage))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMeasurementValue, qAbs, vAbs))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, vAbs, qAbs))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qAbs, df.getOWLNamedIndividual(iri)))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qAbs, df.getOWLNamedIndividual(fastqIri)))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMember, dsAbsInd, vAbs))

                // Relative
                def vRel = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_%d", valCounter++)))
                def qRel = df.getOWLNamedIndividual(IRI.create(BASE + String.format("RAK_%d", qualCounter++)))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(relativeValueClass, vRel))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(relativeQualityClass, qRel))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(concentrationQualityClass, qRel))
                
                addLabel(vRel.getIRI(), "Relative abundance of ${label} in ${sampleName} (${rankLabel})")
                
                manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasRelativeAbundanceValue, vRel, count / total))
                manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasLineageString, vRel, lineage))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMeasurementValue, qRel, vRel))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, vRel, qRel))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qRel, df.getOWLNamedIndividual(iri)))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qRel, df.getOWLNamedIndividual(fastqIri)))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMember, dsRelInd, vRel))
            }
        }
    }
}

manager.saveOntology(ontology, new org.semanticweb.owlapi.formats.TurtleDocumentFormat(), IRI.create(new File("data/processed/ontology/rubalkhali_taxonomy_abox.ttl").toURI()))
println "Done."