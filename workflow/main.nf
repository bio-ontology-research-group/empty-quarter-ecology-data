nextflow.enable.dsl = 2

/*
 * Empty Quarter cross-paper reproducibility workflow.
 *
 * The workflow treats the repository as a read-only input.  Every process
 * writes into its isolated Nextflow task directory and publishDir copies only
 * declared artifacts to params.outdir.
 */

params.project_root = params.project_root ?: file("${projectDir}/..").toAbsolutePath()
params.ecology_paper = params.ecology_paper ?: file("${params.project_root}/empty-quarter-amplicon").toAbsolutePath()
params.outdir = params.outdir ?: file("${params.project_root}/results/reproducibility")
params.stage = params.stage ?: "evidence"
params.run_advanced = params.run_advanced ?: false
params.run_kg = params.run_kg ?: false
params.build_papers = params.build_papers ?: false
params.coverm_dir = params.coverm_dir ?: null
params.eggnog_annotations = params.eggnog_annotations ?: null
params.measured_function_inputs = params.measured_function_inputs ?: null
params.pma_asv_table = params.pma_asv_table ?:
    "${params.project_root}/data-paper/zenodo/metadata/relic-dna/PMA_ASV_table.tsv"
params.functional_permutations = params.functional_permutations ?: 999
params.functional_max_kos = params.functional_max_kos ?: 2000
params.execution_mode = params.execution_mode ?: "host-default"
params.taxonomy_source_taxonomy = params.taxonomy_source_taxonomy ?:
    "${params.project_root}/data/processed/taxonomy/taxon-tables/taxonomy-trips1-5.tsv"
params.taxonomy_feature_table = params.taxonomy_feature_table ?:
    "${params.project_root}/data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv"
params.taxonomy_canonical_mapping = params.taxonomy_canonical_mapping ?:
    "${params.project_root}/data/processed/ontology/mapped_taxonomy.tsv"
params.taxonomy_ncbi_owl = params.taxonomy_ncbi_owl ?:
    "${params.project_root}/data/ontologies/ncbitaxon.owl"
params.taxonomy_sra_sheet = params.taxonomy_sra_sheet ?:
    "${params.project_root}/data/metadata/sra-submissions/submission-sheet.tsv"
params.taxonomy_java_opts = params.taxonomy_java_opts ?: "-Xms2g -Xmx32g"

def stageEnabled(String name) {
    def order = ["evidence", "core", "advanced", "full"]
    def requested = order.indexOf(params.stage as String)
    def required = order.indexOf(name)
    if (requested < 0)
        error "Unknown --stage '${params.stage}'. Choose: ${order.join(', ')}"
    return requested >= required
}

process CAPTURE_PROVENANCE {
    tag "exact source state"
    publishDir "${params.outdir}/00_provenance", mode: "copy", overwrite: true

    input:
    val project_root
    val ecology_paper

    output:
    path "provenance"

    script:
    """
    bash ${projectDir}/bin/capture_provenance.sh \
      '${project_root}' '${ecology_paper}' provenance
    """

    stub:
    """
    mkdir -p provenance
    printf 'stub\\n' > provenance/README.txt
    """
}

process CAPTURE_EXECUTION_ENVIRONMENT {
    tag "executed analysis environment"
    cpus 1
    memory "2 GB"
    time "30m"
    publishDir "${params.outdir}/00_execution_environment", mode: "copy", overwrite: true

    input:
    val project_root
    path source_provenance
    val execution_mode
    val analysis_container

    output:
    path "execution_environment"

    script:
    """
    bash ${projectDir}/bin/capture_execution_environment.sh \
      '${project_root}' execution_environment \
      '${execution_mode}' '${analysis_container}' \
      '${source_provenance}/source_state.json'
    """

    stub:
    """
    mkdir -p execution_environment
    printf '{"status":"stub"}\\n' \
      > execution_environment/execution_environment_manifest.json
    printf 'stub\\n' > execution_environment/environment.tsv
    """
}

