#!/usr/bin/env Rscript
# Official microTrait per-MAG execution script with component-level validation,
# atomic core checkpointing before optional predictors, and preservation of raw evidence.
#
# Approved parameters (ROOT-PARAMETERS.txt & ROOT-UPSTREAM-PARITY-REVIEW.txt):
#   extract.traits(type="genomic", mode="meta",
#                  growthrate_predict=TRUE, optimalT_predict=TRUE,
#                  optimalT_predict_wtRNA=FALSE, save_tempfiles=TRUE)
#   Database: microtrait.hmmdb + dbcan.select.v14.hmmdb (commit b4344eb) + arcbacribosomal.hmmdb
#
# Documented wrapper error-handling differences vs raw extract.traits:
# 1. Enforces project TMPDIR at startup (`!startsWith(tempdir(), "/tmp")`).
# 2. Validates return codes and outputs of prodigal and core hmmsearch runs
#    (microtrait.hmmdb with --cut_tc and dbcan.select.v14.hmmdb), including
#    HMMER3's `# [ok]` completion sentinel in every .domtblout file so failed/truncated
#    HMM runs never silently zero-fill traits.
# 3. Handles valid 0-hit `.domtblout` files cleanly without crashing `readr::type_convert`.
# 4. Writes an atomic core checkpoint (`<id>.core.microtrait.rds` and `<id>.microtrait.rds`)
#    immediately after `microtrait::map.traits.fromdomtblout()`, BEFORE running optional
#    growth or OGT predictors.
# 5. Isolates the ENTIRE growth component (including the ribosomal `hmmsearch` call,
#    ribosomal domtblout parsing, and `gRodon::predictGrowth`) and the OGT component inside
#    `tryCatch`, recording `NA_real_` (never `NULL` or `0`) and explicit status/error fields
#    when a predictor fails or is unsupported, while preserving valid core trait results.

if (startsWith(tempdir(), "/tmp")) {
  stop(paste0("FATAL: R tempdir() resolved to /tmp (", tempdir(), "). Export project TMPDIR before starting R."))
}

