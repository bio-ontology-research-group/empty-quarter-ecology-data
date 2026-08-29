@Grab(group='net.sourceforge.owlapi', module='owlapi-distribution', version='5.1.20')

import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import java.io.File
import java.text.SimpleDateFormat

/**
 * Script to generate Environmental Measurements ABox.
 * References terms from rubalkhali.owl.
 */

def BASE = "https://rubalkhali.science/kb/"
def SIO = "http://semanticscience.org/resource/"
def UO = "http://purl.obolibrary.org/obo/UO_"
def DCTERMS = "http://purl.org/dc/terms/"

def manager = OWLManager.createOWLOntologyManager()
def df = manager.getOWLDataFactory()

// 1. Load Site Mappings from sites.owl
def siteLabelToIri = [:]
def siteIriToLabel = [:]
def coordinateSites = []
def geoWktProperty = df.getOWLAnnotationProperty(
    IRI.create("http://www.opengis.net/ont/geosparql#asWKT")
)
def sitesFile = new File("data/processed/ontology/rubalkhali_sites.owl")
if (sitesFile.exists()) {
    println "Mapping site IRIs from sites.owl..."
    def sOnt = manager.loadOntologyFromOntologyDocument(sitesFile)
    sOnt.getIndividualsInSignature().each { ind ->
        sOnt.getAnnotationAssertionAxioms(ind.getIRI()).each { ax ->
            if (ax.getProperty().isLabel()) {
                def label = ax.getValue().asLiteral().get().getLiteral().trim()
                siteLabelToIri[label] = ind.getIRI()
                siteIriToLabel[ind.getIRI()] = label
                if (label.startsWith("Site ")) siteLabelToIri[label.substring(5)] = ind.getIRI()
            } else if (ax.getProperty() == geoWktProperty &&
                       ax.getValue().asLiteral().isPresent()) {
                def wkt = ax.getValue().asLiteral().get().getLiteral().trim()
                def match = wkt =~ /POINT\(([-+0-9.eE]+)\s+([-+0-9.eE]+)(?:\s+[-+0-9.eE]+)?\)/
                if (match.matches()) {
                    coordinateSites << [
                        iri: ind.getIRI(),
                        longitude: match[0][1].toDouble(),
                        latitude: match[0][2].toDouble()
                    ]
                }
            }
        }
    }
    manager.removeOntology(sOnt)
}

def getSiteIri = { siteId ->
    def cleanId = siteId.toString().replaceAll(/\.0$/, "").trim()
    return siteLabelToIri["Site ${cleanId}"] ?: siteLabelToIri[cleanId]
}
def getSiteIriByCoordinates = { latitude, longitude ->
    if (latitude == null || longitude == null) return null
    def candidates = coordinateSites.findAll {
        Math.abs(it.latitude - latitude.toDouble()) <= 1.0e-6 &&
        Math.abs(it.longitude - longitude.toDouble()) <= 1.0e-6
    }
    if (candidates.size() > 1) {
        throw new IllegalStateException(
            "Coordinate pair ${latitude},${longitude} resolves to " +
            "${candidates.size()} site individuals"
        )
    }
    return candidates ? candidates[0].iri : null
}
def getSiteIriByCoordinateText = { coordinateText ->
    def match = coordinateText.toString().trim() =~
        /([-+0-9.eE]+)\s*N?\s*,\s*([-+0-9.eE]+)\s*E?/
    if (!match.matches()) return null
    return getSiteIriByCoordinates(
        match[0][1].toDouble(),
        match[0][2].toDouble()
    )
}

def ontology = manager.createOntology(IRI.create(BASE + "rubalkhali_measurements.owl"))

// Properties (Referencing rubalkhali.owl)
def hasAttribute = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000008"))
def hasTarget = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000291"))
def hasOutput = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000229"))
def isOutputOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000232"))
def isMeasurementValueOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000215"))   // value -> quality (SIO-canonical)
def hasMeasurementValue  = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000216"))   // quality -> value (inverse)
def isAttributeOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000011"))
def hasUnit = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000221"))
def hasAgent = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000139"))
def hasParticipant = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000132"))
def existsAt = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000687"))
def isPartOf = df.getOWLObjectProperty(IRI.create(SIO + "SIO_000068"))

def hasTempValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000003"))
def hasPressValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000004"))
def hasHumValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000005"))
def hasTimeValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000006"))
def hasAnnualMeanTempValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000007"))
def hasAnnualPrecipValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000008"))
def hasAnnualRainValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000009"))
def hasStartTimeValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000010"))
def hasEndTimeValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000011"))

// Classes (Referencing rubalkhali.owl)
def siteVisitClass = df.getOWLClass(IRI.create(BASE + "RAK_0000003"))
def timeMeasurementClass = df.getOWLClass(IRI.create(SIO + "SIO_000391"))
def expeditionTeamClass = df.getOWLClass(IRI.create(BASE + "RAK_0000016"))
def expeditionClass = df.getOWLClass(IRI.create(BASE + "RAK_0000018"))
def tempMeasuringClass = df.getOWLClass(IRI.create(BASE + "RAK_0000006"))
def pressMeasuringClass = df.getOWLClass(IRI.create(BASE + "RAK_0000007"))
def humMeasuringClass = df.getOWLClass(IRI.create(BASE + "RAK_0000008"))
def annualMeasuringClass = df.getOWLClass(IRI.create(BASE + "RAK_0000009"))
def tempValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000010"))
def pressValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000011"))
def humValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000012"))
def annualMeanTempValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000013"))
def annualPrecipValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000014"))
def annualRainValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000015"))
def pajeroBarometerClass = df.getOWLClass(IRI.create(BASE + "RAK_0000004"))
def testoThermometerClass = df.getOWLClass(IRI.create(BASE + "RAK_0000005"))

// Individuals (Pre-defined or generated here as ABox)
def pajeroBarometer = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_D000001"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(pajeroBarometerClass, pajeroBarometer))
def testoThermometer = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_D000002"))
manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(testoThermometerClass, testoThermometer))

int visitCounter = 1; int measurementCounter = 1; int qualityCounter = 1; int timeCounter = 1; int processCounter = 1; int expeditionCounter = 1; int agentCounter = 1 
def rdfsLabel = df.getRDFSLabel()
def dcDescription = df.getOWLAnnotationProperty(IRI.create(DCTERMS + "description"))
def addLabel = { iri, label -> manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(iri, df.getOWLAnnotation(rdfsLabel, df.getOWLLiteral(label)))) }
def isDouble = { s -> try { s.toDouble(); return true } catch (e) { return false } }

def addMeasurement = { siteInd, parentVisitInd, teamInd, qualityClassIri, value, unitIri, processClass, deviceInd, dataProp, valueClass, label, description ->
    def mValInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", measurementCounter++)))
    def qualityInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", qualityCounter++)))
    def processInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(processClass, processInd))
    addLabel(processInd.getIRI(), "Measuring process for " + label)
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, processInd, teamInd))
    if (deviceInd) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasParticipant, processInd, deviceInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isPartOf, processInd, parentVisitInd))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLClass(IRI.create(qualityClassIri)), qualityInd))
    addLabel(qualityInd.getIRI(), "Quality: " + label)
    // SIO-canonical: value SIO_000215 quality, quality SIO_000216 value
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, mValInd, qualityInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMeasurementValue, qualityInd, mValInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, siteInd, qualityInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qualityInd, siteInd))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(valueClass, mValInd))
    try { manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(dataProp, mValInd, value.toDouble())) } catch (Exception e) {}
    if (unitIri) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, mValInd, df.getOWLNamedIndividual(IRI.create(unitIri))))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, mValInd, processInd))
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, processInd, mValInd))
    addLabel(mValInd.getIRI(), label)
    manager.addAxiom(ontology, df.getOWLAnnotationAssertionAxiom(mValInd.getIRI(), df.getOWLAnnotation(dcDescription, df.getOWLLiteral(description))))
    return processInd 
}