process ENVIRONMENTAL_METADATA {
    tag "field environmental metadata"
    publishDir "${params.outdir}/01_environmental_metadata", mode: "copy", overwrite: true

    input:
    val project_root

    output:
    path "environmental_metadata"

    script:
    """
    python3 '${project_root}/data-paper/scripts/generate_env_table.py' \
      --project-root '${project_root}' \
      --output-dir environmental_metadata
    cmp environmental_metadata/environmental_measurements_curated.tsv \
      '${project_root}/data/processed/metadata/environmental_measurements_curated.tsv'
    cmp environmental_metadata/environmental_measurements_audit.json \
      '${project_root}/data/processed/metadata/environmental_measurements_audit.json'
    cmp environmental_metadata/env_table.tex \
      '${project_root}/data-paper/env_table.tex'
    python3 -m pytest -q \
      '${project_root}/tests/test_samplesheet_environment.py'
    (
      cd environmental_metadata
      find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\\0' |
        sort -z |
        xargs -0 sha256sum > SHA256SUMS
      sha256sum -c SHA256SUMS
    )
    """

    stub:
    """
    mkdir -p environmental_metadata
    printf 'stub\\n' > environmental_metadata/env_table.tex
    printf 'stub\\n' > environmental_metadata/environmental_measurements_curated.tsv
    printf '{"status":"stub"}\\n' \
      > environmental_metadata/environmental_measurements_audit.json
    printf 'stub\\n' > environmental_metadata/SHA256SUMS
    """
}

process DATA_PAPER_FIGURES {
    tag "data-paper transect altitude"
    cpus 1
    memory "2 GB"
    time "30m"
    publishDir "${params.outdir}/01_data_paper_figures", mode: "copy", overwrite: true

    input:
    val project_root

    output:
    path "data_paper_figures"

    script:
    """
    python3 '${project_root}/scripts/analysis/transect_altitude_figure.py' \
      --input '${project_root}/data/metadata/geodata/site_altitudes.tsv' \
      --output-dir data_paper_figures
    cmp data_paper_figures/transect_altitude.png \
      '${project_root}/data/processed/figures/transect_altitude.png'
    cmp data_paper_figures/transect_altitude.png \
      '${project_root}/data-paper/transect_altitude.png'
    (
      cd data_paper_figures
      find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\\0' |
        sort -z |
        xargs -0 sha256sum > SHA256SUMS
      sha256sum -c SHA256SUMS
    )
    """

    stub:
    """
    mkdir -p data_paper_figures
    printf 'stub\\n' > data_paper_figures/transect_altitude.png
    printf 'site\\taltitude_m\\n' \
      > data_paper_figures/transect_altitude_profile.tsv
    printf '{"status":"stub"}\\n' \
      > data_paper_figures/transect_altitude_summary.json
    printf 'stub\\n' > data_paper_figures/SHA256SUMS
    """
}

process GENERATE_CORE_KG_MODULES {
    tag "generated tractable knowledge-graph modules"
    cpus 4
    memory "24 GB"
    time "6h"
    publishDir "${params.outdir}/02_core_kg", mode: "copy", overwrite: true

    input:
    val project_root

    output:
    path "core_kg_modules"

    script:
    """
    bash ${projectDir}/bin/run_core_kg_generation.sh \
      '${project_root}' core_kg_modules
    """

    stub:
    """
    mkdir -p core_kg_modules
    for module in \
      rubalkhali.owl \
      rubalkhali_sites.owl \
      rubalkhali_measurements.owl \
      rubalkhali_samples.owl \
      rubalkhali_xrf.owl \
      rubalkhali_dna.owl \
      rubalkhali_sra.owl \
      rubalkhali_qc.owl \
      rubalkhali_controls.owl \
      rubalkhali_controls.ttl \
      rubalkhali_ph_eq_ph_shared_v1_0_0.owl \
      rubalkhali_ph_eq_ph_shared_v1_0_0.ttl
    do
      printf '<rdf:RDF/>\\n' > "core_kg_modules/\$module"
    done
    printf '{"status":"stub"}\\n' \
      > core_kg_modules/core_kg_manifest.json
    printf '{"status":"stub"}\\n' \
      > core_kg_modules/ontology_declaration_audit.json
    printf 'path\\tbytes\\tsha256\\n' \
      > core_kg_modules/input_manifest.tsv
    printf 'stub\\n' > core_kg_modules/SHA256SUMS
    """
}

