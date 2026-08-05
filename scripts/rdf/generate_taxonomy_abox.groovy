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
import java.nio.charset.StandardCharsets
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/*
 * Generate the taxonomy abundance ABox from the audited, corrected taxonomy
 * mapping.  This generator deliberately refuses the historical
 * mapped_taxonomy.json: it requires the corrected JSON and its PASS manifest,
 * and verifies the checksums of every consumed semantic input before doing any
 * work.
 */

def options = new Options()
options.addOption(Option.builder("s").longOpt("small").desc(
    "Build only the first three profile columns (fixture/smoke-test mode)"
).build())
[
    ["mapping-json", "Audited mapped_taxonomy_corrected.json"],
    ["mapping-manifest", "PASS manifest for the corrected mapping"],
    ["taxonomy-tsv", "Raw feature-to-taxonomy TSV used by the mapping audit"],
    ["feature-table", "Feature-count table TSV"],
    ["sra-sheet", "SRA submission sheet TSV"],
    ["sra-ontology", "SRA OWL file containing FASTQ dataset individuals"],
    ["import-module", "Local ecosystem module file recorded in the manifest"],
    ["import-iri", "Ontology IRI to declare as the ABox import"],
    ["output", "Output Turtle file"],
].each { spec ->
    options.addOption(Option.builder().longOpt(spec[0]).hasArg().required()
        .desc(spec[1]).build())
}
options.addOption(Option.builder("h").longOpt("help").desc("Show help").build())

def parser = new DefaultParser()
def cli
if (args.any { it in ["-h", "--help"] }) {
    new HelpFormatter().printHelp(
        "groovy scripts/rdf/generate_taxonomy_abox.groovy [options]",
        options
    )
    return
}
try {
    cli = parser.parse(options, args)
} catch (ParseException error) {
    System.err.println("ERROR: ${error.message}")
    new HelpFormatter().printHelp(
        "groovy scripts/rdf/generate_taxonomy_abox.groovy [options]",
        options
    )
    System.exit(2)
}
if (cli.hasOption("help")) {
    new HelpFormatter().printHelp(
        "groovy scripts/rdf/generate_taxonomy_abox.groovy [options]",
        options
    )
    return
}

def fail = { String message ->
    throw new IllegalStateException(message)
}
def requiredFile = { String option ->
    def path = new File(cli.getOptionValue(option)).canonicalFile
    if (!path.isFile()) {
        fail("--${option} is not a readable file: ${path}")
    }
    path
}
def sha256 = { File path ->
    def digest = MessageDigest.getInstance("SHA-256")
    path.withInputStream { stream ->
        byte[] buffer = new byte[1024 * 1024]
        int read
        while ((read = stream.read(buffer)) != -1) {
            digest.update(buffer, 0, read)
        }
    }
    digest.digest().collect { String.format("%02x", it & 0xff) }.join()
}
def verifyRecord = { Map record, File actual, String description ->
    if (!(record instanceof Map)) {
        fail("Mapping manifest lacks ${description} checksum record")
    }
    if (!(record.sha256 instanceof String) ||
            !(record.bytes instanceof Number)) {
        fail("Mapping manifest has an incomplete ${description} checksum record")
    }
    if (actual.length() != ((Number) record.bytes).longValue()) {
        fail("Stale ${description}: byte count ${actual.length()} does not match " +
            "manifest ${record.bytes}")
    }
    def observed = sha256(actual)
    if (!observed.equalsIgnoreCase(record.sha256.toString())) {
        fail("Stale ${description}: SHA-256 ${observed} does not match manifest " +
            record.sha256)
    }
}
def checkStatus = { Object check, String name ->
    def status = check instanceof Map ? check.status : check
    if (status?.toString()?.toLowerCase() != "passed") {
        fail("Mapping manifest check '${name}' is not passed")
    }
}

def mappingFile = requiredFile("mapping-json")
def manifestFile = requiredFile("mapping-manifest")
def taxonomyFile = requiredFile("taxonomy-tsv")
def featureTableFile = requiredFile("feature-table")
def sraTsv = requiredFile("sra-sheet")
def sraOntFile = requiredFile("sra-ontology")
def importModuleFile = requiredFile("import-module")
def outputFile = new File(cli.getOptionValue("output")).canonicalFile
def importIriString = cli.getOptionValue("import-iri")?.trim()
if (!(importIriString ==~ /^https?:\/\/\S+$/)) {
    fail("--import-iri must be an absolute HTTP(S) IRI")
}
outputFile.parentFile?.mkdirs()
if (!outputFile.parentFile?.isDirectory()) {
    fail("Could not create output directory for ${outputFile}")
}
if (outputFile.exists()) {
    fail("Refusing to overwrite existing output: ${outputFile}")
}
boolean smallVersion = cli.hasOption("small")