def tripTeams = [: ]
def tripExpeditions = [: ]
def trips = ["trip1-2023.tsv", "trip2-2023.tsv", "trip3-2024.tsv", "trip4-2024.tsv", "trip5-2025.tsv"]
def sdf = new SimpleDateFormat("dd/MM/yyyy")

// Exact-cell curation shared with the supplementary-table generator.  Raw
// field sheets remain unchanged; every moved or quarantined value must match a
// versioned ledger entry before it can affect the ABox.
def correctionFile = new File("data/metadata/samples/environmental_measurement_corrections.tsv")
if (!correctionFile.exists()) {
    throw new IllegalStateException("Missing environmental correction ledger: ${correctionFile}")
}
def correctionLines = correctionFile.readLines()
def correctionHeader = correctionLines[0].split("\t", -1)*.trim()
def requiredCorrectionColumns = [
    "source_file", "source_row", "site", "original_field", "original_value",
    "corrected_field", "corrected_value", "status", "rationale"
]
if (correctionHeader != requiredCorrectionColumns) {
    throw new IllegalStateException("Unexpected environmental correction-ledger schema")
}
def environmentalCorrections = [:]
correctionLines.drop(1).eachWithIndex { line, index ->
    if (!line.trim()) return
    def parts = line.split("\t", -1)
    if (parts.size() != correctionHeader.size()) {
        throw new IllegalStateException("Malformed correction-ledger row ${index + 2}")
    }
    def row = [:]
    correctionHeader.eachWithIndex { name, column -> row[name] = parts[column].trim() }
    def key = "${row.source_file}|${row.source_row}|${row.original_field}"
    if (environmentalCorrections.containsKey(key)) {
        throw new IllegalStateException("Duplicate environmental correction ${key}")
    }
    if (!(row.original_field in ["temperature", "pressure", "humidity", "date"]) ||
        !(row.corrected_field in ["temperature", "pressure", "humidity", "date"])) {
        throw new IllegalStateException("Unsupported environmental correction field in ${key}")
    }
    if (!(row.status.startsWith("confirmed_") || row.status.startsWith("quarantined_")) ||
        !row.rationale) {
        throw new IllegalStateException("Unreviewed environmental correction ${key}")
    }
    environmentalCorrections[key] = row
}
def usedEnvironmentalCorrections = [] as Set
def environmentalRanges = [
    temperature: [-50.0d, 60.0d],
    pressure: [800.0d, 1100.0d],
    humidity: [0.0d, 100.0d]
]
def validateEnvironmentalValue = { field, value, context ->
    if (!value) return
    if (!isDouble(value)) {
        throw new IllegalStateException("${context}: non-numeric ${field} ${value}")
    }
    def numeric = value.toDouble()
    def limits = environmentalRanges[field]
    if (numeric < limits[0] || numeric > limits[1]) {
        throw new IllegalStateException(
            "${context}: ${field} ${value} outside ${limits}"
        )
    }
}