process RELEASE_EVIDENCE {
    tag "sample and release ledger"
    publishDir "${params.outdir}/01_release_evidence", mode: "copy", overwrite: true

    input:
    val project_root
    path environmental_metadata
    path core_kg_modules

    output:
    path "release_evidence"

    script:
    """
    cmp '${environmental_metadata}/environmental_measurements_curated.tsv' \
      '${project_root}/data/processed/metadata/environmental_measurements_curated.tsv'
    cmp '${environmental_metadata}/environmental_measurements_audit.json' \
      '${project_root}/data/processed/metadata/environmental_measurements_audit.json'
    (
      cd '${core_kg_modules}'
      sha256sum -c SHA256SUMS
    )
    core_kg_abs=\$(readlink -f '${core_kg_modules}')
    mkdir -p \
      release-sandbox/data/processed \
      release-sandbox/data
    ln -s '${project_root}/analysis' release-sandbox/analysis
    ln -s '${project_root}/data/metadata' release-sandbox/data/metadata
    ln -s '${project_root}/data/processed/metadata' \
      release-sandbox/data/processed/metadata
    ln -s '${project_root}/data/processed/taxonomy' \
      release-sandbox/data/processed/taxonomy
    ln -s "\$core_kg_abs" \
      release-sandbox/data/processed/ontology
    python3 '${project_root}/scripts/release/build_release_evidence.py' \
      --root "\$PWD/release-sandbox" \
      --output-dir release_evidence
    cp '${core_kg_modules}/core_kg_manifest.json' \
      release_evidence/core_kg_manifest.json
    cp '${core_kg_modules}/ontology_declaration_audit.json' \
      release_evidence/ontology_declaration_audit.json
    cp '${core_kg_modules}/SHA256SUMS' \
      release_evidence/core_kg_SHA256SUMS
    """

    stub:
    """
    mkdir -p release_evidence
    printf '{}\\n' > release_evidence/release_evidence.json
    """
}

process XRF_AUDIT {
    tag "field and laboratory XRF"
    publishDir "${params.outdir}/02_xrf_audit", mode: "copy", overwrite: true

    input:
    val project_root

    output:
    path "xrf_audit"

    script:
    """
    python3 '${project_root}/scripts/xrf/audit_xrf_provenance.py' \
      --project-root '${project_root}' \
      --output-dir "\$PWD/xrf_audit"
    python3 '${project_root}/scripts/xrf/audit_xrf_chemical_mapping.py' \
      --mapping '${project_root}/config/codes/xrf_chemical_mapping.yml' \
      --chebi '${project_root}/data/ontologies/chebi.owl' \
      --pubchem-snapshot '${project_root}/config/codes/xrf_pubchem_snapshot.json' \
      --output-dir "\$PWD/xrf_audit/chemical_mapping"
    """

    stub:
    """
    mkdir -p xrf_audit
    printf '{"status":"stub"}\\n' > xrf_audit/xrf_audit.json
    mkdir -p xrf_audit/chemical_mapping
    printf '{"status":"stub"}\\n' \
      > xrf_audit/chemical_mapping/xrf_chemical_mapping_audit.json
    """
}

process COMPETENCY_QUERY_VALIDATION {
    tag "field-XRF Site 10 competency query"
    publishDir "${params.outdir}/02_competency_query", mode: "copy", overwrite: true

    input:
    val project_root
    path core_kg_modules
    path field_xrf_query

    output:
    path "competency_query"

    script:
    """
    (
      cd '${core_kg_modules}'
      sha256sum -c SHA256SUMS
    )
    python3 '${project_root}/scripts/validation/validate_competency_query.py' \
      --base '${core_kg_modules}/rubalkhali.owl' \
      --sites '${core_kg_modules}/rubalkhali_sites.owl' \
      --xrf '${core_kg_modules}/rubalkhali_xrf.owl' \
      --query '${field_xrf_query}' \
      --expected-rows 46 \
      --output-dir competency_query
    cmp '${field_xrf_query}' competency_query/field_xrf_site10.rq
    (
      cd competency_query
      sha256sum -c SHA256SUMS
    )
    """

    stub:
    """
    mkdir -p competency_query
    printf '{"status":"stub","expected_rows":46,"observed_rows":46}\\n' \
      > competency_query/competency_query_validation.json
    printf 'processLabel\\tsiteLabel\\tanalyte\\tconcentration\\n' \
      > competency_query/field_xrf_site10_results.tsv
    printf 'SELECT * WHERE { ?s ?p ?o }\\n' \
      > competency_query/field_xrf_site10.rq
    (
      cd competency_query
      sha256sum \
        competency_query_validation.json \
        field_xrf_site10_results.tsv \
        field_xrf_site10.rq \
        > SHA256SUMS
    )
    """
}

process ECOLOGY_CORE {
    tag "canonical ecology core"
    cpus 8
    memory "32 GB"
    time "24h"
    publishDir "${params.outdir}/03_ecology_core", mode: "copy", overwrite: true

    input:
    val project_root
    path pma_asv_table

    output:
    path "ecology_core"

    script:
    """
    bash ${projectDir}/bin/run_ecology_core.sh \
      '${project_root}' ecology_core '${pma_asv_table}'
    """

    stub:
    """
    mkdir -p ecology_core
    printf '{"status":"stub"}\\n' > ecology_core/run_manifest.json
    """
}

