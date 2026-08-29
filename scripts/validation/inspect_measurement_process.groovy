@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.model.parameters.Imports
import java.io.File

def file = new File("data/processed/ontology/rubalkhali_measurements.owl")
def manager = OWLManager.createOWLOntologyManager()
def ontology = manager.loadOntologyFromOntologyDocument(file)

def targetIri = IRI.create("https://rubalkhali.science/kb/RAK_P000191")

println "Detailed Triple Inspection for ${targetIri}:"

ontology.getAxioms(Imports.INCLUDED).each { axiom ->
    if (axiom instanceof OWLAnnotationAssertionAxiom) {
        if (axiom.getSubject().equals(targetIri)) {
            println "Annotation: " + axiom.getProperty() + " Value: " + axiom.getValue()
        }
    } else if (axiom instanceof OWLClassAssertionAxiom) {
        if (axiom.getIndividual().asOWLNamedIndividual().getIRI().equals(targetIri)) {
             println "Type: " + axiom.getClassExpression()
        }
    } else if (axiom instanceof OWLObjectPropertyAssertionAxiom) {
        if (axiom.getSubject().asOWLNamedIndividual().getIRI().equals(targetIri)) {
            println "ObjectProp: " + axiom.getProperty() + " Obj: " + axiom.getObject()
        }
    } else if (axiom instanceof OWLDataPropertyAssertionAxiom) {
        if (axiom.getSubject().asOWLNamedIndividual().getIRI().equals(targetIri)) {
            println "DataProp: " + axiom.getProperty() + " Val: " + axiom.getObject()
        }
    }
}
