@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')
@Grab(group='org.yaml', module='snakeyaml', version='2.2')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.yaml.snakeyaml.Yaml
import java.io.File
import static java.lang.Math.*

/**
 * Script to generate Sampling Site ABox.
 * References terms from rubalkhali.owl.
 */

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def OBO = "http://purl.obolibrary.org/obo/"
def GEO = "http://www.opengis.net/ont/geosparql#"
def DCTERMS = "http://purl.org/dc/terms/"

// Haversine Distance
double calculateDistance(double lat1, double lon1, double lat2, double lon2) {
    double R = 6371e3 
    double dLat = toRadians(lat2 - lat1); double dLon = toRadians(lon2 - lon1)
    double a = sin(dLat / 2) * sin(dLat / 2) + cos(toRadians(lat1)) * cos(toRadians(lat2)) * sin(dLon / 2) * sin(dLon / 2)
    double c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c
}

class RawEntry { String originalId; Double lat; Double lon; Set<String> biomes = []; Set<String> features = []; Set<String> rawBiomes = []; Set<String> rawFeatures = [] }
class FinalSite { String baseName; String label; Double avgLat; Double avgLon; Double avgAlt; Set<String> biomes = []; Set<String> features = []; Set<String> rawBiomes = []; Set<String> rawFeatures = [] }

def yaml = new Yaml()
def config = yaml.load(new File("config/codes/biome_codes.yml").text)
def biomeMap = config.biomes ?: [:]
def featureMap = config.features ?: [:]

def altitudeMap = [:]
def altFile = new File("data/metadata/site_altitudes.tsv")
if (altFile.exists()) {
    altFile.eachLine { line, no ->
        if (no == 1) return
        def p = line.split("\t")
        if (p.size() >= 4 && p[3].trim()) altitudeMap[p[0].trim()] = p[3].toDouble()
    }
}

def allEntries = []
new File("data/metadata/samplesheets").listFiles().each { f ->
    if (!f.name.startsWith("trip") || !f.name.endsWith(".tsv")) return
    def lines = f.readLines(); if (lines.isEmpty()) return
    def header = lines[0].split("\t")
    def colSite = header.findIndexOf { it.trim().equalsIgnoreCase("site") }
    def colCoords = header.findIndexOf { it.trim().equalsIgnoreCase("coordinates") || it.trim().equalsIgnoreCase("gps") }
    def colBiome = header.findIndexOf { it.trim().equalsIgnoreCase("biome") }
    def colFeature = header.findIndexOf { it.trim().equalsIgnoreCase("feature") }

    lines.drop(1).each { line ->
        if (!line.trim()) return
        def parts = line.split("\t"); if (parts.size() <= colSite) return
        def siteId = parts[colSite].trim(); if (!siteId) return
        def entry = new RawEntry(originalId: siteId)
        if (colCoords != -1 && parts.size() > colCoords) {
            def m = parts[colCoords] =~ /([-+]?\d+\.\d+)\s*N?\s*,\s*([-+]?\d+\.\d+)\s*E?/
            if (m) { entry.lat = m[0][1].toDouble(); entry.lon = m[0][2].toDouble() }
        }
        if (colBiome != -1 && parts.size() > colBiome && parts[colBiome].trim()) {
            def b = parts[colBiome].trim().toLowerCase(); entry.rawBiomes << b
            if (biomeMap[b]) entry.biomes << biomeMap[b]
        }
        if (colFeature != -1 && parts.size() > colFeature && parts[colFeature].trim()) {
            def fVal = parts[colFeature].trim().toLowerCase(); entry.rawFeatures << fVal
            if (featureMap[fVal]) entry.features << featureMap[fVal]
        }
        allEntries << entry
    }
}

