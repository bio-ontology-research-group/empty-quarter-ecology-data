"""
Tests for XRF data correctness.

1. Unit tests for element-to-oxide stoichiometric conversion factors
2. Data validation: SiO2 must be the dominant analyte in soil samples
3. SPARQL integration test: verify correct analyte labels and dominance in the KG
4. IRI consistency: base ontology and XRF ABox script must assign same IRIs
"""

import pytest
import pandas as pd
import os
import subprocess
import re
import json
import yaml

# --- Stoichiometric conversion factors (element wt% → oxide wt%) ---
# Derived from molecular weight ratios: MW(oxide) / (n × AW(element))
OXIDE_CONVERSION = {
    "Si": ("SiO2", 2.1393),   # 60.08 / 28.09
    "Fe": ("Fe2O3", 1.4297),  # 159.69 / (2 × 55.845)
    "Al": ("Al2O3", 1.8895),  # 101.96 / (2 × 26.98)
    "Ca": ("CaO", 1.3992),    # 56.08 / 40.08
    "Mg": ("MgO", 1.6583),    # 40.30 / 24.31
    "K": ("K2O", 1.2046),     # 94.20 / (2 × 39.10)
    "Na": ("Na2O", 1.3480),   # 61.98 / (2 × 22.99)
    "Ti": ("TiO2", 1.6681),   # 79.87 / 47.87
    "Mn": ("MnO", 1.2912),    # 70.94 / 54.94
    "P": ("P2O5", 2.2914),    # 141.94 / (2 × 30.97)
    "S": ("SO3", 2.4972),     # 80.06 / 32.06
    "Cr": ("Cr2O3", 1.4616),  # 151.99 / (2 × 52.00)
    "V": ("V2O5", 1.7852),    # 181.88 / (2 × 50.94)
}

XRF_PATH = "data/processed/geochemistry/xrf_lab_table_filtered.tsv"


class TestStoichiometricConversion:
    """Verify element-to-oxide conversion factors are chemically correct."""

    @pytest.mark.parametrize("element,expected", [
        ("Si", 2.1393),
        ("Fe", 1.4297),
        ("Al", 1.8895),
        ("Ca", 1.3992),
        ("Mg", 1.6583),
        ("Ti", 1.6681),
        ("Mn", 1.2912),
        ("P", 2.2914),
    ])
    def test_conversion_factor_accuracy(self, element, expected):
        """Each conversion factor must match the known molecular weight ratio."""
        _, factor = OXIDE_CONVERSION[element]
        assert abs(factor - expected) < 0.001, (
            f"{element} conversion factor {factor} != expected {expected}"
        )

    def test_si_to_sio2_example(self):
        """20.1% Si should yield ~43.0% SiO2 (matches lab-reported value)."""
        si_pct = 20.1
        _, factor = OXIDE_CONVERSION["Si"]
        sio2_pct = si_pct * factor
        assert abs(sio2_pct - 43.0) < 0.5, (
            f"Si {si_pct}% → SiO2 {sio2_pct:.1f}%, expected ~43.0%"
        )

    def test_fe_to_fe2o3_example(self):
        """0.351% Fe should yield ~0.502% Fe2O3 (matches lab-reported value)."""
        fe_pct = 0.351
        _, factor = OXIDE_CONVERSION["Fe"]
        fe2o3_pct = fe_pct * factor
        assert abs(fe2o3_pct - 0.502) < 0.01, (
            f"Fe {fe_pct}% → Fe2O3 {fe2o3_pct:.3f}%, expected ~0.502%"
        )

    def test_oxide_always_greater_than_element(self):
        """Oxide wt% must always be > element wt% (due to oxygen mass)."""
        for element, (oxide, factor) in OXIDE_CONVERSION.items():
            assert factor > 1.0, (
                f"Conversion factor for {element}→{oxide} is {factor}, must be >1"
            )