def gson = new Gson()
def manifest = gson.fromJson(manifestFile.getText("UTF-8"), Map.class)
if (!(manifest instanceof Map)) {
    fail("Mapping manifest is not a JSON object")
}
if (manifest.status?.toString()?.toLowerCase() != "passed") {
    fail("Mapping manifest status is not passed")
}
if (manifest.schema_version != "taxonomy-mapping-v1") {
    fail("Unsupported mapping manifest schema_version: ${manifest.schema_version}")
}
checkStatus(manifest.checks?.ancestry, "ancestry")
checkStatus(manifest.checks?.coverage, "coverage")
def missingTaxa = manifest.counts?.missing_taxon_strings
if (!(missingTaxa instanceof Number) ||
        ((Number) missingTaxa).longValue() != 0L) {
    fail("Mapping manifest does not prove zero missing taxon strings")
}
verifyRecord(
    manifest.artifacts?.corrected_json as Map,
    mappingFile,
    "corrected mapping JSON"
)
verifyRecord(
    manifest.inputs?.source_taxonomy as Map,
    taxonomyFile,
    "source taxonomy TSV"
)
verifyRecord(
    manifest.inputs?.feature_table as Map,
    featureTableFile,
    "feature table TSV"
)
verifyRecord(
    manifest.artifacts?.ecosystem_module as Map,
    importModuleFile,
    "imported ecosystem module"
)

def correctedTaxonomy = gson.fromJson(mappingFile.getText("UTF-8"), Map.class)
if (!(correctedTaxonomy instanceof Map) || correctedTaxonomy.isEmpty()) {
    fail("Corrected mapping JSON must be a non-empty object")
}

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def PATO = "http://purl.obolibrary.org/obo/PATO_"
def ranks = ["domain", "phylum", "class", "order", "family", "genus", "species"]
def rankLabels = ["Domain", "Phylum", "Class", "Order", "Family", "Genus", "Species"]
def confidencePattern = ~/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/

/*
 * The combined taxonomy source has exactly two encodings:
 *   - seven asserted rank fields; or
 *   - seven asserted rank fields, one supplementary provenance field, and a
 *     numeric confidence.
 * The supplementary eighth field is NEVER promoted, even when the asserted
 * species field is empty or conflicts with it.  This rule is shared with the
 * corrected-mapping builder and preserves rather than resolves that evidence.
 */
def normalizeTaxon = { String raw, String context ->
    if (raw == null) {
        fail("${context}: missing Taxon value")
    }
    def fields = raw.split(";", -1).collect { it.trim() }
    if (fields.size() == 9 && fields[8] ==~ confidencePattern) {
        fields = fields.take(7)
    } else if (fields.size() != 7) {
        fail("${context}: expected 7 ranks or 7+routing-field+numeric-confidence; " +
            "found ${fields.size()} fields in '${raw}'")
    }
    fields = fields.collect { String field ->
        def withoutPrefix = field.replaceFirst(/(?i)^[dkpcofgs]__/, "").trim()
        if (!withoutPrefix ||
                withoutPrefix.equalsIgnoreCase("na") ||
                withoutPrefix.equalsIgnoreCase("n/a") ||
                withoutPrefix.equalsIgnoreCase("unclassified") ||
                withoutPrefix.equalsIgnoreCase("uncultured")) {
            return "NA"
        }
        withoutPrefix
    }
    fields.join(";")
}

/*
 * Validate the mapping contract before reading the large feature table.
 * Source-lineage identity comes from the canonical seven-field JSON key.
 * Display labels and corrected IRIs come only from the audited mapping rows.
 */
