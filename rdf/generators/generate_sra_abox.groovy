@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')
@Grab(group='org.apache.commons', module='commons-csv', version='1.10.0')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import java.io.File
import java.io.FileReader
import org.apache.commons.csv.CSVFormat
import org.apache.commons.csv.CSVParser
import org.semanticweb.owlapi.search.EntitySearcher

/**
 * Script to generate SRA Submission ABox (Libraries, Sequencing, Runs)
 * References terms from rubalkhali.owl.
 */

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def RDFS = "http://www.w3.org/2000/01/rdf-schema#"
def DC = "http://purl.obolibrary.org/dc/elements/1.1/"

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()
def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_sra.owl"))

// --- Helper Functions ---
def addLabel = { iri, label ->
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(label))))
}
def addDesc = { iri, desc ->
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(DC + "description")), df.getOWLLiteral(desc))))
}
def addSeeAlso = { iri, url ->
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(df.getOWLAnnotationProperty(IRI.create(RDFS + "seeAlso")), IRI.create(url))))
}

// Properties
def hasInput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000230"))
def hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
def isPartOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000068"))
def isSpecifiedBy = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000339"))
def hasAgent = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000139"))

// Properties from rubalkhali.owl
def usesFwdPrimer = df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000018"))
def usesRevPrimer = df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000019"))

// Classes from rubalkhali.owl or SIO
def experimentClass = df.getOWLClass(IRI.create(SIO + "SIO_000994"))
def experimentalProtocolClass = df.getOWLClass(IRI.create(SIO + "SIO_001043"))
def studyClass = df.getOWLClass(IRI.create(SIO + "SIO_001080"))
def organizationClass = df.getOWLClass(IRI.create(SIO + "SIO_000012"))

def ampliconLibClass = df.getOWLClass(IRI.create(BASE + "RAK_0000060"))
def fwdPrimerClass = df.getOWLClass(IRI.create(BASE + "RAK_0000061"))
def revPrimerClass = df.getOWLClass(IRI.create(BASE + "RAK_0000062"))
def fastqDatasetClass = df.getOWLClass(IRI.create(BASE + "RAK_0000063"))
def libPrepClass = df.getOWLClass(IRI.create(BASE + "RAK_0000065"))
def sequencingClass = df.getOWLClass(IRI.create(BASE + "RAK_0000066"))


// --- 2. Static Individuals ---

// Umbrella Project
def umbrellaProj = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_E000010"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(studyClass, umbrellaProj))
addLabel(umbrellaProj.getIRI(), "Rub' al Khali Umbrella Project")
addSeeAlso(umbrellaProj.getIRI(), "https://identifiers.org/bioproject/PRJEB104209")

// 16S Project
def ampliconProj = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_E000011"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(studyClass, ampliconProj))
addLabel(ampliconProj.getIRI(), "Rub' al Khali 16S amplicon sequencing")
addSeeAlso(ampliconProj.getIRI(), "https://identifiers.org/bioproject/PRJEB106069")
manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isPartOf, ampliconProj, umbrellaProj))

// Agent: Corelabs
def corelabs = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_A000020"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(organizationClass, corelabs))
addLabel(corelabs.getIRI(), "KAUST Bioscience Corelabs")

// Protocol
def illuminaProto = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_L000010"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(experimentalProtocolClass, illuminaProto))
addLabel(illuminaProto.getIRI(), "16S amplicon library prep protocol")
addSeeAlso(illuminaProto.getIRI(), "https://support.illumina.com/documents/documentation/chemistry_documentation/16s/16s-metagenomic-library-prep-guide-15044223-b.pdf")


// --- 3. Look up DNA Extracts ---
def sampleToExtractIri = [:]
def dnaFile = new File("data/processed/ontology/rubalkhali_dna.owl")
if (dnaFile.exists()) {
    println "Loading rubalkhali_dna.owl to map samples to extracts..."
    def dnaOnt = manager.loadOntologyFromOntologyDocument(dnaFile)
    dnaOnt.getIndividualsInSignature().each { ind ->
        EntitySearcher.getAnnotationObjects(ind, dnaOnt, df.getRDFSLabel()).each { ann ->
            String label = ann.getValue().asLiteral().get().getLiteral()
            if (label.startsWith("DNA extract of sample ")) {
                String sampleName = label.replace("DNA extract of sample ", "").trim()
                sampleToExtractIri[sampleName] = ind.getIRI()
            }
        }
    }
    manager.removeOntology(dnaOnt)
    println "Mapped ${sampleToExtractIri.size()} samples to DNA extracts."
}