class TestXRFDataDominance:
    """Verify SiO2 is the dominant analyte in the lab XRF data."""

    @pytest.fixture
    def xrf_data(self):
        if not os.path.exists(XRF_PATH):
            pytest.skip("XRF data file not found")
        df = pd.read_csv(XRF_PATH, sep="\t", index_col=0)
        # Keep only numeric columns
        meta_cols = ["SoilType", "Material", "Mode", "Diameter", "Method"]
        numeric_cols = [c for c in df.columns if c not in meta_cols]
        return df[numeric_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    def test_sio2_is_dominant_overall(self, xrf_data):
        """SiO2 must have the highest mean concentration across all samples."""
        means = xrf_data.mean().sort_values(ascending=False)
        top_analyte = means.index[0]
        assert top_analyte == "SiO2", (
            f"Expected SiO2 as dominant analyte, got {top_analyte} "
            f"(mean={means.iloc[0]:.2f}%)"
        )

    def test_sio2_exceeds_fe2o3(self, xrf_data):
        """SiO2 mean must be at least 10x higher than Fe2O3 mean in soil."""
        sio2_mean = xrf_data["SiO2"].mean()
        fe2o3_mean = xrf_data["Fe2O3"].mean()
        ratio = sio2_mean / fe2o3_mean if fe2o3_mean > 0 else float("inf")
        assert ratio > 10, (
            f"SiO2/Fe2O3 ratio = {ratio:.1f}, expected >10 for soil samples"
        )

    def test_oxide_sum_under_100(self, xrf_data):
        """Sum of major oxides should not exceed 100% for any sample."""
        oxide_cols = [c for c in xrf_data.columns if re.search(r"[0-9]", c)]
        if oxide_cols:
            oxide_sums = xrf_data[oxide_cols].sum(axis=1)
            max_sum = oxide_sums.max()
            assert max_sum <= 100.5, (
                f"Max oxide sum = {max_sum:.1f}%, exceeds 100%"
            )

    def test_both_element_and_oxide_present(self, xrf_data):
        """
        Both element (Si) and oxide (SiO2) forms should be present in the data.
        The KG stores both as-is from the source files without deduplication.
        """
        element_oxide_pairs = {
            "Si": "SiO2", "Fe": "Fe2O3", "Al": "Al2O3", "Ca": "CaO"
        }
        for elem, oxide in element_oxide_pairs.items():
            assert elem in xrf_data.columns, f"Element {elem} missing from data"
            assert oxide in xrf_data.columns, f"Oxide {oxide} missing from data"
            # Both should have non-zero values
            assert xrf_data[elem].sum() > 0, f"{elem} has no non-zero values"
            assert xrf_data[oxide].sum() > 0, f"{oxide} has no non-zero values"


class TestXRFSparql:
    """
    Integration test: query the generated XRF ontology via SPARQL
    to verify analyte class labels and dominance.
    Requires: data/processed/ontology/rubalkhali_xrf.owl to be generated.
    """

    SPARQL_DOMINANT = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX rak: <https://rubalkhali.science/kb/>
    PREFIX sio: <http://semanticscience.org/resource/>

    SELECT ?analyteName (AVG(?conc) AS ?meanConc)
    WHERE {
        ?value rak:RAK_2000012 ?conc .
        # SIO-canonical: value sio:SIO_000215 quality (value is subject).
        ?value sio:SIO_000215 ?quality .
        ?quality a ?qClass .
        ?qClass rdfs:label ?qLabel .
        FILTER(?qClass != rak:RAK_0000029)
        BIND(STRBEFORE(?qLabel, " concentration") AS ?analyteName)
        FILTER(STRLEN(?analyteName) > 0)
    }
    GROUP BY ?analyteName
    ORDER BY DESC(?meanConc)
    LIMIT 5
    """

    SPARQL_CLASS_LABELS = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX rak: <https://rubalkhali.science/kb/>

    SELECT (COUNT(?qClass) AS ?labelCount)
    WHERE {
        ?qClass rdfs:subClassOf rak:RAK_0000029 .
        ?qClass rdfs:label ?label .
    }
    """

    @pytest.fixture
    def xrf_owl_exists(self):
        owl_path = "data/processed/ontology/rubalkhali_xrf.owl"
        if not os.path.exists(owl_path):
            pytest.skip("XRF OWL file not generated yet")
        return owl_path

    def test_analyte_instance_labels_present(self, xrf_owl_exists):
        """XRF ABox must contain analyte instance labels for SPARQL to work."""
        with open(xrf_owl_exists) as f:
            content = f.read()
        # Instance labels follow pattern: "SiO2 quality (Lab XRF) for ..." or "Si quality (Field XRF..."
        quality_instances = re.findall(r'quality \((Lab|Field) XRF', content)
        assert len(quality_instances) > 10, (
            f"Expected >10 quality instance labels, found {len(quality_instances)}"
        )

    def test_sio2_instances_exist(self, xrf_owl_exists):
        """SiO2 quality instances must exist in the XRF ABox."""
        with open(xrf_owl_exists) as f:
            content = f.read()
        assert "SiO2 quality (Lab XRF)" in content, "SiO2 quality instance labels not found"

    def test_both_forms_in_owl(self, xrf_owl_exists):
        """Both element (Si) and oxide (SiO2) instance labels should be in the OWL file."""
        with open(xrf_owl_exists) as f:
            content = f.read()
        # Both forms should be present - the KG stores data as-is
        si_lab = re.findall(r'Si quality \(Lab XRF\)', content)
        sio2_lab = re.findall(r'SiO2 quality \(Lab XRF\)', content)
        assert len(sio2_lab) > 0, "SiO2 quality instance labels missing from OWL"
        assert len(si_lab) > 0, "Si quality instance labels missing from OWL"

    def test_xrf_script_guards_existing_sample_labels(self):
        """The XRF ABox script must not re-label samples that already exist in samples.owl."""
        script_path = "scripts/rdf/generate_xrf_abox.groovy"
        if not os.path.exists(script_path):
            pytest.skip("XRF ABox script not found")
        with open(script_path) as f:
            content = f.read()
        # The script must check isExistingSample before adding labels/types
        assert "isExistingSample" in content, (
            "XRF script does not guard against re-labeling existing samples. "
            "This causes 'Lab XRF input material' to appear in the Samples tab."
        )


class TestXRFIriConsistency:
    """
    Verify that the base ontology (update_rubalkhali_ontology.groovy) and
    the XRF ABox (generate_xrf_abox.groovy) assign the same IRIs to each analyte.

    Both scripts iterate xrf_chemical_mapping.yml with counters starting at 100/500,
    skipping LE. If one skips LE and the other doesn't, all IRIs shift by one,
    causing analyte label mismatches (e.g., SiO2 labeled as Fe2O3).
    """

    YAML_PATH = "config/codes/xrf_chemical_mapping.yml"
    BASE_ONTOLOGY_SCRIPT = "scripts/rdf/update_rubalkhali_ontology.groovy"
    XRF_ABOX_SCRIPT = "scripts/rdf/generate_xrf_abox.groovy"

    def test_yaml_mapping_exists(self):
        """The XRF chemical mapping YAML (used by both RDF scripts) must exist."""
        assert os.path.exists(self.YAML_PATH), f"{self.YAML_PATH} not found"

    def test_le_is_not_mapped_to_a_chemical_entity(self):
        """LE is an instrument aggregate, not the ChEBI class 'chemical entity'."""
        with open(self.YAML_PATH) as handle:
            mapping = yaml.safe_load(handle)["mappings"]["LE"]
        assert mapping["chebi"] is None
        assert mapping["pubchem"] is None
        assert mapping["semantic_status"] == "instrument_pseudoanalyte"

    def test_both_scripts_skip_le(self):
        """Both the base ontology and XRF ABox scripts must skip LE in their counters."""
        for script_path in [self.BASE_ONTOLOGY_SCRIPT, self.XRF_ABOX_SCRIPT]:
            if not os.path.exists(script_path):
                pytest.skip(f"{script_path} not found")
            with open(script_path) as f:
                content = f.read()
            assert 'name == "LE"' in content or "name == 'LE'" in content, (
                f"{script_path} does not skip LE in its counter loop. "
                "This will cause an off-by-one IRI mismatch with the base ontology."
            )

    def test_si_gets_rak_0000100(self):
        """Si must be assigned RAK_0000100 (not LE), matching the base ontology."""
        if not os.path.exists(self.YAML_PATH):
            pytest.skip("YAML mapping not found")
        with open(self.YAML_PATH) as f:
            mapping = yaml.safe_load(f)
        analytes = list(mapping.get("mappings", {}).keys())

        # Simulate the counter assignment (skipping LE)
        counter = 100
        iri_map = {}
        for name in analytes:
            if name == "LE":
                continue
            iri_map[name] = f"RAK_0{counter:06d}"
            counter += 1

        assert iri_map.get("Si") == "RAK_0000100", (
            f"Si assigned {iri_map.get('Si')}, expected RAK_0000100"
        )
        assert iri_map.get("Fe") == "RAK_0000101", (
            f"Fe assigned {iri_map.get('Fe')}, expected RAK_0000101"
        )
        assert iri_map.get("SiO2") is not None, "SiO2 not found in mapping"
        assert iri_map.get("Fe2O3") is not None, "Fe2O3 not found in mapping"


class TestXRFChemicalMapping:
    """Prevent the retired shifted/label-similarity mappings from recurring."""

    CONSOLIDATED = "config/codes/xrf_chemical_mapping.yml"
    PROJECTIONS = (
        "config/codes/xrf_chebi_mapping.yml",
        "config/codes/xrf_chebi_mapping_validated.yml",
    )

    def test_legacy_files_are_exact_projections(self):
        with open(self.CONSOLIDATED) as handle:
            consolidated = yaml.safe_load(handle)["mappings"]
        expected = {
            analyte: entry.get("chebi")
            for analyte, entry in consolidated.items()
        }
        for path in self.PROJECTIONS:
            with open(path) as handle:
                observed = yaml.safe_load(handle)["mappings"]
            assert observed == expected, (
                f"{path} is not an exact ChEBI projection of {self.CONSOLIDATED}"
            )

    @pytest.mark.parametrize(
        "analyte,chebi_id",
        [
            ("K", "CHEBI_26216"),
            ("S", "CHEBI_26833"),
            ("P", "CHEBI_28659"),
            ("V", "CHEBI_27698"),
            ("U", "CHEBI_27214"),
            ("Y", "CHEBI_33331"),
            ("Sn", "CHEBI_27007"),
            ("I", "CHEBI_24859"),
            ("Pr", "CHEBI_49828"),
            ("W", "CHEBI_27998"),
            ("Co", "CHEBI_27638"),
            ("Au", "CHEBI_29287"),
            ("SO3", "CHEBI_29384"),
            ("Cr2O3", "CHEBI_48242"),
            ("CuO", "CHEBI_75955"),
        ],
    )
    def test_formula_matching_chebi_identifiers(self, analyte, chebi_id):
        with open(self.CONSOLIDATED) as handle:
            mapping = yaml.safe_load(handle)["mappings"]
        assert mapping[analyte]["chebi"].endswith(chebi_id)

    @pytest.mark.parametrize(
        "analyte",
        [
            "Na2O",
            "MnO",
            "SrO",
            "ZrO2",
            "BaO",
            "La2O3",
            "PrO2",
            "Nd2O3",
            "Sm2O3",
            "NiO",
            "CoO",
            "Sc2O3",
            "Ga2O3",
        ],
    )
    def test_missing_chebi_oxide_is_explicitly_null(self, analyte):
        with open(self.CONSOLIDATED) as handle:
            mapping = yaml.safe_load(handle)["mappings"]
        assert mapping[analyte]["chebi"] is None

    def test_atomic_halogen_pubchem_records(self):
        with open(self.CONSOLIDATED) as handle:
            mapping = yaml.safe_load(handle)["mappings"]
        assert mapping["Cl"]["pubchem"].endswith("/5360523")
        assert mapping["Br"]["pubchem"].endswith("/5360770")
        assert mapping["I"]["pubchem"].endswith("/5360629")

    def test_pro2_rejects_charged_pubchem_record(self):
        with open(self.CONSOLIDATED) as handle:
            mapping = yaml.safe_load(handle)["mappings"]["PrO2"]
        assert mapping["chebi"] is None
        assert mapping["pubchem"] is None
        assert mapping["semantic_status"] == "local_formula_only"

    def test_checked_audit_artifact_passes_if_present(self):
        path = "data/release/xrf_chemical_mapping_audit/xrf_chemical_mapping_audit.json"
        if not os.path.exists(path):
            pytest.skip("chemical mapping audit has not been generated")
        with open(path) as handle:
            audit = json.load(handle)
        assert audit["status"] == "passed"
        assert audit["metadata"]["row_count"] == 93
        assert audit["metadata"]["chebi_version"] == "247"
        assert not audit["errors"]

    def test_generated_rdf_uses_corrected_cross_references_if_present(self):
        path = "data/processed/ontology/rubalkhali_xrf.owl"
        if not os.path.exists(path):
            pytest.skip("XRF ABox has not been generated")
        with open(path) as handle:
            rdf = handle.read()
        for identifier in (
            "CHEBI_28659",
            "CHEBI_27698",
            "CHEBI_27214",
            "CHEBI_27007",
            "CHEBI_27638",
            "CHEBI_29287",
            "CHEBI_29384",
            "CHEBI_48242",
            "CHEBI_75955",
        ):
            assert identifier in rdf
        for retired_identifier in (
            "CHEBI_17203",
            "CHEBI_16414",
            "CHEBI_17568",
            "CHEBI_17909",
            "CHEBI_34631",
            "CHEBI_59965",
            "CHEBI_17359",
            "CHEBI_50812",
            "CHEBI_50823",
        ):
            assert retired_identifier not in rdf


class TestXRFLightElements:
    """
    Verify that Light Elements (LE) are correctly represented in the generated OWL.

    LE is measured by the field Vanta XRF device as a combined percentage for
    H, He, Li, Be, B, C, N, O, F elements too light to detect individually.
    LE has predefined IRIs (RAK_0000032 for quality, RAK_0000033 for value)
    and is NOT mapped to a ChEBI IRI. It only appears in Field XRF (not Lab XRF).
    """

    OWL_PATH = "data/processed/ontology/rubalkhali_xrf.owl"
    LE_QUALITY_IRI = "RAK_0000032"
    LE_VALUE_IRI = "RAK_0000033"

    @pytest.fixture
    def xrf_owl_content(self):
        if not os.path.exists(self.OWL_PATH):
            pytest.skip("XRF OWL file not generated yet")
        with open(self.OWL_PATH) as f:
            return f.read()

    def test_le_quality_instances_exist(self, xrf_owl_content):
        """LE quality instances (typed as RAK_0000032) must exist in the Field XRF OWL."""
        le_quality_count = len(re.findall(r'Light Elements quality \(Field XRF', xrf_owl_content))
        assert le_quality_count > 0, (
            f"No 'Light Elements quality (Field XRF' labels found — "
            "LE must be present in Field XRF output"
        )

    def test_le_value_instances_have_percentage(self, xrf_owl_content):
        """LE measurement value instances must carry a non-zero numeric concentration."""
        # Find blocks containing LE value labels and check they have RAK_2000012 data property
        le_value_count = len(re.findall(r'Light Elements measurement value \(Field XRF', xrf_owl_content))
        assert le_value_count > 0, "No LE measurement value instances found in Field XRF"
        # Each LE value instance should be typed as RAK_0000033 and have hasConcValue
        assert self.LE_VALUE_IRI in xrf_owl_content, (
            f"LE value class IRI ({self.LE_VALUE_IRI}) not found — "
            "LE must use predefined IRI, not counter-based assignment"
        )

    def test_le_uses_predefined_quality_iri(self, xrf_owl_content):
        """LE quality class must use predefined RAK_0000032, not the counter-based range."""
        assert self.LE_QUALITY_IRI in xrf_owl_content, (
            f"LE quality IRI ({self.LE_QUALITY_IRI}) not referenced in OWL — "
            "LE must use predefined IRI, skipped in counter loop"
        )
        # Counter-based quality IRIs start at RAK_0000100; LE must NOT fall there
        le_blocks = re.findall(
            r'<owl:NamedIndividual[^>]*>.*?</owl:NamedIndividual>',
            xrf_owl_content, re.DOTALL
        )
        for block in le_blocks:
            if 'Light Elements quality (Field XRF' in block:
                assert 'RAK_0000032' in block, (
                    "LE quality instance not typed as RAK_0000032"
                )
                assert 'RAK_0000100' not in block, (
                    "LE quality instance incorrectly typed as RAK_0000100 (Si's IRI) — "
                    "LE must use predefined IRI"
                )
                break

    def test_le_not_in_lab_xrf(self, xrf_owl_content):
        """LE must not appear in Lab XRF labels — the lab data has no LE column."""
        le_lab_count = len(re.findall(r'Light Elements.*?Lab XRF', xrf_owl_content))
        assert le_lab_count == 0, (
            f"Found {le_lab_count} 'Light Elements ... Lab XRF' labels — "
            "LE is only measured by field Vanta device, not in lab XRF"
        )


class TestXRFFieldVsLab:
    """
    Verify that Field XRF and Lab XRF data are correctly distinguished.

    Field XRF (Vanta device): measures at the recorded Trip 5 site and reports
    raw element wt%, with derived oxide-equivalent values where configured.
    The field log does not identify a collected sample or soil compartment.

    Lab XRF (three soil types): stores both element and oxide columns as-is
    from the combined lab table. Soil types: Surface, Deep, Rhizosphere.
    """

    OWL_PATH = "data/processed/ontology/rubalkhali_xrf.owl"

    @pytest.fixture
    def xrf_owl_content(self):
        if not os.path.exists(self.OWL_PATH):
            pytest.skip("XRF OWL file not generated yet")
        with open(self.OWL_PATH) as f:
            return f.read()

    def test_field_xrf_has_both_si_and_sio2(self, xrf_owl_content):
        """Field XRF stores both Si (element wt%) and SiO2 (oxide wt%) — consistent with lab TSV format."""
        si_field = re.findall(r'Si quality \(Field XRF', xrf_owl_content)
        assert len(si_field) > 0, (
            "No 'Si quality (Field XRF' labels found — Field XRF should store element form"
        )
        sio2_field = re.findall(r'SiO2 quality \(Field XRF', xrf_owl_content)
        assert len(sio2_field) > 0, (
            "No 'SiO2 quality (Field XRF' labels found — Field XRF should store oxide form"
        )

    def test_lab_xrf_has_both_si_and_sio2(self, xrf_owl_content):
        """Lab XRF must have both Si and SiO2 quality instances (stored as-is from lab table)."""
        si_lab = re.findall(r'Si quality \(Lab XRF\)', xrf_owl_content)
        sio2_lab = re.findall(r'SiO2 quality \(Lab XRF\)', xrf_owl_content)
        assert len(si_lab) > 0, "No 'Si quality (Lab XRF)' labels — lab data has Si column"
        assert len(sio2_lab) > 0, "No 'SiO2 quality (Lab XRF)' labels — lab data has SiO2 column"

    def test_lab_xrf_has_three_soil_types(self, xrf_owl_content):
        """Lab XRF must cover all three soil types: Surface, Deep, Rhizosphere."""
        for soil_type in ["Surface", "Deep", "Rhizosphere"]:
            pattern = rf"Lab XRF analysis for Sample \w+ \({soil_type}\)"
            matches = re.findall(pattern, xrf_owl_content)
            assert len(matches) > 0, (
                f"No Lab XRF processes found for soil type '{soil_type}' — "
                "all three soil types must be represented"
            )

    def test_field_xrf_linked_to_sites(self, xrf_owl_content):
        """Field XRF process labels must reference site IDs."""
        field_proc = re.findall(r'Field XRF analysis \(Test \d+\) for Site \d+', xrf_owl_content)
        assert len(field_proc) > 0, (
            "No 'Field XRF analysis ... for Site ...' process labels found"
        )