def finalSites = [] 
(1..64).each { i ->
    def siteStr = i.toString()
    def matching = allEntries.findAll { e -> e.originalId == siteStr && e.lat != null }
    if (matching) {
        def fs = new FinalSite(baseName: siteStr, label: "Site " + siteStr)
        fs.avgLat = matching.collect { e -> e.lat }.sum() / matching.size()
        fs.avgLon = matching.collect { e -> e.lon }.sum() / matching.size()
        fs.avgAlt = altitudeMap[siteStr]
        matching.each { e -> fs.biomes.addAll(e.biomes); fs.features.addAll(e.features); fs.rawBiomes.addAll(e.rawBiomes); fs.rawFeatures.addAll(e.rawFeatures) }
        finalSites << fs
    }
}
allEntries.findAll { e -> !(e.originalId ==~ /^\d+$/ && e.originalId.toInteger() >= 1 && e.originalId.toInteger() <= 64) }.each { entry ->
    if (entry.lat == null) return
    def existing = finalSites.find { fs -> calculateDistance(entry.lat, entry.lon, fs.avgLat, fs.avgLon) < 500.0 }
    if (existing) { existing.biomes.addAll(entry.biomes); existing.features.addAll(entry.features); existing.rawBiomes.addAll(entry.rawBiomes); existing.rawFeatures.addAll(entry.rawFeatures) }
    else {
        def fs = new FinalSite(baseName: entry.originalId, avgLat: entry.lat, avgLon: entry.lon)
        fs.avgAlt = altitudeMap[entry.originalId]
        fs.biomes.addAll(entry.biomes); fs.features.addAll(entry.features); fs.rawBiomes.addAll(entry.rawBiomes); fs.rawFeatures.addAll(entry.rawFeatures)
        finalSites << fs
    }
}
def nameCounts = [:]; finalSites.each { fs -> if (fs.label) return; nameCounts[fs.baseName] = (nameCounts[fs.baseName] ?: 0) + 1 }
def curSeq = [:]; finalSites.each { fs ->
    if (fs.label) return
    if (nameCounts[fs.baseName] > 1) { def s = (curSeq[fs.baseName] ?: 0) + 1; curSeq[fs.baseName] = s; fs.label = "Site ${fs.baseName} (location ${s})" }
    else fs.label = "Site " + fs.baseName
}

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()
def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_sites.owl"))
def dcDesc = df.getOWLAnnotationProperty(IRI.create(DCTERMS + "description"))
def wktLiteral = df.getOWLDatatype(IRI.create(GEO + "wktLiteral"))
def wgsAlt = df.getOWLDataProperty(IRI.create("http://www.w3.org/2003/01/geo/wgs84_pos#alt"))

// Referencing terms from rubalkhali.owl
def hasBiome = df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000001"))
def hasEnvFeature = df.getOWLObjectProperty(IRI.create(BASE + "RAK_2000002"))
def siteClass = df.getOWLClass(IRI.create(BASE + "RAK_0000002"))
def asWKT = df.getOWLAnnotationProperty(IRI.create(GEO + "asWKT"))

int counter = 1
finalSites.each { fs ->
    def siteIri = IRI.create(BASE + String.format("RAK_1%06d", counter++))
    def siteInd = df.getOWLNamedIndividual(siteIri)
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(siteClass, siteInd))
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(siteIri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral(fs.label))))
    def desc = "Sampling site located at ${fs.avgLat}, ${fs.avgLon}."
    if (fs.rawBiomes) desc += " Biome: " + fs.rawBiomes.join(", ") + "."
    if (fs.rawFeatures) desc += " Features: " + fs.rawFeatures.join(", ") + "."
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(siteIri, df.getOWLAnnotation(dcDesc, df.getOWLLiteral(desc))))
    if (fs.avgLat != null) {
        def wkt = "POINT(${fs.avgLon} ${fs.avgLat}" + (fs.avgAlt != null ? " ${fs.avgAlt}" : "") + ")"
        manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(siteIri, df.getOWLAnnotation(asWKT, df.getOWLLiteral(wkt, wktLiteral))))
        if (fs.avgAlt != null) {
            manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(wgsAlt, siteInd, fs.avgAlt))
        }
    }
    fs.biomes.each { id ->
        def cls = df.getOWLClass(IRI.create(OBO + id))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLObjectSomeValuesFrom(hasBiome, cls), siteInd))
    }
    fs.features.each { id ->
        def cls = df.getOWLClass(IRI.create(OBO + id))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLObjectSomeValuesFrom(hasEnvFeature, cls), siteInd))
    }
}

// Rub' al Khali region
def rakIri = IRI.create(BASE + "RAK_1999999")
def rakInd = df.getOWLNamedIndividual(rakIri)
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLClass(IRI.create(OBO + "ENVO_00000192")), rakInd))
manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(rakIri, df.getOWLAnnotation(df.getRDFSLabel(), df.getOWLLiteral("Rub' al Khali (Empty Quarter)"))))
manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(rakIri, df.getOWLAnnotation(dcDesc, df.getOWLLiteral("Approximate boundary of the Rub' al Khali desert."))))
manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(rakIri, df.getOWLAnnotation(asWKT, df.getOWLLiteral("POLYGON((46.50 17.45, 50.70 17.15, 53.25 17.00, 55.65 19.45, 55.80 22.50, 53.50 23.80, 51.00 24.10, 48.50 23.25, 46.00 21.50, 45.00 19.80, 44.80 19.00, 45.50 18.00, 46.50 17.45))", wktLiteral))))

manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_sites.owl").toURI()))
println "Success: Generated rubalkhali_sites.owl using centralized TBox."