def canonicalSegments = [:]
correctedTaxonomy.keySet().toList().sort().each { Object keyObject ->
    def key = keyObject.toString()
    def segments = key.split(";", -1).collect { it.trim() }
    if (segments.size() != 7 || key != segments.join(";")) {
        fail("Corrected mapping key is not a canonical seven-rank lineage: '${key}'")
    }
    def rows = correctedTaxonomy[key]
    if (!(rows instanceof List) || rows.size() != 7) {
        fail("Corrected mapping '${key}' must have exactly seven rank rows")
    }
    rows.eachWithIndex { Object rowObject, int index ->
        if (!(rowObject instanceof Map)) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} is not an object")
        }
        def row = rowObject as Map
        if (row.rank != ranks[index]) {
            fail("Corrected mapping '${key}' has rank '${row.rank}' at " +
                "position ${index}; expected '${ranks[index]}'")
        }
        if (!(row.iri instanceof String) ||
                !(row.iri ==~ /^https?:\/\/\S+$/)) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks a valid IRI")
        }
        if (!(row.label instanceof String) || row.label.trim().isEmpty()) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks a label")
        }
        if (!(row.source_name instanceof String)) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks source_name")
        }
        if (row.source_name != segments[index]) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} source_name " +
                "'${row.source_name}' does not match canonical source segment " +
                "'${segments[index]}'")
        }
        if (!(row.mapping_status in
                ["validated_ncbi", "stable_project", "contextual"])) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} has unsupported " +
                "mapping_status '${row.mapping_status}'")
        }
        if (row.mapping_status == "validated_ncbi" &&
                !(row.iri ==~ /^http:\/\/purl\.obolibrary\.org\/obo\/NCBITaxon_[0-9]+$/)) {
            fail("Validated NCBI mapping '${key}' rank ${ranks[index]} has " +
                "non-NCBI IRI '${row.iri}'")
        }
        if (row.mapping_status == "stable_project" &&
                !row.iri.toString().startsWith(BASE + "RAK_")) {
            fail("Stable project mapping '${key}' rank ${ranks[index]} has " +
                "non-project IRI '${row.iri}'")
        }
        if (row.mapping_status == "contextual" &&
                !(row.iri ==~ /^https:\/\/rubalkhali\.science\/kb\/RAK_CTX_[0-9a-f]{24}$/)) {
            fail("Contextual mapping '${key}' rank ${ranks[index]} has non-contextual " +
                "IRI '${row.iri}'")
        }
        if (!(row.source_lineage instanceof String)) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks source_lineage")
        }
        def expectedSourceLineage = segments.take(index + 1).join(";")
        if (row.source_lineage != expectedSourceLineage) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} source_lineage " +
                "does not equal '${expectedSourceLineage}'")
        }
        if (!(row.lineage instanceof String) || row.lineage.trim().isEmpty()) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks display lineage")
        }
        if (!(row.reason instanceof String) || row.reason.trim().isEmpty()) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks a reason")
        }
        if (!(row.original_id == null || row.original_id instanceof String)) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} has invalid original_id")
        }
        if (!(row.is_inherited instanceof Boolean)) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} lacks is_inherited")
        }
        if (index == 0 && row.parent_iri != null) {
            fail("Corrected mapping '${key}' domain parent_iri must be null")
        }
        if (index > 0 && row.parent_iri != rows[index - 1].iri) {
            fail("Corrected mapping '${key}' rank ${ranks[index]} has stale parent_iri")
        }
    }
    canonicalSegments[key] = segments
}
def manifestMapped = manifest.counts?.mapped_taxon_strings
def manifestSource = manifest.counts?.source_taxon_strings
def manifestRows = manifest.counts?.mapping_rows
if (!(manifestMapped instanceof Number) ||
        ((Number) manifestMapped).longValue() != correctedTaxonomy.size()) {
    fail("Corrected JSON cardinality does not match manifest mapped_taxon_strings")
}
if (!(manifestRows instanceof Number) ||
        ((Number) manifestRows).longValue() != correctedTaxonomy.size() * 7L) {
    fail("Corrected JSON row count does not match manifest mapping_rows")
}

// Read the raw taxonomy source, applying the exact audited normalization rule.
def featureToTaxon = [:]
def sourceTaxa = new TreeSet<String>()
taxonomyFile.withReader("UTF-8") { reader ->
    CSVFormat.TDF.builder().setHeader().setSkipHeaderRecord(true).build()
        .parse(reader).each { record ->
            def feature = record.get("Feature ID")?.trim()
            if (!feature) {
                fail("${taxonomyFile}: blank Feature ID at record ${record.recordNumber}")
            }
            def taxon = normalizeTaxon(
                record.get("Taxon"),
                "${taxonomyFile}: Feature ID ${feature}"
            )
            if (featureToTaxon.containsKey(feature)) {
                fail("${taxonomyFile}: duplicate Feature ID ${feature}")
            }
            featureToTaxon[feature] = taxon
            sourceTaxa.add(taxon)
        }
}
if (!(manifestSource instanceof Number) ||
        ((Number) manifestSource).longValue() != sourceTaxa.size()) {
    fail("Normalized source-taxonomy cardinality ${sourceTaxa.size()} does not " +
        "match manifest source_taxon_strings ${manifestSource}")
}
def missingMappings = sourceTaxa.findAll { !correctedTaxonomy.containsKey(it) }
def extraMappings = correctedTaxonomy.keySet().findAll { !sourceTaxa.contains(it) }
if (missingMappings || extraMappings) {
    fail("Corrected mapping coverage mismatch: ${missingMappings.size()} missing, " +
        "${extraMappings.size()} extra; first missing=" +
        "${missingMappings ? missingMappings.first() : 'none'}, first extra=" +
        "${extraMappings ? extraMappings.sort().first() : 'none'}")
}

// SRA run mappings are sorted before assignment to repeated profile columns.
def sampleToRuns = [:].withDefault { [] }
def runToSample = [:]
sraTsv.withReader("UTF-8") { reader ->
    CSVFormat.TDF.builder().setHeader().setSkipHeaderRecord(true).build()
        .parse(reader).each { record ->
            def sample = record.get("sample_name")?.trim()
            def run = record.get("run_accession")?.trim()
            if (sample && run) {
                if (runToSample.containsKey(run) && runToSample[run] != sample) {
                    fail("SRA run ${run} is assigned to both ${runToSample[run]} " +
                        "and ${sample}")
                }
                runToSample[run] = sample
                sampleToRuns[sample] << run
            }
        }
}
sampleToRuns.keySet().each { sample ->
    sampleToRuns[sample] = sampleToRuns[sample].unique().sort()
}