trips.each { filename ->
    def file = new File("data/metadata/samplesheets", filename)
    if (!file.exists()) return
    def lines = file.readLines(); if (lines.size() < 2) return
    def header = lines[0].split("\t", -1)
    def colDate = header.findIndexOf { it.trim().equalsIgnoreCase("date") }
    def dates = []
    def expectedYear = (filename =~ /-(\d{4})\.tsv$/)[0][1]
    def dateSiteColumn = header.findIndexOf { it.trim().equalsIgnoreCase("site") }
    lines.drop(1).eachWithIndex { line, rowIndex ->
        def parts = line.split("\t", -1)
        if (parts.size() <= Math.max(colDate, dateSiteColumn)) return
        def rawDate = parts[colDate].trim()
        def site = parts[dateSiteColumn].trim()
        if (!rawDate || !site) return
        def dateKey = "${filename}|${rowIndex + 2}|date"
        def dateCorrection = environmentalCorrections[dateKey]
        def curatedDate = rawDate
        if (dateCorrection) {
            if (dateCorrection.site != site || dateCorrection.original_value != rawDate) {
                throw new IllegalStateException(
                    "${dateKey}: correction ledger does not match source cell"
                )
            }
            curatedDate = dateCorrection.corrected_value
        }
        try {
            def parsedDate = sdf.parse(curatedDate)
            if (new SimpleDateFormat("yyyy").format(parsedDate) == expectedYear) {
                dates << parsedDate
            }
        } catch(e) {
            throw new IllegalStateException(
                "${filename}:${rowIndex + 2}: invalid curated date ${curatedDate}"
            )
        }
    }
    def startDate = dates ? new SimpleDateFormat("yyyy-MM-dd").format(dates.min()) : null
    def endDate = dates ? new SimpleDateFormat("yyyy-MM-dd").format(dates.max()) : null
    def expName = filename.replace("-", " ").replace(".tsv", "").capitalize()
    def expInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_E" + String.format("%06d", expeditionCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(expeditionClass, expInd))
    addLabel(expInd.getIRI(), expName)
    tripExpeditions[filename.split("-")[0]] = expInd
    def teamInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_A" + String.format("%06d", agentCounter++)))
    manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(expeditionTeamClass, teamInd))
    addLabel(teamInd.getIRI(), "${expName} Team")
    manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, expInd, teamInd))
    tripTeams[filename.split("-")[0]] = teamInd
    if (startDate || endDate) {
        def timeInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_T" + String.format("%06d", timeCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(timeMeasurementClass, timeInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(existsAt, expInd, timeInd))
        if (startDate) manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasStartTimeValue, timeInd, startDate))
        if (endDate) manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasEndTimeValue, timeInd, endDate))
    }
    def colSite = header.findIndexOf { it.trim().equalsIgnoreCase("site") }
    def colTime = header.findIndexOf { it.trim().equalsIgnoreCase("time") }
    def colCoordinates = header.findIndexOf {
        it.trim().equalsIgnoreCase("coordinates") ||
        it.trim().equalsIgnoreCase("gps")
    }
    def colTemp = header.findIndexOf { it.trim().equalsIgnoreCase("temperature") }
    def colPress = header.findIndexOf { it.trim().equalsIgnoreCase("pressure") }
    def colHum = header.findIndexOf { it.trim().equalsIgnoreCase("humidity") }

    lines.drop(1).eachWithIndex { line, rowIndex ->
        def sourceRow = rowIndex + 2
        def parts = line.split("\t", -1)
        if (!parts.any { it.trim() } || parts.size() <= colSite) return
        def site = parts[colSite].trim()
        def values = [
            temperature: (colTemp != -1 && parts.size() > colTemp) ? parts[colTemp].trim() : "",
            pressure: (colPress != -1 && parts.size() > colPress) ? parts[colPress].trim() : "",
            humidity: (colHum != -1 && parts.size() > colHum) ? parts[colHum].trim() : "",
            date: (colDate != -1 && parts.size() > colDate) ? parts[colDate].trim() : ""
        ]
        ["temperature", "pressure", "humidity", "date"].each { originalField ->
            def key = "${filename}|${sourceRow}|${originalField}"
            def correction = environmentalCorrections[key]
            if (!correction) return
            if (correction.site != site || correction.original_value != values[originalField]) {
                throw new IllegalStateException(
                    "${key}: correction ledger does not match source cell"
                )
            }
            def correctedField = correction.corrected_field
            if (correctedField != originalField && values[correctedField] &&
                values[correctedField] != correction.corrected_value) {
                throw new IllegalStateException(
                    "${key}: corrected field ${correctedField} is already populated"
                )
            }
            values[originalField] = ""
            values[correctedField] = correction.corrected_value
            usedEnvironmentalCorrections << key
        }
        ["temperature", "pressure", "humidity"].each { field ->
            validateEnvironmentalValue(field, values[field], "${filename}:${sourceRow} site ${site}")
        }

        def coordinateText =
            (colCoordinates != -1 && parts.size() > colCoordinates) ?
            parts[colCoordinates].trim() : ""
        def isAuxiliaryRecord =
            filename == "trip3-2024.tsv" && values.date.endsWith("/2023")
        // Coordinate fallback is limited to primary field-log records.  The
        // 15 appended Trip-1 auxiliary/revisit rows describe offset or
        // special-purpose locations (for example "47+grass" and "52AD").
        // Their coordinates may coincide with a catalogue site without
        // establishing identity.  Only an exact site label may connect such
        // a row to the graph; the other rows remain available in the curated
        // table without being silently attached to a catalogue site.
        def siteIri = getSiteIri(site)
        if (!siteIri && !isAuxiliaryRecord) {
            siteIri = getSiteIriByCoordinateText(coordinateText)
        }
        if (!siteIri) return
        def siteInd = df.getOWLNamedIndividual(siteIri)
        def canonicalSiteLabel =
            siteIriToLabel[siteIri] ?: "Site ${parts[colSite]}"
        def effectiveTripKey =
            isAuxiliaryRecord ? "trip1" : filename.split("-")[0]
        def effectiveExpInd = tripExpeditions[effectiveTripKey]
        def effectiveTeamInd = tripTeams[effectiveTripKey]
        if (!effectiveExpInd || !effectiveTeamInd) {
            throw new IllegalStateException(
                "${filename}:${sourceRow}: no expedition for ${effectiveTripKey}"
            )
        }
        def effectiveExpName =
            effectiveTripKey == "trip1" ? "Trip1 2023" : expName
        def dateStr = values.date ?: "Unknown Date"
        def dateStrIso =
            dateStr == "Unknown Date" ?
            dateStr :
            dateStr.split("/").reverse().join("-")
        def timeStr = (colTime != -1 && parts.size() > colTime) ? parts[colTime].trim() : "00:00"
        def visitInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_3" + String.format("%06d", visitCounter++)))
        manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(siteVisitClass, visitInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasTarget, visitInd, siteInd))
        manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isPartOf, visitInd, effectiveExpInd))
        addLabel(visitInd.getIRI(), "Visit to ${canonicalSiteLabel} during ${effectiveExpName} on ${dateStrIso} ${timeStr}")
        if (dateStr != "Unknown Date") {
            def vTimeInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_T" + String.format("%06d", timeCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(timeMeasurementClass, vTimeInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(existsAt, visitInd, vTimeInd))
            manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasTimeValue, vTimeInd, dateStrIso + "T" + timeStr))
        }
        if (values.temperature) addMeasurement(siteInd, visitInd, effectiveTeamInd, "http://purl.obolibrary.org/obo/PATO_0000146", values.temperature, UO + "0000027", tempMeasuringClass, testoThermometer, hasTempValue, tempValueClass, "Temperature for ${canonicalSiteLabel}", "Surface temperature.")
        if (values.pressure) {
            // Field sheets record atmospheric pressure in mbar/hPa. The
            // asserted UO_0000110 unit is pascal, so convert before minting
            // the RDF value.
            def pressurePascals = values.pressure.toDouble() * 100.0d
            addMeasurement(siteInd, visitInd, effectiveTeamInd, "http://purl.obolibrary.org/obo/PATO_0001025", pressurePascals, UO + "0000110", pressMeasuringClass, pajeroBarometer, hasPressValue, pressValueClass, "Pressure for ${canonicalSiteLabel}", "Atmospheric pressure converted from source millibars (hectopascals) to pascals.")
        }
        if (values.humidity) addMeasurement(siteInd, visitInd, effectiveTeamInd, "http://purl.obolibrary.org/obo/PATO_0015009", values.humidity, UO + "0000187", humMeasuringClass, null, hasHumValue, humValueClass, "Humidity for ${canonicalSiteLabel}", "Relative humidity.")
    }
}
def unusedEnvironmentalCorrections =
    (environmentalCorrections.keySet() as Set) - usedEnvironmentalCorrections