suppressPackageStartupMessages({
  library(microtrait)
  library(gRodon)
  library(Biostrings)
  library(seqinr)
  library(dplyr)
  library(tibble)
  library(readr)
  library(tidyr)
  library(stringr)
  library(tictoc)
  library(fs)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) {
  stop("Usage: run_microtrait_batch.R <mag_list_file_or_single_mag> <root_dir> <hmm_threads>")
}

mag_arg <- args[1]
root_dir <- normalizePath(args[2], mustWork = TRUE)
hmm_threads <- as.integer(args[3])
if (is.na(hmm_threads) || hmm_threads < 1L) hmm_threads <- 1L

if (file.exists(mag_arg)) {
  mag_ids <- readLines(mag_arg, warn = FALSE)
  mag_ids <- trimws(mag_ids)
  mag_ids <- mag_ids[nzchar(mag_ids)]
} else {
  mag_ids <- trimws(strsplit(mag_arg, ",")[[1]])
  mag_ids <- mag_ids[nzchar(mag_ids)]
}

# Locate verified pressed HMM databases in microtrait package extdata (pinned commit b4344eb uses dbcan.select.v14.hmmdb)
pkg_extdata <- system.file("extdata", package = "microtrait", mustWork = TRUE)
hmmpress_dir <- file.path(pkg_extdata, "hmm", "hmmpress")
hmm_microtrait <- file.path(hmmpress_dir, "microtrait.hmmdb")
hmm_dbcan_v14 <- file.path(hmmpress_dir, "dbcan.select.v14.hmmdb")
hmm_ribosomal <- file.path(hmmpress_dir, "arcbacribosomal.hmmdb")

for (h in c(hmm_microtrait, hmm_dbcan_v14, hmm_ribosomal)) {
  for (ext in c(".h3f", ".h3i", ".h3m", ".h3p")) {
    if (!file.exists(paste0(h, ext))) {
      stop(paste0("Missing pressed HMM database file: ", h, ext))
    }
  }
}

empty_domtblout_tibble <- function() {
  tibble::tibble(
    gene_name = character(),
    gene_accession = character(),
    gene_len = integer(),
    hmm_name = character(),
    hmm_accession = character(),
    hmm_qlen = integer(),
    hmm_evalue = double(),
    hmm_score = double(),
    hmm_bias = double(),
    gene_N = integer(),
    gene_of = integer(),
    gene_cevalue = double(),
    gene_ievalue = double(),
    gene_score = double(),
    gene_bias = double(),
    hmm_from = integer(),
    hmm_to = integer(),
    gene_from = integer(),
    gene_to = integer(),
    env_from = integer(),
    env_to = integer(),
    acc = double()
  )
}

read_verified_domtblout <- function(domtblout_file) {
  if (!file.exists(domtblout_file)) {
    stop(paste0("domtblout file does not exist: ", domtblout_file))
  }
  lines <- readLines(domtblout_file, warn = FALSE)
  if (length(lines) == 0L || !any(grepl("^# \\[ok\\]\\s*$", tail(lines, 5)))) {
    stop(paste0("domtblout file missing HMMER3 '# [ok]' completion sentinel: ", domtblout_file))
  }
  data_lines <- lines[!grepl("^#", lines) & nzchar(trimws(lines))]
  if (length(data_lines) == 0L) {
    return(list(tbl = empty_domtblout_tibble(), n_raw_hits = 0L))
  }
  tbl <- suppressWarnings(microtrait::read.domtblout(domtblout_file))
  list(tbl = tbl, n_raw_hits = nrow(tbl))
}

json_escape <- function(x) {
  if (length(x) == 0L || is.null(x) || is.na(x)) return("null")
  s <- as.character(x)[1]
  s <- gsub("\\\\", "\\\\\\\\", s)
  s <- gsub("\"", "\\\\\"", s)
  s <- gsub("\n", "\\\\n", s)
  s <- gsub("\r", "\\\\r", s)
  s <- gsub("\t", "\\\\t", s)
  paste0("\"", s, "\"")
}

num_or_null <- function(x) {
  if (length(x) == 0L || is.null(x) || is.na(x) || !is.finite(as.numeric(x)[1])) return("null")
  format(as.numeric(x)[1], digits = 10, scientific = FALSE)
}

bool_json <- function(x) {
  if (length(x) == 0L || is.null(x) || is.na(x)) return("null")
  ifelse(isTRUE(as.logical(x)[1]), "true", "false")
}

write_status_json <- function(status_list, out_path) {
  fields <- c(
    sprintf("  \"mag\": %s", json_escape(status_list$mag)),
    sprintf("  \"overall_status\": %s", json_escape(status_list$overall_status)),
    sprintf("  \"prodigal_status\": %s", json_escape(status_list$prodigal_status)),
    sprintf("  \"microtrait_hmm_status\": %s", json_escape(status_list$microtrait_hmm_status)),
    sprintf("  \"dbcan_hmm_status\": %s", json_escape(status_list$dbcan_hmm_status)),
    sprintf("  \"dbcan_version\": %s", json_escape(status_list$dbcan_version)),
    sprintf("  \"rules_traits_status\": %s", json_escape(status_list$rules_traits_status)),
    sprintf("  \"core_checkpoint_saved\": %s", bool_json(status_list$core_checkpoint_saved)),
    sprintf("  \"ribosomal_hmm_status\": %s", json_escape(status_list$ribosomal_hmm_status)),
    sprintf("  \"growth_status\": %s", json_escape(status_list$growth_status)),
    sprintf("  \"ogt_status\": %s", json_escape(status_list$ogt_status)),
    sprintf("  \"prodigal_mode\": %s", json_escape(status_list$prodigal_mode)),
    sprintf("  \"ogt_model\": %s", json_escape(status_list$ogt_model)),
    sprintf("  \"optimalT_predict_wtRNA\": %s", bool_json(status_list$optimalT_predict_wtRNA)),
    sprintf("  \"genome_length\": %s", num_or_null(status_list$genome_length)),
    sprintf("  \"norfs\": %s", num_or_null(status_list$norfs)),
    sprintf("  \"n_microtrait_domtblout_hits\": %s", num_or_null(status_list$n_microtrait_domtblout_hits)),
    sprintf("  \"n_genes_detected\": %s", num_or_null(status_list$n_genes_detected)),
    sprintf("  \"n_dbcan_domtblout_hits\": %s", num_or_null(status_list$n_dbcan_domtblout_hits)),
    sprintf("  \"n_domains_detected\": %s", num_or_null(status_list$n_domains_detected)),
    sprintf("  \"n_rules_total\": %s", num_or_null(status_list$n_rules_total)),
    sprintf("  \"n_rules_asserted_true\": %s", num_or_null(status_list$n_rules_asserted_true)),
    sprintf("  \"n_traits_granularity1_nonzero\": %s", num_or_null(status_list$n_traits_granularity1_nonzero)),
    sprintf("  \"n_traits_granularity2_nonzero\": %s", num_or_null(status_list$n_traits_granularity2_nonzero)),
    sprintf("  \"n_traits_granularity3_nonzero\": %s", num_or_null(status_list$n_traits_granularity3_nonzero)),
    sprintf("  \"n_ribosomal_domtblout_hits\": %s", num_or_null(status_list$n_ribosomal_domtblout_hits)),
    sprintf("  \"n_highly_expressed_genes\": %s", num_or_null(status_list$n_highly_expressed_genes)),
    sprintf("  \"growthrate_d_hours\": %s", num_or_null(status_list$growthrate_d_hours)),
    sprintf("  \"growthrate_LowerCI\": %s", num_or_null(status_list$growthrate_LowerCI)),
    sprintf("  \"growthrate_UpperCI\": %s", num_or_null(status_list$growthrate_UpperCI)),
    sprintf("  \"growthrate_CUBHE\": %s", num_or_null(status_list$growthrate_CUBHE)),
    sprintf("  \"growthrate_ConsistencyHE\": %s", num_or_null(status_list$growthrate_ConsistencyHE)),
    sprintf("  \"growthrate_CPB\": %s", num_or_null(status_list$growthrate_CPB)),
    sprintf("  \"growth_warning\": %s", json_escape(status_list$growth_warning)),
    sprintf("  \"growth_error\": %s", json_escape(status_list$growth_error)),
    sprintf("  \"ogt_celsius\": %s", num_or_null(status_list$ogt_celsius)),
    sprintf("  \"ogt_error\": %s", json_escape(status_list$ogt_error)),
    sprintf("  \"elapsed_seconds\": %s", num_or_null(status_list$elapsed_seconds)),
    sprintf("  \"rds_file\": %s", json_escape(status_list$rds_file)),
    sprintf("  \"core_rds_file\": %s", json_escape(status_list$core_rds_file)),
    sprintf("  \"error_message\": %s", json_escape(status_list$error_message))
  )
  tmp_path <- paste0(out_path, ".tmp")
  writeLines(c("{", paste(fields, collapse = ",\n"), "}"), con = tmp_path)
  file.rename(tmp_path, out_path)
}

atomic_save_rds <- function(obj, path) {
  tmp_p <- paste0(path, ".tmp")
  saveRDS(obj, file = tmp_p)
  file.rename(tmp_p, path)
}

process_one_mag <- function(id) {
  t_start <- proc.time()[["elapsed"]]
  fasta_file <- file.path(root_dir, "inputs", "fastas", paste0(id, ".fa"))
  out_dir <- file.path(root_dir, "per_mag", id)
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

  rds_file <- file.path(out_dir, paste0(id, ".microtrait.rds"))
  core_rds_file <- file.path(out_dir, paste0(id, ".core.microtrait.rds"))
  status_file <- file.path(out_dir, paste0(id, ".status.json"))
  done_file <- file.path(out_dir, "DONE")

  if (file.exists(done_file) && file.exists(rds_file) && file.exists(status_file)) {
    chk <- tryCatch(readRDS(rds_file), error = function(e) NULL)
    if (!is.null(chk) && !is.null(chk$trait_counts_atgranularity3) && identical(chk$id, id)) {
      message("[SKIP] Already completed and verified: ", id)
      return(invisible(TRUE))
    }
  }

  status <- list(
    mag = id,
    overall_status = "running",
    prodigal_status = "not_run",
    microtrait_hmm_status = "not_run",
    dbcan_hmm_status = "not_run",
    dbcan_version = "v14",
    rules_traits_status = "not_run",
    core_checkpoint_saved = FALSE,
    ribosomal_hmm_status = "not_run",
    growth_status = "not_run",
    ogt_status = "not_run",
    prodigal_mode = "meta",
    ogt_model = "genomic+ORF+protein",
    optimalT_predict_wtRNA = FALSE,
    genome_length = NA_real_,
    norfs = NA_integer_,
    n_microtrait_domtblout_hits = NA_integer_,
    n_genes_detected = NA_integer_,
    n_dbcan_domtblout_hits = NA_integer_,
    n_domains_detected = NA_integer_,
    n_rules_total = NA_integer_,
    n_rules_asserted_true = NA_integer_,
    n_traits_granularity1_nonzero = NA_integer_,
    n_traits_granularity2_nonzero = NA_integer_,
    n_traits_granularity3_nonzero = NA_integer_,
    n_ribosomal_domtblout_hits = NA_integer_,
    n_highly_expressed_genes = NA_integer_,
    growthrate_d_hours = NA_real_,
    growthrate_LowerCI = NA_real_,
    growthrate_UpperCI = NA_real_,
    growthrate_CUBHE = NA_real_,
    growthrate_ConsistencyHE = NA_real_,
    growthrate_CPB = NA_real_,
    growth_warning = NA_character_,
    growth_error = NA_character_,
    ogt_celsius = NA_real_,
    ogt_error = NA_character_,
    elapsed_seconds = NA_real_,
    rds_file = NA_character_,
    core_rds_file = NA_character_,
    error_message = NA_character_
  )

  tryCatch({
    if (!file.exists(fasta_file)) {
      stop(paste0("Input FASTA does not exist: ", fasta_file))
    }

    tictoc::tic.clearlog()
    tictoc::tic("extract.traits")

    # 1. Read genome & run Prodigal in approved mode="meta"
    tictoc::tic("run.prodigal")
    fasta_seq <- seqinr::read.fasta(file = fasta_file, seqtype = "DNA", as.string = TRUE, forceDNAtolower = FALSE, seqonly = TRUE)
    genome_length <- sum(seqinr::getLength(fasta_seq))
    status$genome_length <- genome_length

    cds_file <- file.path(out_dir, paste0(id, ".prodigal.fa"))
    proteins_file <- file.path(out_dir, paste0(id, ".prodigal.faa"))
    gff_file <- file.path(out_dir, paste0(id, ".prodigal.gff"))
    prod_err_file <- file.path(out_dir, paste0(id, ".prodigal.stderr"))

    rc_prod <- system2(
      "prodigal",
      args = c(
        "-f", "gff",
        "-q",
        "-g", "11",
        "-p", "meta",
        "-i", fasta_file,
        "-d", cds_file,
        "-a", proteins_file,
        "-o", gff_file
      ),
      stdout = "/dev/null",
      stderr = prod_err_file
    )
    tictoc::toc(log = TRUE)

    if (rc_prod != 0L || !file.exists(proteins_file) || !file.exists(cds_file)) {
      status$prodigal_status <- paste0("failed_exit_", rc_prod)
      stop(paste0("Prodigal failed with exit code ", rc_prod))
    }

    aa_set <- Biostrings::readAAStringSet(proteins_file)
    dna_set <- Biostrings::readDNAStringSet(cds_file)
    nseq <- length(aa_set)
    status$norfs <- nseq

    if (nseq == 0L || length(dna_set) != nseq) {
      status$prodigal_status <- ifelse(nseq == 0L, "failed_zero_orfs", "failed_cds_protein_mismatch")
      stop(paste0("Prodigal produced invalid ORF inventory: norfs=", nseq, ", ncds=", length(dna_set)))
    }
    status$prodigal_status <- "ok"

    # 2. Run HMMER searches for microtrait (with --cut_tc) and official dbCAN V14
    tictoc::tic("run.hmmsearch")
    microtrait_domtblout_file <- file.path(out_dir, paste0(id, ".microtrait.domtblout"))
    dbcan_domtblout_file <- file.path(out_dir, paste0(id, ".dbcan.domtblout"))

    rc_mt <- system2(
      "hmmsearch",
      args = c(
        "--domtblout", microtrait_domtblout_file,
        "--cpu", as.character(hmm_threads),
        "--noali",
        "--cut_tc",
        hmm_microtrait,
        proteins_file
      ),
      stdout = "/dev/null",
      stderr = file.path(out_dir, paste0(id, ".microtrait.hmmsearch.stderr"))
    )
    if (rc_mt != 0L) {
      status$microtrait_hmm_status <- paste0("failed_exit_", rc_mt)
      stop(paste0("microtrait hmmsearch failed with exit code ", rc_mt))
    }

    rc_dbcan <- system2(
      "hmmsearch",
      args = c(
        "--domtblout", dbcan_domtblout_file,
        "--cpu", as.character(hmm_threads),
        "--noali",
        hmm_dbcan_v14,
        proteins_file
      ),
      stdout = "/dev/null",
      stderr = file.path(out_dir, paste0(id, ".dbcan.hmmsearch.stderr"))
    )
    if (rc_dbcan != 0L) {
      status$dbcan_hmm_status <- paste0("failed_exit_", rc_dbcan)
      stop(paste0("dbcan v14 hmmsearch failed with exit code ", rc_dbcan))
    }
    tictoc::toc(log = TRUE)

    # 3. Parse verified core domtblout files (must have HMMER3 '# [ok]' footer)
    tictoc::tic("read.domtblout")
    mt_parsed <- read_verified_domtblout(microtrait_domtblout_file)
    microtrait_domtblout <- mt_parsed$tbl
    status$n_microtrait_domtblout_hits <- mt_parsed$n_raw_hits
    status$microtrait_hmm_status <- "ok"

    dbcan_parsed <- read_verified_domtblout(dbcan_domtblout_file)
    dbcan_domtblout <- dbcan_parsed$tbl
    status$n_dbcan_domtblout_hits <- dbcan_parsed$n_raw_hits
    status$dbcan_hmm_status <- "ok"
    tictoc::toc(log = TRUE)

    # 4. Official microTrait rule assertion & trait granularity 1/2/3 mapping
    tictoc::tic("map.traits.fromdomtblout")
    map.traits.result <- microtrait::map.traits.fromdomtblout(microtrait_domtblout, dbcan_domtblout)
    tictoc::toc(log = TRUE)

    if (
      is.null(map.traits.result$rules_asserted) ||
      is.null(map.traits.result$trait_counts_atgranularity1) ||
      is.null(map.traits.result$trait_counts_atgranularity2) ||
      is.null(map.traits.result$trait_counts_atgranularity3)
    ) {
      status$rules_traits_status <- "failed_null_trait_tables"
      stop("map.traits.fromdomtblout returned NULL rule or trait table")
    }
    status$n_genes_detected <- length(map.traits.result$genes_detected)
    status$n_domains_detected <- length(map.traits.result$domains_detected)
    status$n_rules_total <- nrow(map.traits.result$rules_asserted)
    status$n_rules_asserted_true <- sum(map.traits.result$rules_asserted$`microtrait_rule-asserted` == TRUE, na.rm = TRUE)
    status$n_traits_granularity1_nonzero <- sum(map.traits.result$trait_counts_atgranularity1$`microtrait_trait-value` > 0, na.rm = TRUE)
    status$n_traits_granularity2_nonzero <- sum(map.traits.result$trait_counts_atgranularity2$`microtrait_trait-value` > 0, na.rm = TRUE)
    status$n_traits_granularity3_nonzero <- sum(map.traits.result$trait_counts_atgranularity3$`microtrait_trait-value` > 0, na.rm = TRUE)
    status$rules_traits_status <- "ok"

    # Populate core fields and NA_real_ defaults for continuous predictors,
    # then save atomic core checkpoint BEFORE optional growth/OGT predictors!
    map.traits.result$id <- id
    map.traits.result$cds_file <- cds_file
    map.traits.result$proteins_file <- proteins_file
    map.traits.result$genome_length <- genome_length
    map.traits.result$norfs <- nseq
    map.traits.result$growthrate_CUBHE <- NA_real_
    map.traits.result$growthrate_ConsistencyHE <- NA_real_
    map.traits.result$growthrate_CPB <- NA_real_
    map.traits.result$growthrate_d <- NA_real_
    map.traits.result$growthrate_LowerCI <- NA_real_
    map.traits.result$growthrate_UpperCI <- NA_real_
    map.traits.result$growthrate_FilteredSequences <- NA_integer_
    map.traits.result$nhighlyexpressed <- NA_integer_
    map.traits.result$highlyexpressed_genes <- character(0)
    map.traits.result$allfeatures <- NULL
    map.traits.result$ogt <- NA_real_
    map.traits.result$time_log <- tictoc::tic.log()

    atomic_save_rds(map.traits.result, core_rds_file)
    atomic_save_rds(map.traits.result, rds_file)
    status$core_checkpoint_saved <- TRUE
    status$core_rds_file <- core_rds_file
    status$rds_file <- rds_file

    # 5. Growth prediction (entire component including ribosomal hmmsearch isolated in tryCatch)
    tictoc::tic("run.predictGrowth")
    tryCatch({
      ribosomal_domtblout_file <- file.path(out_dir, paste0(id, ".ribosomalproteins.domtblout"))
      rc_rib <- system2(
        "hmmsearch",
        args = c(
          "--domtblout", ribosomal_domtblout_file,
          "--cpu", as.character(hmm_threads),
          "--noali",
          "--cut_ga",
          hmm_ribosomal,
          proteins_file
        ),
        stdout = "/dev/null",
        stderr = file.path(out_dir, paste0(id, ".ribosomal.hmmsearch.stderr"))
      )
      if (rc_rib != 0L) {
        status$ribosomal_hmm_status <- paste0("failed_exit_", rc_rib)
        stop(paste0("ribosomal hmmsearch failed with exit code ", rc_rib))
      }
      rib_parsed <- read_verified_domtblout(ribosomal_domtblout_file)
      ribosomal_domtblout <- rib_parsed$tbl
      status$n_ribosomal_domtblout_hits <- rib_parsed$n_raw_hits
      status$ribosomal_hmm_status <- "ok"

      genes_dna <- Biostrings::readDNAStringSet(cds_file)
      names(genes_dna) <- sub(" .*", "", names(genes_dna))
      highlyexpressed_genes <- dplyr::pull(ribosomal_domtblout, `gene_name`)
      highlyexpressed_logical <- names(genes_dna) %in% highlyexpressed_genes
      nhighlyexpressed <- length(which(highlyexpressed_logical == TRUE))
      status$n_highly_expressed_genes <- nhighlyexpressed
      map.traits.result$nhighlyexpressed <- length(highlyexpressed_genes)
      map.traits.result$highlyexpressed_genes <- highlyexpressed_genes

      if (nhighlyexpressed == 0L) {
        status$growth_status <- "na_zero_ribosomal_genes"
        status$growth_error <- "No ribosomal protein genes detected at --cut_ga; gRodon requires >=1 highly expressed gene"
      } else {
        g_try <- microtrait:::myTryCatch(
          gRodon::predictGrowth(
            genes_dna,
            highlyexpressed_logical,
            mode = "full",
            temperature = "none",
            training_set = "vs",
            depth_of_coverage = NULL,
            fragments = FALSE
          )
        )
        if (!is.null(g_try$warning)) {
          status$growth_warning <- conditionMessage(g_try$warning)
        }
        if (!is.null(g_try$error) || is.null(g_try$value)) {
          status$growth_status <- "failed_grodon_error"
          status$growth_error <- if (!is.null(g_try$error)) conditionMessage(g_try$error) else "gRodon returned NULL"
        } else {
          gv <- g_try$value
          map.traits.result$growthrate_CUBHE <- as.numeric(gv$CUBHE)[1]
          map.traits.result$growthrate_ConsistencyHE <- as.numeric(gv$ConsistencyHE)[1]
          map.traits.result$growthrate_CPB <- as.numeric(gv$CPB)[1]
          map.traits.result$growthrate_FilteredSequences <- as.integer(gv$FilteredSequences)[1]
          map.traits.result$growthrate_d <- as.numeric(gv$d)[1]
          map.traits.result$growthrate_LowerCI <- as.numeric(gv$LowerCI)[1]
          map.traits.result$growthrate_UpperCI <- as.numeric(gv$UpperCI)[1]

          status$growthrate_CUBHE <- map.traits.result$growthrate_CUBHE
          status$growthrate_ConsistencyHE <- map.traits.result$growthrate_ConsistencyHE
          status$growthrate_CPB <- map.traits.result$growthrate_CPB
          status$growthrate_d_hours <- map.traits.result$growthrate_d
          status$growthrate_LowerCI <- map.traits.result$growthrate_LowerCI
          status$growthrate_UpperCI <- map.traits.result$growthrate_UpperCI

          if (is.na(map.traits.result$growthrate_d) || !is.finite(map.traits.result$growthrate_d)) {
            status$growth_status <- "na_nonfinite_prediction"
          } else if (nhighlyexpressed < 10L) {
            status$growth_status <- "ok_low_ribosomal_count_lt10"
          } else {
            status$growth_status <- "ok"
          }
        }
      }
    }, error = function(ge) {
      if (identical(status$ribosomal_hmm_status, "not_run")) {
        status$ribosomal_hmm_status <<- "failed"
      }
      status$growth_status <<- "failed_growth_component_error"
      status$growth_error <<- conditionMessage(ge)
    })
    map.traits.result$growth_status <- status$growth_status
    map.traits.result$growth_warning <- status$growth_warning
    map.traits.result$growth_error <- status$growth_error
    tictoc::toc(log = TRUE)

    # 6. OGT prediction (approved default optimalT_predict_wtRNA = FALSE -> genomic+ORF+protein)
    tictoc::tic("run_ogtmodel")
    ogt_try <- microtrait:::myTryCatch({
      allfeatures <- microtrait::extract_features(
        genome_file = fasta_file,
        cds_file = cds_file,
        proteins_file = proteins_file,
        tRNA = FALSE
      )
      write.table(
        allfeatures[, -1],
        sep = "\t",
        quote = FALSE,
        row.names = FALSE,
        col.names = FALSE,
        file = file.path(out_dir, paste0(id, ".allfeatures.txt"))
      )
      ogt_val <- microtrait::run_ogtmodel(allfeatures, model = "genomic+ORF+protein")
      list(allfeatures = allfeatures, ogt = as.numeric(ogt_val)[1])
    })
    if (!is.null(ogt_try$error) || is.null(ogt_try$value)) {
      status$ogt_status <- "failed_ogt_error"
      status$ogt_error <- if (!is.null(ogt_try$error)) conditionMessage(ogt_try$error) else "run_ogtmodel returned NULL"
    } else {
      map.traits.result$allfeatures <- ogt_try$value$allfeatures
      map.traits.result$ogt <- ogt_try$value$ogt
      status$ogt_celsius <- map.traits.result$ogt
      if (is.na(map.traits.result$ogt) || !is.finite(map.traits.result$ogt)) {
        status$ogt_status <- "na_nonfinite_prediction"
      } else {
        status$ogt_status <- "ok"
      }
    }
    map.traits.result$ogt_status <- status$ogt_status
    map.traits.result$ogt_model <- "genomic+ORF+protein"
    map.traits.result$ogt_error <- status$ogt_error
    tictoc::toc(log = TRUE)

    tictoc::toc(log = TRUE)

    # 7. Finalize official microTrait RDS structure
    map.traits.result$time_log <- tictoc::tic.log()
    atomic_save_rds(map.traits.result, rds_file)

    status$elapsed_seconds <- round(proc.time()[["elapsed"]] - t_start, 3)
    if (status$growth_status %in% c("ok", "ok_low_ribosomal_count_lt10") && status$ogt_status == "ok") {
      status$overall_status <- "complete_all_components"
    } else {
      status$overall_status <- "complete_traits_partial_continuous_predictors"
    }
    write_status_json(status, status_file)
    file.create(done_file)
    message("[DONE] ", id, " (", status$overall_status, ", ", status$elapsed_seconds, "s)")
  }, error = function(e) {
    status$elapsed_seconds <- round(proc.time()[["elapsed"]] - t_start, 3)
    status$overall_status <- "failed"
    status$error_message <- conditionMessage(e)
    write_status_json(status, status_file)
    message("[ERROR] ", id, ": ", conditionMessage(e))
  })
}

for (m in mag_ids) {
  process_one_mag(m)
}

failed_mags <- character()
for (m in mag_ids) {
  done_p <- file.path(root_dir, "per_mag", m, "DONE")
  if (!file.exists(done_p)) {
    failed_mags <- c(failed_mags, m)
  }
}
if (length(failed_mags) > 0L) {
  stop(paste0("Worker had ", length(failed_mags), " failed MAG(s): ", paste(failed_mags, collapse = ", ")))
}
