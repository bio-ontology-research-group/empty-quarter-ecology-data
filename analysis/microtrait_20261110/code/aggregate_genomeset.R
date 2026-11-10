#!/usr/bin/env Rscript
# Official microTrait genomeset matrix synthesis across all 5,438 canonical EQ MAGs.
# Calls microtrait::make.genomeset.results() and guarantees exact 5,438-row coverage
# across trait_matrixatgranularity1, trait_matrixatgranularity2, trait_matrixatgranularity3,
# hmm_matrix, and rule_matrix (including retaining any 0-HMM-hit genome with 0s across
# all hmms_fromrules columns instead of silently dropping the row).

suppressPackageStartupMessages({
  library(microtrait)
  library(gRodon)
  library(dplyr)
  library(tibble)
  library(tidyr)
  library(readr)
  library(parallel)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) {
  stop("Usage: aggregate_genomeset.R <root_dir> <ncores>")
}
root_dir <- normalizePath(args[1], mustWork = TRUE)
ncores <- as.integer(args[2])
if (is.na(ncores) || ncores < 1L) ncores <- 16L

base_tmp <- Sys.getenv("TMPDIR", unset = file.path(root_dir, "tmp", "agg_r"))
if (startsWith(base_tmp, "/tmp")) {
  base_tmp <- file.path(root_dir, "tmp", "agg_r")
}
dir.create(base_tmp, recursive = TRUE, showWarnings = FALSE)

mags_file <- file.path(root_dir, "inputs", "all_5438_mags.txt")
ids <- readLines(mags_file, warn = FALSE)
ids <- trimws(ids)
ids <- ids[nzchar(ids)]

if (length(ids) != 5438L) {
  stop(paste0("Expected 5438 canonical MAG IDs, got ", length(ids)))
}

rds_files <- file.path(root_dir, "per_mag", ids, paste0(ids, ".microtrait.rds"))
missing_rds <- rds_files[!file.exists(rds_files)]
if (length(missing_rds) > 0L) {
  stop(paste0("Missing ", length(missing_rds), " RDS files, e.g.: ", paste(head(missing_rds, 5), collapse = ", ")))
}

message("[Aggregate] Running microtrait::make.genomeset.results across ", length(ids), " RDS files with ncores=", ncores, "...")
genomeset_results <- microtrait::make.genomeset.results(
  rds_files = rds_files,
  ids = ids,
  growthrate = TRUE,
  optimumT = TRUE,
  ncores = ncores
)

# Check if any genome with 0 detected HMMs was omitted from hmm_matrix by fetch.results(type="gene")
hmm_mat <- genomeset_results$hmm_matrix
if (nrow(hmm_mat) < length(ids)) {
  missing_ids <- setdiff(ids, hmm_mat$id)
  message("[Aggregate] Backfilling ", length(missing_ids), " genome(s) with 0 detected HMMs in hmm_matrix...")
  meta_cols <- c("id", "genome_length", "mingentime", "optimumT")
  hmm_cols <- setdiff(colnames(hmm_mat), meta_cols)
  g1 <- genomeset_results$trait_matrixatgranularity1
  missing_meta <- g1 %>%
    dplyr::filter(id %in% missing_ids) %>%
    dplyr::select(dplyr::any_of(meta_cols))
  zero_block <- as.data.frame(matrix(0L, nrow = nrow(missing_meta), ncol = length(hmm_cols)))
  colnames(zero_block) <- hmm_cols
  for (col in hmm_cols) {
    if (is.factor(hmm_mat[[col]])) {
      zero_block[[col]] <- factor(0, levels = levels(hmm_mat[[col]]), ordered = is.ordered(hmm_mat[[col]]))
    }
  }
  backfill_df <- dplyr::bind_cols(
    missing_meta %>% dplyr::select(id),
    tibble::as_tibble(zero_block),
    missing_meta %>% dplyr::select(-id)
  )
  hmm_mat <- dplyr::bind_rows(hmm_mat, backfill_df)
}

# Order all 5 matrices identically to canonical `ids` and verify 5,438 rows
matrix_names <- c(
  "trait_matrixatgranularity1",
  "trait_matrixatgranularity2",
  "trait_matrixatgranularity3",
  "hmm_matrix",
  "rule_matrix"
)
genomeset_results$hmm_matrix <- hmm_mat

res_dir <- file.path(root_dir, "results")
dir.create(res_dir, recursive = TRUE, showWarnings = FALSE)

for (nm in matrix_names) {
  mat <- genomeset_results[[nm]]
  if (nrow(mat) != 5438L || length(unique(mat$id)) != 5438L || !setequal(mat$id, ids)) {
    stop(paste0("Matrix ", nm, " failed 5438 ID completeness check: nrow=", nrow(mat)))
  }
  mat <- mat[match(ids, mat$id), ]
  genomeset_results[[nm]] <- mat
  out_tsv <- file.path(res_dir, paste0(nm, ".tsv"))
  readr::write_tsv(mat, out_tsv)
  message("[Aggregate] Wrote ", out_tsv, " (", nrow(mat), " x ", ncol(mat), ")")
}

out_rds <- file.path(res_dir, "eq_5438.microtrait.genomeset_results.rds")
saveRDS(genomeset_results, file = out_rds)
message("[Aggregate] Saved official genomeset_results RDS to ", out_rds)

# Save R sessionInfo for provenance
prov_dir <- file.path(root_dir, "provenance")
dir.create(prov_dir, recursive = TRUE, showWarnings = FALSE)
writeLines(capture.output(sessionInfo()), con = file.path(prov_dir, "r_session_info.txt"))
message("[Aggregate] Completed R genomeset synthesis successfully.")