process CONTROL_ANALYSIS {
    tag "assay-aware controls and ecology sensitivity"
    cpus 8
    memory "32 GB"
    time "36h"
    publishDir "${params.outdir}/04_control_analysis", mode: "copy", overwrite: true

    input:
    val project_root
    path ecology_core

    output:
    path "control_analysis"

    script:
    """
    bash ${projectDir}/bin/run_control_analysis.sh \
      '${project_root}' '${ecology_core}' control_analysis
    """

    stub:
    """
    mkdir -p control_analysis/control_audit control_analysis/control_sensitivity
    printf '{"status":"stub"}\n' > control_analysis/run_manifest.json
    printf 'stub\n' > control_analysis/SHA256SUMS
    """
}

process ENVIRONMENT_ASSOCIATIONS {
    tag "site-level climate and collection-weather associations"
    cpus 2
    memory "8 GB"
    time "2h"
    publishDir "${params.outdir}/04_environment_associations", mode: "copy", overwrite: true

    input:
    val project_root
    path ecology_core
    path environmental_metadata

    output:
    path "environment_associations"

    script:
    """
    python3 '${project_root}/analysis/v3/environment_associations.py' \
      --project-root '${project_root}' \
      --alpha-table '${ecology_core}/cache/alpha.tsv' \
      --genus-counts '${ecology_core}/cache/genus_counts.tsv' \
      --monthly-climate \
        '${project_root}/data/processed/climate/monthly_weather_averages_canonical.tsv' \
      --field-weather \
        '${environmental_metadata}/environmental_measurements_curated.tsv' \
      --output-dir environment_associations
    (cd environment_associations && sha256sum -c SHA256SUMS)
    """

    stub:
    """
    mkdir -p environment_associations
    printf '{"status":"stub"}\n' \
      > environment_associations/analysis_decision.json
    printf 'stub\n' > environment_associations/SHA256SUMS
    """
}

process RAIN_PULSE_SUITE {
    tag "short-term rainfall pulse and sensitivities"
    cpus 4
    memory "16 GB"
    time "24h"
    publishDir "${params.outdir}/04_rain_pulse", mode: "copy", overwrite: true

    input:
    val project_root
    path ecology_core
    path control_analysis

    output:
    path "rain_pulse"

    script:
    """
    bash ${projectDir}/bin/run_rain_pulse_suite.sh \
      '${project_root}' '${ecology_core}' '${control_analysis}' rain_pulse
    """

    stub:
    """
    mkdir -p rain_pulse/rain_pulse_response
    printf '{"status":"stub"}\n' \
      > rain_pulse/rain_pulse_response/analysis_decision.json
    printf 'stub\n' > rain_pulse/SHA256SUMS
    """
}

process ECOLOGY_ADVANCED {
    tag "advanced claim rescue"
    cpus 16
    memory "48 GB"
    time "48h"
    publishDir "${params.outdir}/04_ecology_advanced", mode: "copy", overwrite: true

    input:
    val project_root
    path ecology_core
    path measured_function_inputs

    output:
    path "ecology_advanced"

    script:
    """
    bash ${projectDir}/bin/run_ecology_advanced.sh \
      '${project_root}' '${ecology_core}' \
      '${measured_function_inputs}' ecology_advanced
    """

    stub:
    """
    mkdir -p ecology_advanced
    printf '{"status":"stub"}\\n' > ecology_advanced/run_manifest.json
    """
}

process PICRUST2_ECOLOGY {
    tag "predicted pathway geography and soil-position structure"
    cpus 4
    memory "16 GB"
    time "8h"
    publishDir "${params.outdir}/06_picrust2_ecology", mode: "copy", overwrite: true

    input:
    val project_root
    path ecology_core
    path ecology_advanced

    output:
    path "picrust2_ecology"

    script:
    """
    python3 '${project_root}/analysis/v3/picrust2_ecology.py' \
      --project-root '${project_root}' \
      --alpha-table '${ecology_core}/cache/alpha.tsv' \
      --measured-function-summary \
        '${ecology_advanced}/measured_function_summary/summary_metrics.tsv' \
      --output-dir picrust2_ecology \
      --permutations 9999 \
      --bootstrap 2000 \
      --seed 20260804
    (cd picrust2_ecology && sha256sum -c SHA256SUMS)
    """

    stub:
    """
    mkdir -p picrust2_ecology
    printf '{"status":"stub"}\n' > picrust2_ecology/analysis_decision.json
    printf 'stub\n' > picrust2_ecology/SHA256SUMS
    """
}

