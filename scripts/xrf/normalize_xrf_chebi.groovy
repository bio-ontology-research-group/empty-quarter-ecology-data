@Grab(group='org.yaml', module='snakeyaml', version='2.2')
import org.yaml.snakeyaml.Yaml
import java.io.File

/**
 * Add the audited ChEBI identifier column to per-instrument XRF exports.
 *
 * The canonical mapping is config/codes/xrf_chemical_mapping.yml.  This
 * script deliberately performs no label or one-letter-symbol lookup: those
 * heuristics caused the retired amino-acid and fabricated-oxide mappings.
 * Run scripts/xrf/audit_xrf_chemical_mapping.py before using this normalizer.
 */

def mappingPath = "config/codes/xrf_chemical_mapping.yml"
def xrfProcessedDir = "data/processed/xrf/"

def mappingDocument = new Yaml().load(new File(mappingPath).text)
def canonicalMapping = (mappingDocument.mappings ?: [:]).collectEntries {
    analyte, entry -> [(analyte.toString()): (entry.chebi ?: "").toString()]
}

if (!canonicalMapping.containsKey("LE") || canonicalMapping["LE"]) {
    throw new IllegalStateException(
        "Canonical mapping must contain an explicitly unmapped LE pseudo-analyte"
    )
}

def processFile(File tableFile, Map<String, String> mapping) {
    println "Processing ${tableFile}"
    def lines = tableFile.readLines("UTF-8")
    if (lines.isEmpty()) return

    def header = lines[0]
    def separator = header.contains('\t') ? '\t' : ','
    def headers = header.split(separator, -1)
    def analyteIndex = headers.findIndexOf {
        it.replaceAll('^"|"$', '').equalsIgnoreCase("Analyte")
    }
    if (analyteIndex < 0) {
        println "  Skipping: no Analyte column"
        return
    }
    if (headers.any {
        it.replaceAll('^"|"$', '').equalsIgnoreCase("ChEBI_ID")
    }) {
        println "  Skipping: ChEBI_ID already present"
        return
    }

    def output = [header + separator + "ChEBI_ID"]
    lines.drop(1).eachWithIndex { line, rowIndex ->
        if (!line.trim()) return
        def fields = line.split(separator, -1)
        if (analyteIndex >= fields.length) {
            throw new IllegalArgumentException(
                "${tableFile}: row ${rowIndex + 2} has no Analyte field"
            )
        }
        def analyte = fields[analyteIndex].replaceAll('^"|"$', '').trim()
        if (!mapping.containsKey(analyte)) {
            throw new IllegalArgumentException(
                "${tableFile}: row ${rowIndex + 2} has unreviewed analyte '${analyte}'"
            )
        }
        output << (line + separator + mapping[analyte])
    }

    tableFile.write(output.join("\n") + "\n", "UTF-8")
    println "  Updated from ${mappingPath}"
}

def trip5Dir = new File(xrfProcessedDir + "trip-5-lab/")
if (trip5Dir.exists()) {
    trip5Dir.eachFileMatch(~/.*\.tsv/) { file ->
        processFile(file, canonicalMapping)
    }
}

def baseDir = new File(xrfProcessedDir)
if (baseDir.exists()) {
    baseDir.eachDirMatch(~/Site_.*/) { siteDir ->
        siteDir.eachDirMatch(~/Test_.*/) { testDir ->
            testDir.eachFileMatch(~/vanta_data_.*\.csv/) { file ->
                processFile(file, canonicalMapping)
            }
        }
    }
}

println "Done."