def fastqMap = [:]
// OWLAPI is retained only for this small, read-only lookup. The generated
// ~42-million-triple ABox itself is streamed below and is never materialised.
def lookupManager = OWLManager.createOWLOntologyManager()
def lookupLabel = lookupManager.getOWLDataFactory().getRDFSLabel()
def sraOnt = lookupManager.loadOntologyFromOntologyDocument(sraOntFile)
sraOnt.getIndividualsInSignature().each { ind ->
    EntitySearcher.getAnnotationObjects(ind, sraOnt, lookupLabel).each { ann ->
        def literal = ann.getValue().asLiteral()
        if (literal.isPresent()) {
            def label = literal.get().getLiteral()
            if (label.startsWith("FASTQ dataset for ")) {
                fastqMap[label.substring("FASTQ dataset for ".length())] = ind.getIRI()
            }
        }
    }
}
lookupManager.removeOntology(sraOnt)
lookupManager = null
sraOnt = null

/*
 * The submission sheet contains 26 sequenced controls that are intentionally
 * absent from the released FASTQ ontology: EB1--EB18, Negative1--Negative7
 * (where present), and T_Neg_Ctrl1--2. They must not become ABox processes,
 * and must not make smoke-mode selection choose an unavailable bearer.
 * Any missing non-control run remains a hard provenance error.
 */
def recognizedControlSample = { String sample ->
    sample ==~ /^(?:EB(?:[1-9]|1[0-8])|Negative[1-7]|T_Neg_Ctrl[12])$/
}
def runsWithoutFastq = runToSample.keySet()
    .findAll { !fastqMap.containsKey(it) }
    .sort()
def unexpectedMissingRuns = runsWithoutFastq.findAll {
    !recognizedControlSample(runToSample[it].toString())
}
if (unexpectedMissingRuns) {
    def firstRun = unexpectedMissingRuns.first()
    fail("SRA sheet run ${firstRun} for non-control sample " +
        "${runToSample[firstRun]} has no FASTQ individual in ${sraOntFile}")
}
if (runsWithoutFastq) {
    def excludedSamples = runsWithoutFastq.collect { runToSample[it] }.sort()
    System.err.println(
        "WARNING: excluding ${runsWithoutFastq.size()} recognized control runs " +
        "that are intentionally absent from the FASTQ ontology: " +
        excludedSamples.join(", ")
    )
}
sampleToRuns.keySet().toList().each { sample ->
    def available = sampleToRuns[sample].findAll { fastqMap.containsKey(it) }
    if (available) {
        sampleToRuns[sample] = available
    } else {
        sampleToRuns.remove(sample)
    }
}

/*
 * profile -> rank -> aggregation key -> record
 *
 * The key deliberately includes the corrected taxon IRI, the rank-truncated
 * canonical source lineage, and its terminal source label.  Thus two source
 * classifications that resolve to the same accepted taxon remain separate.
 * No global IRI-to-label or IRI-to-lineage map exists.
 */
def profileRankRecords = [:].withDefault {
    [:].withDefault { [:] }
}
def profileTotals = [:].withDefault { 0.0d }
def samples = []

featureTableFile.withReader("UTF-8") { reader ->
    // Avoid materialising the multi-gigabyte table merely to put back a
    // possible first header line. The actual header is far below this bound.
    reader.mark(16 * 1024 * 1024)
    def first = reader.readLine()
    if (first == null) {
        fail("${featureTableFile}: empty feature table")
    }
    if (first.startsWith("# Constructed")) {
        // The QIIME export comment is intentionally outside the TSV table.
    } else {
        reader.reset()
    }
    def table = CSVFormat.TDF.builder().setHeader().setSkipHeaderRecord(true).build()
        .parse(reader)
    samples = table.headerNames.findAll { it != "#OTU ID" }.sort()
    if (smallVersion) {
        // Controls and other non-SRA profiles may sort first. Smoke mode must
        // select profiles that can actually produce process records.
        samples = samples.findAll { profile ->
            sampleToRuns.containsKey(profile.tokenize("_").last())
        }.take(3)
        if (!samples) {
            fail("Small mode found no SRA-linked feature-table profiles")
        }
    }
    println("Mode: ${smallVersion ? 'SMALL' : 'FULL'} (${samples.size()} profiles)")

    table.each { record ->
        def feature = record.get("#OTU ID")?.trim()
        def taxon = featureToTaxon[feature]
        if (taxon == null) {
            fail("${featureTableFile}: feature ${feature} has no source taxonomy")
        }
        def mapping = correctedTaxonomy[taxon] as List
        if (mapping == null) {
            fail("${featureTableFile}: feature ${feature} lineage '${taxon}' is unmapped")
        }
        def segments = canonicalSegments[taxon] as List

        samples.each { profile ->
            def raw = record.get(profile)?.trim()
            double count
            try {
                count = raw ? Double.parseDouble(raw) : 0.0d
            } catch (NumberFormatException error) {
                fail("${featureTableFile}: non-numeric count '${raw}' for " +
                    "${feature}/${profile}")
            }
            if (!Double.isFinite(count) || count < 0.0d) {
                fail("${featureTableFile}: invalid count '${raw}' for ${feature}/${profile}")
            }
            if (count > 0.0d) {
                profileTotals[profile] += count
                ranks.eachWithIndex { rank, int index ->
                    def row = mapping[index] as Map
                    def sourceLineage = segments.take(index + 1).join(";")
                    def terminalSourceLabel = segments[index]
                    def key = [row.iri.toString(), sourceLineage, terminalSourceLabel]
                    def existing = profileRankRecords[profile][rank][key]
                    if (existing == null) {
                        existing = [
                            iri: row.iri.toString(),
                            label: row.label.toString(),
                            sourceLineage: sourceLineage,
                            terminalSourceLabel: terminalSourceLabel,
                            count: 0.0d,
                        ]
                        profileRankRecords[profile][rank][key] = existing
                    } else if (existing.label != row.label.toString()) {
                        fail("Mapping '${taxon}' gives inconsistent labels for key ${key}")
                    }
                    existing.count = ((double) existing.count) + count
                }
            }
        }
    }
}