process FUNCTIONAL_REDUNDANCY_NULL {
    tag "resolution-matched encoded-function null"
    cpus 16
    memory "32 GB"
    time "24h"
    publishDir "${params.outdir}/06_functional_redundancy", mode: "copy", overwrite: true

    input:
    val project_root
    path coverm_input
    path eggnog_annotations
    val permutations
    val max_kos

    output:
    path "functional_redundancy"

    script:
    """
    coverm_path='${coverm_input}'
    if [[ -f "\$coverm_path" ]]; then
      mkdir -p functional-inputs
      tar -xzf "\$coverm_path" -C functional-inputs
      coverm_path=functional-inputs/coverm
    fi
    if [[ ! -d "\$coverm_path" ]]; then
      printf 'CoverM input must be a directory or a tar.gz containing coverm/: %s\n' \
        "\$coverm_path" >&2
      exit 66
    fi
    python3 '${project_root}/analysis/v3/functional_redundancy_null.py' \
      --coverm-dir "\$coverm_path" \
      --eggnog-annotations '${eggnog_annotations}' \
      --output-dir functional_redundancy \
      --permutations '${permutations}' \
      --max-kos '${max_kos}'
    (
      cd functional_redundancy
      find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\\0' |
        sort -z |
        xargs -0 sha256sum > SHA256SUMS
    )
    """

    stub:
    """
    mkdir -p functional_redundancy
    printf '{"status":"stub"}\\n' > functional_redundancy/functional_redundancy_summary.json
    """
}

process NETWORK_RESCUE {
    tag "compositional conditional-association networks"
    cpus 8
    memory "32 GB"
    time "24h"
    publishDir "${params.outdir}/05_network_rescue", mode: "copy", overwrite: true

    input:
    val project_root
    path ecology_core

    output:
    path "network_rescue"

    script:
    """
    python3 '${project_root}/analysis/v3/network_rescue/run_network_rescue.py' \
      --project-root '${project_root}' \
      --input-table "\$PWD/${ecology_core}/cache/genus_counts.tsv" \
      --output-dir "\$PWD/network_rescue"
    (
      cd network_rescue
      find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\\0' |
        sort -z |
        xargs -0 sha256sum > SHA256SUMS
    )
    """

    stub:
    """
    mkdir -p network_rescue
    printf '{"status":"stub"}\\n' > network_rescue/claim_verdict.json
    """
}

process SUBMISSION_FIGURES {
    tag "evidence-bounded ecology figures"
    cpus 1
    memory "4 GB"
    time "1h"
    publishDir "${params.outdir}/07_submission_figures", mode: "copy", overwrite: true

    input:
    path ecology_core
    path environment_associations
    path rain_pulse
    path picrust2_ecology
    path control_analysis
    path ecology_advanced

    output:
    path "submission_figures"

    script:
    """
    python3 '${params.project_root}/analysis/v3/make_submission_figures.py' \
      --core-dir '${ecology_core}' \
      --environment-dir '${environment_associations}' \
      --rain-dir '${rain_pulse}/rain_pulse_response' \
      --picrust-dir '${picrust2_ecology}' \
      --control-dir '${control_analysis}/control_audit' \
      --pma-dir '${ecology_core}/pma_endpoints' \
      --measured-function-dir \
        '${ecology_advanced}/measured_function_summary' \
      --output-dir submission_figures
    """

    stub:
    """
    mkdir -p submission_figures
    printf 'stub\n' > submission_figures/figure_manifest.tsv
    """
}

process STAGE_MANUSCRIPT_FIGURES {
    tag "existing evidence-bounded ecology figures"

    input:
    val ecology_paper

    output:
    path "submission_figures"

    script:
    """
    mkdir -p submission_figures
    cp \
      '${ecology_paper}/figures/fig1_landscape.pdf' \
      '${ecology_paper}/figures/fig2_soil_position.pdf' \
      '${ecology_paper}/figures/fig3_function_controls.pdf' \
      '${ecology_paper}/figures/figS_campaign_rainfall.pdf' \
      submission_figures/
    if [[ -f '${ecology_paper}/figures/figure_manifest.tsv' ]]; then
      cp '${ecology_paper}/figures/figure_manifest.tsv' submission_figures/
    fi
    """
}