if (unusedEnvironmentalCorrections) {
    throw new IllegalStateException(
        "Unused environmental correction-ledger entries: ${unusedEnvironmentalCorrections.sort()}"
    )
}

// 2. Geodata
new File("data/metadata/geodata").listFiles()
    .findAll { file -> file.name ==~ /trip[1-5]_geodata\.tsv/ }
    .sort { first, second -> first.name <=> second.name }
    .each { file ->
    def tripKey = file.name.split("_")[0]; def teamInd = tripTeams[tripKey]; def lines = file.readLines(); if (lines.isEmpty()) return
    def header = lines[0].split("\t")
    def colSite = header.findIndexOf { it.trim().equalsIgnoreCase("site") }
    def colLatitude = header.findIndexOf { it.trim().equalsIgnoreCase("latitude") }
    def colLongitude = header.findIndexOf { it.trim().equalsIgnoreCase("longitude") }
    def colMeanTemp = header.findIndexOf { it.trim().equalsIgnoreCase("AnnualMeanTemp") }
    def colTotalPrecip = header.findIndexOf { it.trim().equalsIgnoreCase("AnnualTotalPrecip") }
    def colTotalRain = header.findIndexOf { it.trim().equalsIgnoreCase("AnnualTotalRain") }
    def colStart = header.findIndexOf { it.trim().equalsIgnoreCase("StartDate") }
    def colEnd = header.findIndexOf { it.trim().equalsIgnoreCase("EndDate") }
    lines.drop(1).each { line ->
        def parts = line.split("\t"); if (parts.size() <= colSite) return
        def latitude =
            (colLatitude != -1 && parts.size() > colLatitude &&
             isDouble(parts[colLatitude].trim())) ?
            parts[colLatitude].trim().toDouble() : null
        def longitude =
            (colLongitude != -1 && parts.size() > colLongitude &&
             isDouble(parts[colLongitude].trim())) ?
            parts[colLongitude].trim().toDouble() : null
        // Annual climate records are keyed by the field-notebook Site value.
        // Do not use a coordinate fallback here: labels such as "47+grass"
        // are explicitly quarantined because their offset from Site 47 was
        // never recorded. Coordinate fallback would silently attach them to
        // the stem site and contradict the climate-key ledger.
        def siteIri = getSiteIri(parts[colSite].trim())
        if (!siteIri) return
        def siteInd = df.getOWLNamedIndividual(siteIri)
        def startDate = (colStart != -1 && parts.size() > colStart) ? parts[colStart].trim() : ""
        def endDate = (colEnd != -1 && parts.size() > colEnd) ? parts[colEnd].trim() : ""
        def annualTimeInd = null
        if (startDate || endDate) {
            annualTimeInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_T" + String.format("%06d", timeCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(timeMeasurementClass, annualTimeInd))
            if (startDate) manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasStartTimeValue, annualTimeInd, startDate))
            if (endDate) manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasEndTimeValue, annualTimeInd, endDate))
        }
        def addAnnualM = { qualityClass, value, unit, prop, vClass, lbl ->
            def mValInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", measurementCounter++)))
            def qualityInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", qualityCounter++)))
            def processInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(annualMeasuringClass, processInd))
            addLabel(processInd.getIRI(), "Measuring process for " + lbl)
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasTarget, processInd, siteInd))
            if (teamInd) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAgent, processInd, teamInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, siteInd, qualityInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qualityInd, siteInd))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLClass(IRI.create(qualityClass)), qualityInd))
            // SIO-canonical: value SIO_000215 quality, quality SIO_000216 value
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, mValInd, qualityInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMeasurementValue, qualityInd, mValInd))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(vClass, mValInd))
            try { manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(prop, mValInd, value.toDouble())) } catch(e){}
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, mValInd, df.getOWLNamedIndividual(IRI.create(unit))))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, mValInd, processInd))
            manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, processInd, mValInd))
            if (annualTimeInd) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, processInd, annualTimeInd))
            addLabel(mValInd.getIRI(), lbl)
        }
        def interval = (startDate || endDate) ? " (${startDate} to ${endDate})" : ""
        if (colMeanTemp != -1 && parts.size() > colMeanTemp && parts[colMeanTemp].trim() && isDouble(parts[colMeanTemp].trim())) addAnnualM("http://purl.obolibrary.org/obo/PATO_0000146", parts[colMeanTemp], UO + "0000027", hasAnnualMeanTempValue, annualMeanTempValueClass, "Annual Mean Temperature Value for Site ${parts[colSite]}${interval}")
        if (colTotalPrecip != -1 && parts.size() > colTotalPrecip && parts[colTotalPrecip].trim() && isDouble(parts[colTotalPrecip].trim())) addAnnualM("http://purl.obolibrary.org/obo/ENVO_00002005", parts[colTotalPrecip], UO + "0000016", hasAnnualPrecipValue, annualPrecipValueClass, "Annual Total Precipitation Value for Site ${parts[colSite]}${interval}")
        if (colTotalRain != -1 && parts.size() > colTotalRain && parts[colTotalRain].trim() && isDouble(parts[colTotalRain].trim())) addAnnualM("http://purl.obolibrary.org/obo/ENVO_00002005", parts[colTotalRain], UO + "0000016", hasAnnualRainValue, annualRainValueClass, "Annual Total Rain Value for Site ${parts[colSite]}${interval}")
    }
}