/*
 * Freeze each aggregation map as a sorted list once. All subsequent passes use
 * this identical order, which makes sequential identifiers and the emitted
 * bytes deterministic without retaining OWL axioms.
 */
profileRankRecords.keySet().sort().each { profile ->
    ranks.each { rank ->
        profileRankRecords[profile][rank] =
            profileRankRecords[profile][rank].values().toList().sort {
                left, right ->
                    int comparison = left.iri.toString() <=>
                        right.iri.toString()
                    if (comparison == 0) {
                        comparison = left.sourceLineage.toString() <=>
                            right.sourceLineage.toString()
                    }
                    if (comparison == 0) {
                        comparison = left.terminalSourceLabel.toString() <=>
                            right.terminalSourceLabel.toString()
                    }
                    comparison
            }
    }
}

/*
 * Build the small process plan separately from abundance records. Dedicated,
 * collision-free identifier ranges are retained for the complete streaming
 * validator:
 *   taxonomy process  RAK_P290001...
 *   taxonomy dataset  RAK_7740001...
 *   abundance value   RAK_V00000001...
 *   abundance quality RAK_Q00000001...
 */
def columnsPerSample = [:].withDefault { 0 }
profileRankRecords.keySet().sort().each { profile ->
    columnsPerSample[profile.tokenize("_").last()]++
}
def sampleUsageCount = [:].withDefault { 0 }
def processPlans = []
long nextProcess = 290001L
long nextDataset = 740001L
profileRankRecords.keySet().sort().each { profile ->
    def sampleName = profile.tokenize("_").last()
    def runs = sampleToRuns[sampleName]
    if (!runs) {
        System.err.println(
            "WARNING: no SRA run for profile ${profile} (sample ${sampleName}); " +
            "profile is not represented in the ABox"
        )
    } else {
        def targetRuns
        if (columnsPerSample[sampleName] == 1 && runs.size() > 1) {
            targetRuns = runs
        } else {
            int index = sampleUsageCount[sampleName]
            targetRuns = [index < runs.size() ? runs[index] : runs.last()]
            sampleUsageCount[sampleName]++
        }
        targetRuns.each { runAccession ->
            double total = (double) profileTotals[profile]
            if (!(total > 0.0d)) {
                fail("Profile ${profile} has a non-positive mapped-read denominator")
            }
            processPlans << [
                profile: profile,
                sampleName: sampleName,
                run: runAccession,
                fastqIri: fastqMap[runAccession].toString(),
                total: total,
                processNumber: nextProcess++,
                datasetStart: nextDataset,
            ]
            nextDataset += 14L
        }
    }
}
if (processPlans.isEmpty()) {
    fail("No SRA-linked positive profiles are available for ABox generation")
}

// RDF constants and serialization helpers.
def RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
def RDFS = "http://www.w3.org/2000/01/rdf-schema#"
def OWL = "http://www.w3.org/2002/07/owl#"
def XSD = "http://www.w3.org/2001/XMLSchema#"
def RDF_TYPE = RDF + "type"
def RDFS_LABEL = RDFS + "label"
def OWL_IMPORTS = OWL + "imports"
def OWL_ONTOLOGY = OWL + "Ontology"
def OWL_NAMED_INDIVIDUAL = OWL + "NamedIndividual"
def OWL_OBJECT_PROPERTY = OWL + "ObjectProperty"
def OWL_DATATYPE_PROPERTY = OWL + "DatatypeProperty"
def OWL_CLASS = OWL + "Class"
def XSD_DOUBLE = XSD + "double"