process BUILD_TAXONOMY_MAPPING {
    tag "corrected Trips 1-5 taxonomy mapping"
    cpus 2
    memory "24 GB"
    time "12h"
    publishDir "${params.outdir}/08_taxonomy_mapping", mode: "copy", overwrite: true

    input:
    path taxonomy_code
    path source_taxonomy
    path feature_table
    path canonical_mapping
    path ncbi_taxonomy

    output:
    path "taxonomy_mapping"

    script:
    """
    mkdir -p taxonomy_mapping/canonical taxonomy_mapping/audit
    python3 '${taxonomy_code}/build_canonical_taxonomy.py' \
      --source-taxonomy '${source_taxonomy}' \
      --feature-table '${feature_table}' \
      --canonical-mapping '${canonical_mapping}' \
      --ncbi-taxonomy '${ncbi_taxonomy}' \
      --output-dir taxonomy_mapping/canonical \
      --audit-dir taxonomy_mapping/audit

    for required in \
      taxonomy_mapping/canonical/mapped_taxonomy_corrected.json \
      taxonomy_mapping/canonical/mapped_taxonomy_corrected.tsv \
      taxonomy_mapping/canonical/mapped_taxonomy_corrected.manifest.json \
      taxonomy_mapping/canonical/ecosystem_module.owl \
      taxonomy_mapping/canonical/ecosystem_module.ttl \
      taxonomy_mapping/audit/taxonomy_mapping_audit.json \
      taxonomy_mapping/audit/taxonomy_mapping_decisions.tsv \
      taxonomy_mapping/audit/taxonomy_source_supplementary_species.tsv \
      taxonomy_mapping/audit/taxonomy_source_schema_audit.json
    do
      [[ -s "\$required" ]] || {
        echo "mapping builder omitted required artifact: \$required" >&2
        exit 65
      }
    done
    (
      cd taxonomy_mapping
      find . -type f ! -name SHA256SUMS -printf '%P\\0' |
        sort -z |
        xargs -0 sha256sum > SHA256SUMS
      sha256sum -c SHA256SUMS
    )
    """

    stub:
    """
    mkdir -p taxonomy_mapping/canonical taxonomy_mapping/audit
    printf '{"status":"passed"}\\n' \
      > taxonomy_mapping/canonical/mapped_taxonomy_corrected.json
    printf 'stub\\n' \
      > taxonomy_mapping/canonical/mapped_taxonomy_corrected.tsv
    printf '{"status":"passed"}\\n' \
      > taxonomy_mapping/canonical/mapped_taxonomy_corrected.manifest.json
    printf 'stub\\n' > taxonomy_mapping/canonical/ecosystem_module.owl
    printf 'stub\\n' > taxonomy_mapping/canonical/ecosystem_module.ttl
    printf '{"status":"passed"}\\n' \
      > taxonomy_mapping/audit/taxonomy_mapping_audit.json
    printf 'stub\\n' \
      > taxonomy_mapping/audit/taxonomy_mapping_decisions.tsv
    printf 'stub\\n' \
      > taxonomy_mapping/audit/taxonomy_source_supplementary_species.tsv
    printf '{"status":"passed"}\\n' \
      > taxonomy_mapping/audit/taxonomy_source_schema_audit.json
    printf 'stub\\n' > taxonomy_mapping/SHA256SUMS
    """
}

process GENERATE_TAXONOMY_ABOX {
    tag "generated corrected taxonomy ABox"
    cpus 8
    memory "48 GB"
    disk "20 GB"
    time "24h"
    publishDir "${params.outdir}/09_taxonomy_abox", mode: "copy", overwrite: true

    input:
    path taxonomy_generator
    path taxonomy_mapping
    path source_taxonomy
    path feature_table
    path sra_sheet
    path core_kg_modules
    val java_opts

    output:
    path "taxonomy_abox"

    script:
    """
    export JAVA_OPTS='${java_opts}'
    bash ${projectDir}/bin/run_taxonomy_abox_generation.sh \
      '${taxonomy_generator}' \
      '${taxonomy_mapping}/canonical/mapped_taxonomy_corrected.json' \
      '${taxonomy_mapping}/canonical/mapped_taxonomy_corrected.manifest.json' \
      '${source_taxonomy}' \
      '${feature_table}' \
      '${sra_sheet}' \
      '${core_kg_modules}/rubalkhali_sra.owl' \
      '${taxonomy_mapping}/canonical/ecosystem_module.owl' \
      taxonomy_abox
    """

    stub:
    """
    mkdir -p taxonomy_abox
    printf '@prefix ex: <https://example.org/> .\\n' \
      > taxonomy_abox/rubalkhali_taxonomy_abox.ttl
    printf '{"status":"passed"}\\n' \
      > taxonomy_abox/taxonomy_abox_manifest.json
    printf 'stub\\n' > taxonomy_abox/SHA256SUMS
    """
}