// 3. Monthly Weather Averages
def monthlyFile = new File("data/processed/climate/monthly_weather_averages.tsv")
if (monthlyFile.exists()) {
    println "Processing monthly weather averages..."
    def lines = monthlyFile.readLines()
    if (lines.size() > 1) {
        def header = lines[0].split("\t")
        def colSite = header.findIndexOf { it.trim().equalsIgnoreCase("Site") }
        def colYear = header.findIndexOf { it.trim().equalsIgnoreCase("Year") }
        def colMonth = header.findIndexOf { it.trim().equalsIgnoreCase("Month") }
        def colTemp = header.findIndexOf { it.trim().equalsIgnoreCase("Avg_Temp_C") }
        def colPrecip = header.findIndexOf { it.trim().equalsIgnoreCase("Avg_Total_Precip_mm") }
        def colRain = header.findIndexOf { it.trim().equalsIgnoreCase("Avg_Total_Rain_mm") }
        def colHum = header.findIndexOf { it.trim().equalsIgnoreCase("Avg_Humidity_Percent") }

        // New Classes and Properties for Monthly Data
        def monthlyMeasuringClass = df.getOWLClass(IRI.create(BASE + "RAK_0000034"))
        def monthlyMeanTempValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000035"))
        def monthlyPrecipValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000036"))
        def monthlyRainValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000037"))
        def monthlyHumValueClass = df.getOWLClass(IRI.create(BASE + "RAK_0000038"))

        def hasMonthlyMeanTempValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000021"))
        def hasMonthlyPrecipValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000022"))
        def hasMonthlyRainValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000023"))
        def hasMonthlyHumValue = df.getOWLDataProperty(IRI.create(BASE + "RAK_2000024"))

        lines.drop(1).each { line ->
            def parts = line.split("\t")
            if (parts.size() <= colSite) return
            def siteIri = getSiteIri(parts[colSite].trim())
            if (!siteIri) return
            def siteInd = df.getOWLNamedIndividual(siteIri)

            def year = parts[colYear].trim().toInteger()
            def month = parts[colMonth].trim().toInteger()
            
            // Construct Time Individual
            def cal = Calendar.instance
            cal.set(year, month - 1, 1)
            def startStr = new SimpleDateFormat("yyyy-MM-dd").format(cal.time)
            cal.set(Calendar.DAY_OF_MONTH, cal.getActualMaximum(Calendar.DAY_OF_MONTH))
            def endStr = new SimpleDateFormat("yyyy-MM-dd").format(cal.time)

            def monthTimeInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_T" + String.format("%06d", timeCounter++)))
            manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(timeMeasurementClass, monthTimeInd))
            manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasStartTimeValue, monthTimeInd, startStr))
            manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(hasEndTimeValue, monthTimeInd, endStr))

            def addMonthlyM = { qualityClass, value, unit, prop, vClass, lbl ->
                def mValInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_4" + String.format("%06d", measurementCounter++)))
                def qualityInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_5" + String.format("%06d", qualityCounter++)))
                def processInd = df.getOWLNamedIndividual(IRI.create(BASE + "RAK_P" + String.format("%06d", processCounter++)))
                
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(monthlyMeasuringClass, processInd))
                addLabel(processInd.getIRI(), "Measuring process for " + lbl)
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasTarget, processInd, siteInd))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, processInd, monthTimeInd)) // Bind time to process
                
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasAttribute, siteInd, qualityInd))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isAttributeOf, qualityInd, siteInd))
                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(df.getOWLClass(IRI.create(qualityClass)), qualityInd))
                // SIO-canonical: value SIO_000215 quality, quality SIO_000216 value
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isMeasurementValueOf, mValInd, qualityInd))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasMeasurementValue, qualityInd, mValInd))

                manager.addAxiom(ontology, df.getOWLClassAssertionAxiom(vClass, mValInd))
                try { manager.addAxiom(ontology, df.getOWLDataPropertyAssertionAxiom(prop, mValInd, value.toDouble())) } catch(e){}
                if (unit) manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasUnit, mValInd, df.getOWLNamedIndividual(IRI.create(unit))))
                
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(isOutputOf, mValInd, processInd))
                manager.addAxiom(ontology, df.getOWLObjectPropertyAssertionAxiom(hasOutput, processInd, mValInd))
                addLabel(mValInd.getIRI(), lbl)
            }

            if (colTemp != -1 && parts[colTemp].trim() && isDouble(parts[colTemp].trim())) 
                addMonthlyM("http://purl.obolibrary.org/obo/PATO_0000146", parts[colTemp], UO + "0000027", hasMonthlyMeanTempValue, monthlyMeanTempValueClass, "Monthly Mean Temperature for Site ${parts[colSite]} (${month}/${year})")
            
            if (colPrecip != -1 && parts[colPrecip].trim() && isDouble(parts[colPrecip].trim())) 
                addMonthlyM("http://purl.obolibrary.org/obo/ENVO_00002005", parts[colPrecip], UO + "0000016", hasMonthlyPrecipValue, monthlyPrecipValueClass, "Monthly Total Precipitation for Site ${parts[colSite]} (${month}/${year})")
            
            if (colRain != -1 && parts[colRain].trim() && isDouble(parts[colRain].trim())) 
                addMonthlyM("http://purl.obolibrary.org/obo/ENVO_00002005", parts[colRain], UO + "0000016", hasMonthlyRainValue, monthlyRainValueClass, "Monthly Total Rain for Site ${parts[colSite]} (${month}/${year})")
                
            if (colHum != -1 && parts[colHum].trim() && isDouble(parts[colHum].trim())) 
                addMonthlyM("http://purl.obolibrary.org/obo/PATO_0015009", parts[colHum], UO + "0000187", hasMonthlyHumValue, monthlyHumValueClass, "Monthly Mean Humidity for Site ${parts[colSite]} (${month}/${year})")
        }
    }
}
manager.saveOntology(ontology, IRI.create(new File("data/processed/ontology/rubalkhali_measurements.owl").toURI()))
println "Success: Generated rubalkhali_measurements.owl using centralized TBox."