def HAS_ATTRIBUTE = SIO + "SIO_000008"
def IS_ATTRIBUTE_OF = SIO + "SIO_000011"
def HAS_MEMBER = SIO + "SIO_000059"
def IS_MEASUREMENT_VALUE_OF = SIO + "SIO_000215"
def HAS_MEASUREMENT_VALUE = SIO + "SIO_000216"
def HAS_OUTPUT = SIO + "SIO_000229"
def HAS_INPUT = SIO + "SIO_000230"
def IS_SPECIFIED_BY = SIO + "SIO_000339"
def RELATIVE_VALUE_PROPERTY = BASE + "RAK_2000020"
def LINEAGE_PROPERTY = BASE + "RAK_2000025"
def ABSOLUTE_VALUE_PROPERTY = BASE + "RAK_2000026"

def WORKFLOW_CLASS = BASE + "RAK_0000071"
def RELATIVE_QUALITY_CLASS = BASE + "RAK_0000072"
def RELATIVE_VALUE_CLASS = BASE + "RAK_0000073"
def ABSOLUTE_DATASET_CLASS = BASE + "RAK_0000074"
def RELATIVE_DATASET_CLASS = BASE + "RAK_0000075"
def ABSOLUTE_VALUE_CLASS = BASE + "RAK_0000076"
def ABSOLUTE_QUALITY_CLASS = BASE + "RAK_0000078"
def AMOUNT_QUALITY_CLASS = PATO + "0000070"
def CONCENTRATION_QUALITY_CLASS = PATO + "0000033"
def PROTOCOL_IRI = BASE + "RAK_L000012"
def ONTOLOGY_IRI = BASE + "rubalkhali_taxonomy_abox.owl"

def iriToken = { Object iri -> "<${iri}>" }
def literalToken = { Object value ->
    def escaped = value.toString()
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    "\"${escaped}\""
}
def doubleToken = { double value ->
    "\"${Double.toString(value)}\"^^<${XSD_DOUBLE}>"
}
def qIri = { long number -> BASE + String.format("RAK_Q%08d", number) }
def vIri = { long number -> BASE + String.format("RAK_V%08d", number) }
def pIri = { long number -> BASE + String.format("RAK_P%06d", number) }
def dIri = { long number -> BASE + String.format("RAK_7%06d", number) }
def lineageFor = { Object abundance ->
    abundance.sourceLineage.toString().split(";", -1).toList()
        .withIndex().collect { String segment, int index ->
            "${rankLabels[index]}: ${segment ?: 'NA'}"
        }.join("; ")
}

/*
 * One complete subject is always emitted contiguously. This permits the
 * constant-memory structural validator to check exact predicate cardinality
 * and reciprocal-link fingerprints while the generator retains only compact
 * abundance aggregations and bearer-to-quality integer lists.
 */