// --- 4. Process SRA Submission Sheet ---
def tsvFile = new File("data/metadata/sra-submissions/submission-sheet.tsv")
FileReader reader = new FileReader(tsvFile)
CSVParser parser = CSVFormat.TDF.withFirstRecordAsHeader().parse(reader)

int libPrepCounter = 250001
int sequencingCounter = 280001
int libraryCounter = 690001
int fastqCounter = 790001
int primerInstanceCounter = 1

parser.each { record ->
    String sampleName = record.get("sample_name")
    String libraryName = record.get("library_name")
    String runAccession = record.get("run_accession")
    String biosampleAccession = record.get("biosample_accession")
    
    IRI extractIri = sampleToExtractIri[sampleName]
    // Fallback: strip suffix (O/T/R/RE) and try different replicates
    if (!extractIri) {
        def baseName = sampleName.replaceAll(/(O|T|RE|R)$/, "")
        extractIri = sampleToExtractIri[baseName]
        // Try replicate 1 if current replicate not found
        if (!extractIri) {
            def rep1Name = baseName.replaceAll(/r\d+$/, "r1")
            extractIri = sampleToExtractIri[rep1Name]
        }
    }
    if (!extractIri) return

    // --- A. Create Primer Instances ---
    def fwdPrimerInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_F" + String.format("%06d", primerInstanceCounter)))
    def revPrimerInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_R" + String.format("%06d", primerInstanceCounter)))
    primerInstanceCounter++

    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(fwdPrimerClass, fwdPrimerInd))
    addLabel(fwdPrimerInd.getIRI(), "Forward Primer for ${libraryName}")
    
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(revPrimerClass, revPrimerInd))
    addLabel(revPrimerInd.getIRI(), "Reverse Primer for ${libraryName}")


    // --- B. Library Prep Process ---
    def libPrepInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", libPrepCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(libPrepClass, libPrepInd))
    addLabel(libPrepInd.getIRI(), "Library preparation for ${libraryName}")
    
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, libPrepInd, df.getOWLNamedIndividual(extractIri)))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(usesFwdPrimer, libPrepInd, fwdPrimerInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(usesRevPrimer, libPrepInd, revPrimerInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isSpecifiedBy, libPrepInd, illuminaProto))
    
    // Output: Library
    def libraryInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_6" + String.format("%06d", libraryCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(ampliconLibClass, libraryInd))
    addLabel(libraryInd.getIRI(), libraryName)
    addDesc(libraryInd.getIRI(), "16S amplicon library ${libraryName} (BioSample: ${biosampleAccession})")
    addSeeAlso(libraryInd.getIRI(), "https://identifiers.org/biosample/${biosampleAccession}")
    
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, libPrepInd, libraryInd))


    // --- C. Sequencing Process ---
    def seqProcInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", sequencingCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(sequencingClass, seqProcInd))
    addLabel(seqProcInd.getIRI(), "Sequencing of ${libraryName} (${runAccession})")
    
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasInput, seqProcInd, libraryInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isPartOf, seqProcInd, ampliconProj))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, seqProcInd, corelabs))

    // Output: FASTQ Dataset
    def fastqInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_7" + String.format("%06d", fastqCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(fastqDatasetClass, fastqInd))
    addLabel(fastqInd.getIRI(), "FASTQ dataset for ${runAccession}")
    addDesc(fastqInd.getIRI(), "FASTQ read dataset from run ${runAccession} (ERR).")
    addSeeAlso(fastqInd.getIRI(), "https://identifiers.org/insdc.run/${runAccession}")
    
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, seqProcInd, fastqInd))
}

manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_sra.owl").toURI()))
println "Success: Generated data/processed/ontology/rubalkhali_sra.owl"