process KG_VALIDATE {
    tag "generated knowledge graph validation"
    cpus 8
    memory "32 GB"
    time "12h"
    publishDir "${params.outdir}/10_kg_validation", mode: "copy", overwrite: true

    input:
    val project_root
    path core_kg_modules
    path taxonomy_abox
    path taxonomy_mapping

    output:
    path "kg_validation"

    script:
    """
    bash ${projectDir}/bin/run_kg_validation.sh \
      '${project_root}' kg_validation '${core_kg_modules}' \
      '${taxonomy_abox}' '${taxonomy_mapping}'
    """

    stub:
    """
    mkdir -p kg_validation
    printf '{"status":"stub"}\\n' > kg_validation/run_manifest.json
    """
}

process BUILD_PAPERS {
    tag "both manuscripts"
    cpus 2
    memory "8 GB"
    time "2h"
    publishDir "${params.outdir}/11_papers", mode: "copy", overwrite: true

    input:
    val project_root
    val ecology_paper
    path release_evidence
    path xrf_audit
    path submission_figures
    path data_paper_figures
    path environmental_metadata
    path competency_query
    path source_provenance
    path execution_environment
    val execution_mode
    val tex_container

    output:
    path "papers"

    script:
    """
    bash ${projectDir}/bin/build_papers.sh \
      '${project_root}' '${ecology_paper}' papers \
      '${release_evidence}' '${xrf_audit}' '${submission_figures}' \
      '${data_paper_figures}' '${environmental_metadata}' \
      '${competency_query}' \
      '${source_provenance}' '${execution_environment}' \
      '${execution_mode}' '${tex_container}'
    """

    stub:
    """
    mkdir -p papers
    printf 'stub\\n' > papers/README.txt
    """
}