def temporaryOutput = File.createTempFile(
    outputFile.name + ".",
    ".tmp",
    outputFile.parentFile
)
try {
    def stream = new BufferedOutputStream(
        new FileOutputStream(temporaryOutput),
        8 * 1024 * 1024
    )
    def writer = new BufferedWriter(
        new OutputStreamWriter(stream, StandardCharsets.UTF_8),
        8 * 1024 * 1024
    )
    def triple = { String subject, String predicate, String objectToken ->
        writer.write("<")
        writer.write(subject)
        writer.write("> <")
        writer.write(predicate)
        writer.write("> ")
        writer.write(objectToken)
        writer.write(" .\n")
    }
    def endSubject = { writer.write("\n") }

    try {
        writer.write("# Deterministic streaming taxonomy ABox\n")
        writer.write("# Generated only from a checksum-verified corrected mapping\n\n")

        // Ontology header plus the declarations OWLAPI formerly synthesized.
        triple(ONTOLOGY_IRI, RDF_TYPE, iriToken(OWL_ONTOLOGY))
        triple(ONTOLOGY_IRI, OWL_IMPORTS, iriToken(importIriString))
        endSubject()
        [
            HAS_ATTRIBUTE,
            IS_ATTRIBUTE_OF,
            HAS_MEMBER,
            IS_MEASUREMENT_VALUE_OF,
            HAS_MEASUREMENT_VALUE,
            HAS_OUTPUT,
            HAS_INPUT,
            IS_SPECIFIED_BY,
        ].sort().each { property ->
            triple(property, RDF_TYPE, iriToken(OWL_OBJECT_PROPERTY))
            endSubject()
        }
        [
            RELATIVE_VALUE_PROPERTY,
            LINEAGE_PROPERTY,
            ABSOLUTE_VALUE_PROPERTY,
        ].sort().each { property ->
            triple(property, RDF_TYPE, iriToken(OWL_DATATYPE_PROPERTY))
            endSubject()
        }
        [
            WORKFLOW_CLASS,
            RELATIVE_QUALITY_CLASS,
            RELATIVE_VALUE_CLASS,
            ABSOLUTE_DATASET_CLASS,
            RELATIVE_DATASET_CLASS,
            ABSOLUTE_VALUE_CLASS,
            ABSOLUTE_QUALITY_CLASS,
            AMOUNT_QUALITY_CLASS,
            CONCENTRATION_QUALITY_CLASS,
        ].sort().each { owlClass ->
            triple(owlClass, RDF_TYPE, iriToken(OWL_CLASS))
            endSubject()
        }
        triple(PROTOCOL_IRI, RDF_TYPE, iriToken(OWL_NAMED_INDIVIDUAL))
        triple(
            PROTOCOL_IRI,
            RDFS_LABEL,
            literalToken("16S amplicon processing protocol")
        )
        endSubject()

        // Processes: output datasets are fixed consecutive ranges.
        processPlans.each { plan ->
            def processIri = pIri((long) plan.processNumber)
            triple(processIri, RDF_TYPE, iriToken(OWL_NAMED_INDIVIDUAL))
            triple(processIri, RDF_TYPE, iriToken(WORKFLOW_CLASS))
            (0L..<14L).each { offset ->
                triple(
                    processIri,
                    HAS_OUTPUT,
                    iriToken(dIri((long) plan.datasetStart + offset))
                )
            }
            triple(processIri, HAS_INPUT, iriToken(plan.fastqIri))
            triple(processIri, IS_SPECIFIED_BY, iriToken(PROTOCOL_IRI))
            triple(
                processIri,
                RDFS_LABEL,
                literalToken(
                    "16S amplicon processing of ${plan.sampleName} (${plan.run})"
                )
            )
            endSubject()
        }

        // Dataset blocks, including membership in absolute/relative parity.
        long datasetValueCursor = 1L
        processPlans.each { plan ->
            ranks.eachWithIndex { rank, int rankIndex ->
                def records = profileRankRecords[plan.profile][rank] as List
                long rankValueStart = datasetValueCursor
                long absoluteDatasetNumber =
                    (long) plan.datasetStart + rankIndex * 2L
                long relativeDatasetNumber = absoluteDatasetNumber + 1L
                def absoluteDatasetIri = dIri(absoluteDatasetNumber)
                def relativeDatasetIri = dIri(relativeDatasetNumber)
                def rankLabel = rankLabels[rankIndex]

                triple(
                    absoluteDatasetIri,
                    RDF_TYPE,
                    iriToken(OWL_NAMED_INDIVIDUAL)
                )
                triple(
                    absoluteDatasetIri,
                    RDF_TYPE,
                    iriToken(ABSOLUTE_DATASET_CLASS)
                )
                records.indices.each { int index ->
                    triple(
                        absoluteDatasetIri,
                        HAS_MEMBER,
                        iriToken(vIri(rankValueStart + index * 2L))
                    )
                }
                triple(
                    absoluteDatasetIri,
                    RDFS_LABEL,
                    literalToken(
                        "Taxon absolute abundance dataset for " +
                            "${plan.sampleName} (${rankLabel})"
                    )
                )
                endSubject()

                triple(
                    relativeDatasetIri,
                    RDF_TYPE,
                    iriToken(OWL_NAMED_INDIVIDUAL)
                )
                triple(
                    relativeDatasetIri,
                    RDF_TYPE,
                    iriToken(RELATIVE_DATASET_CLASS)
                )
                records.indices.each { int index ->
                    triple(
                        relativeDatasetIri,
                        HAS_MEMBER,
                        iriToken(vIri(rankValueStart + index * 2L + 1L))
                    )
                }
                triple(
                    relativeDatasetIri,
                    RDFS_LABEL,
                    literalToken(
                        "Taxon relative abundance dataset for " +
                            "${plan.sampleName} (${rankLabel})"
                    )
                )
                endSubject()
                datasetValueCursor += records.size() * 2L
            }
        }

        // Quality blocks, while building compact inverse bearer lists.
        def bearerQualities = [:].withDefault { [] }
        long qualityCursor = 1L
        long qualityValueCursor = 1L
        processPlans.each { plan ->
            ranks.each { rank ->
                (profileRankRecords[plan.profile][rank] as List).each {
                    abundance ->
                        long absoluteQualityNumber = qualityCursor++
                        long absoluteValueNumber = qualityValueCursor++
                        long relativeQualityNumber = qualityCursor++
                        long relativeValueNumber = qualityValueCursor++
                        def absoluteQualityIri = qIri(absoluteQualityNumber)
                        def relativeQualityIri = qIri(relativeQualityNumber)

                        triple(
                            absoluteQualityIri,
                            RDF_TYPE,
                            iriToken(OWL_NAMED_INDIVIDUAL)
                        )
                        triple(
                            absoluteQualityIri,
                            RDF_TYPE,
                            iriToken(ABSOLUTE_QUALITY_CLASS)
                        )
                        triple(
                            absoluteQualityIri,
                            RDF_TYPE,
                            iriToken(AMOUNT_QUALITY_CLASS)
                        )
                        triple(
                            absoluteQualityIri,
                            IS_ATTRIBUTE_OF,
                            iriToken(abundance.iri)
                        )
                        triple(
                            absoluteQualityIri,
                            IS_ATTRIBUTE_OF,
                            iriToken(plan.fastqIri)
                        )
                        triple(
                            absoluteQualityIri,
                            HAS_MEASUREMENT_VALUE,
                            iriToken(vIri(absoluteValueNumber))
                        )
                        endSubject()

                        triple(
                            relativeQualityIri,
                            RDF_TYPE,
                            iriToken(OWL_NAMED_INDIVIDUAL)
                        )
                        triple(
                            relativeQualityIri,
                            RDF_TYPE,
                            iriToken(RELATIVE_QUALITY_CLASS)
                        )
                        triple(
                            relativeQualityIri,
                            RDF_TYPE,
                            iriToken(CONCENTRATION_QUALITY_CLASS)
                        )
                        triple(
                            relativeQualityIri,
                            IS_ATTRIBUTE_OF,
                            iriToken(abundance.iri)
                        )
                        triple(
                            relativeQualityIri,
                            IS_ATTRIBUTE_OF,
                            iriToken(plan.fastqIri)
                        )
                        triple(
                            relativeQualityIri,
                            HAS_MEASUREMENT_VALUE,
                            iriToken(vIri(relativeValueNumber))
                        )
                        endSubject()

                        bearerQualities[abundance.iri.toString()] <<
                            absoluteQualityNumber
                        bearerQualities[abundance.iri.toString()] <<
                            relativeQualityNumber
                        bearerQualities[plan.fastqIri.toString()] <<
                            absoluteQualityNumber
                        bearerQualities[plan.fastqIri.toString()] <<
                            relativeQualityNumber
                }
            }
        }

        // Value blocks use the same frozen order and mapped-read denominator.
        long valueCursor = 1L
        long valueQualityCursor = 1L
        processPlans.each { plan ->
            ranks.eachWithIndex { rank, int rankIndex ->
                def rankLabel = rankLabels[rankIndex]
                (profileRankRecords[plan.profile][rank] as List).each {
                    abundance ->
                        long absoluteValueNumber = valueCursor++
                        long absoluteQualityNumber = valueQualityCursor++
                        long relativeValueNumber = valueCursor++
                        long relativeQualityNumber = valueQualityCursor++
                        def absoluteValueIri = vIri(absoluteValueNumber)
                        def relativeValueIri = vIri(relativeValueNumber)
                        double count = (double) abundance.count
                        def lineage = lineageFor(abundance)

                        triple(
                            absoluteValueIri,
                            RDF_TYPE,
                            iriToken(OWL_NAMED_INDIVIDUAL)
                        )
                        triple(
                            absoluteValueIri,
                            RDF_TYPE,
                            iriToken(ABSOLUTE_VALUE_CLASS)
                        )
                        triple(
                            absoluteValueIri,
                            IS_MEASUREMENT_VALUE_OF,
                            iriToken(qIri(absoluteQualityNumber))
                        )
                        triple(
                            absoluteValueIri,
                            LINEAGE_PROPERTY,
                            literalToken(lineage)
                        )
                        triple(
                            absoluteValueIri,
                            ABSOLUTE_VALUE_PROPERTY,
                            doubleToken(count)
                        )
                        triple(
                            absoluteValueIri,
                            RDFS_LABEL,
                            literalToken(
                                "Absolute abundance of ${abundance.label} in " +
                                    "${plan.sampleName} (${rankLabel})"
                            )
                        )
                        endSubject()

                        triple(
                            relativeValueIri,
                            RDF_TYPE,
                            iriToken(OWL_NAMED_INDIVIDUAL)
                        )
                        triple(
                            relativeValueIri,
                            RDF_TYPE,
                            iriToken(RELATIVE_VALUE_CLASS)
                        )
                        triple(
                            relativeValueIri,
                            IS_MEASUREMENT_VALUE_OF,
                            iriToken(qIri(relativeQualityNumber))
                        )
                        triple(
                            relativeValueIri,
                            LINEAGE_PROPERTY,
                            literalToken(lineage)
                        )
                        triple(
                            relativeValueIri,
                            RELATIVE_VALUE_PROPERTY,
                            doubleToken(count / (double) plan.total)
                        )
                        triple(
                            relativeValueIri,
                            RDFS_LABEL,
                            literalToken(
                                "Relative abundance of ${abundance.label} in " +
                                    "${plan.sampleName} (${rankLabel})"
                            )
                        )
                        endSubject()
                }
            }
        }

        // Group inverse links by bearer so every subject occurs exactly once.
        bearerQualities.keySet().sort().each { bearer ->
            triple(bearer, RDF_TYPE, iriToken(OWL_NAMED_INDIVIDUAL))
            (bearerQualities[bearer] as List).each { qualityNumber ->
                triple(
                    bearer,
                    HAS_ATTRIBUTE,
                    iriToken(qIri((long) qualityNumber))
                )
            }
            endSubject()
        }
        writer.flush()
    } finally {
        writer.close()
    }

    try {
        Files.move(
            temporaryOutput.toPath(),
            outputFile.toPath(),
            StandardCopyOption.ATOMIC_MOVE
        )
    } catch (AtomicMoveNotSupportedException ignored) {
        Files.move(temporaryOutput.toPath(), outputFile.toPath())
    }
} catch (Throwable error) {
    temporaryOutput.delete()
    throw error
}
println("Wrote ${outputFile} by deterministic streaming Turtle emission")