workflow {
    project_root_ch = Channel.value(params.project_root.toString())
    ecology_paper_ch = Channel.value(params.ecology_paper.toString())
    ws_host_mode = (
        params.execution_mode.toString()
        == "host-analysis-docker-tex-profile"
    )
    if (ws_host_mode && params.analysis_container) {
        error "The ws_host profile executes analysis on the host; do not supply --analysis_container"
    }

    competency_query_ch = Channel.fromPath(
        "${params.project_root}/data-paper/zenodo/sparql/field_xrf_site10.rq",
        checkIfExists: true
    )
    pma_asv_table_ch = Channel.fromPath(
        params.pma_asv_table.toString(),
        checkIfExists: true
    )

    CAPTURE_PROVENANCE(project_root_ch, ecology_paper_ch)
    CAPTURE_EXECUTION_ENVIRONMENT(
        project_root_ch,
        CAPTURE_PROVENANCE.out,
        Channel.value(params.execution_mode.toString()),
        Channel.value(
            params.analysis_container
                ? params.analysis_container.toString()
                : ""
        )
    )
    ENVIRONMENTAL_METADATA(project_root_ch)
    DATA_PAPER_FIGURES(project_root_ch)
    GENERATE_CORE_KG_MODULES(project_root_ch)
    RELEASE_EVIDENCE(
        project_root_ch,
        ENVIRONMENTAL_METADATA.out,
        GENERATE_CORE_KG_MODULES.out
    )
    XRF_AUDIT(project_root_ch)
    COMPETENCY_QUERY_VALIDATION(
        project_root_ch,
        GENERATE_CORE_KG_MODULES.out,
        competency_query_ch
    )

    if (stageEnabled("core") || params.run_advanced) {
        ECOLOGY_CORE(project_root_ch, pma_asv_table_ch)
        CONTROL_ANALYSIS(project_root_ch, ECOLOGY_CORE.out)
        ENVIRONMENT_ASSOCIATIONS(
            project_root_ch,
            ECOLOGY_CORE.out,
            ENVIRONMENTAL_METADATA.out
        )
        RAIN_PULSE_SUITE(
            project_root_ch,
            ECOLOGY_CORE.out,
            CONTROL_ANALYSIS.out
        )
    }

    if (stageEnabled("advanced") || params.run_advanced) {
        if (
            !params.coverm_dir
            || !params.eggnog_annotations
            || !params.measured_function_inputs
        ) {
            error "Advanced stage requires --coverm_dir, --eggnog_annotations, and --measured_function_inputs"
        }
        coverm_input_ch = Channel.fromPath(
            params.coverm_dir.toString(),
            checkIfExists: true
        )
        eggnog_annotations_ch = Channel.fromPath(
            params.eggnog_annotations.toString(),
            checkIfExists: true
        )
        measured_function_inputs_ch = Channel.fromPath(
            params.measured_function_inputs.toString(),
            checkIfExists: true
        )
        ECOLOGY_ADVANCED(
            project_root_ch,
            ECOLOGY_CORE.out,
            measured_function_inputs_ch
        )
        PICRUST2_ECOLOGY(
            project_root_ch,
            ECOLOGY_CORE.out,
            ECOLOGY_ADVANCED.out
        )
        NETWORK_RESCUE(project_root_ch, ECOLOGY_CORE.out)
        FUNCTIONAL_REDUNDANCY_NULL(
            project_root_ch,
            coverm_input_ch,
            eggnog_annotations_ch,
            Channel.value(params.functional_permutations as Integer),
            Channel.value(params.functional_max_kos as Integer)
        )
        SUBMISSION_FIGURES(
            ECOLOGY_CORE.out,
            ENVIRONMENT_ASSOCIATIONS.out,
            RAIN_PULSE_SUITE.out,
            PICRUST2_ECOLOGY.out,
            CONTROL_ANALYSIS.out,
            ECOLOGY_ADVANCED.out
        )
    }

    if (params.run_kg || params.stage == "full") {
        taxonomy_code_ch = Channel.fromPath(
            "${params.project_root}/scripts/taxonomy",
            checkIfExists: true
        )
        taxonomy_generator_ch = Channel.fromPath(
            "${params.project_root}/scripts/rdf/generate_taxonomy_abox.groovy",
            checkIfExists: true
        )
        taxonomy_source_ch = Channel.fromPath(
            params.taxonomy_source_taxonomy.toString(),
            checkIfExists: true
        )
        taxonomy_feature_table_ch = Channel.fromPath(
            params.taxonomy_feature_table.toString(),
            checkIfExists: true
        )
        taxonomy_canonical_mapping_ch = Channel.fromPath(
            params.taxonomy_canonical_mapping.toString(),
            checkIfExists: true
        )
        taxonomy_ncbi_ch = Channel.fromPath(
            params.taxonomy_ncbi_owl.toString(),
            checkIfExists: true
        )
        taxonomy_sra_sheet_ch = Channel.fromPath(
            params.taxonomy_sra_sheet.toString(),
            checkIfExists: true
        )
        BUILD_TAXONOMY_MAPPING(
            taxonomy_code_ch,
            taxonomy_source_ch,
            taxonomy_feature_table_ch,
            taxonomy_canonical_mapping_ch,
            taxonomy_ncbi_ch
        )
        GENERATE_TAXONOMY_ABOX(
            taxonomy_generator_ch,
            BUILD_TAXONOMY_MAPPING.out,
            taxonomy_source_ch,
            taxonomy_feature_table_ch,
            taxonomy_sra_sheet_ch,
            GENERATE_CORE_KG_MODULES.out,
            Channel.value(params.taxonomy_java_opts.toString())
        )
        KG_VALIDATE(
            project_root_ch,
            GENERATE_CORE_KG_MODULES.out,
            GENERATE_TAXONOMY_ABOX.out,
            BUILD_TAXONOMY_MAPPING.out
        )
    }

    if (params.build_papers || params.stage == "full") {
        if (
            ws_host_mode
            && (
                !params.tex_container
                || !params.tex_container.toString().contains("@sha256:")
            )
        ) {
            error "The ws_host paper build requires --tex_container with an immutable @sha256: Docker reference"
        }
        if (stageEnabled("advanced") || params.run_advanced) {
            BUILD_PAPERS(
                project_root_ch,
                ecology_paper_ch,
                RELEASE_EVIDENCE.out,
                XRF_AUDIT.out,
                SUBMISSION_FIGURES.out,
                DATA_PAPER_FIGURES.out,
                ENVIRONMENTAL_METADATA.out,
                COMPETENCY_QUERY_VALIDATION.out,
                CAPTURE_PROVENANCE.out,
                CAPTURE_EXECUTION_ENVIRONMENT.out,
                Channel.value(params.execution_mode.toString()),
                Channel.value(
                    params.tex_container
                        ? params.tex_container.toString()
                        : ""
                )
            )
        } else {
            STAGE_MANUSCRIPT_FIGURES(ecology_paper_ch)
            BUILD_PAPERS(
                project_root_ch,
                ecology_paper_ch,
                RELEASE_EVIDENCE.out,
                XRF_AUDIT.out,
                STAGE_MANUSCRIPT_FIGURES.out,
                DATA_PAPER_FIGURES.out,
                ENVIRONMENTAL_METADATA.out,
                COMPETENCY_QUERY_VALIDATION.out,
                CAPTURE_PROVENANCE.out,
                CAPTURE_EXECUTION_ENVIRONMENT.out,
                Channel.value(params.execution_mode.toString()),
                Channel.value(
                    params.tex_container
                        ? params.tex_container.toString()
                        : ""
                )
            )
        }
    }
}
