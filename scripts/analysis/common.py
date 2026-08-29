"""
Common data loading and metadata parsing for all v2 RQ analysis scripts.
Updated for Trips 1-5 with PICRUST2 functional data and XRF combined.

Handles all 5 trip prefixes:
  Trip 1: no prefix (e.g., 61PRr1)
  Trip 2: T prefix (e.g., T1PRr3)
  Trip 3: F prefix (e.g., F21Dr1)
  Trip 4: S prefix (e.g., S41Sr2)
  Trip 5: V prefix (e.g., V1Dr1)
"""

import pandas as pd
import numpy as np
import os
import re
import sys
import warnings

# --- Configuration ---
# Resolve project root (two levels up from analysis/v2/)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# Paths
FT_PATH = os.path.join(DATA_DIR, "processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv")
TAX_PATH = os.path.join(DATA_DIR, "processed/taxonomy/taxon-tables/taxonomy-trips1-5.tsv")
# Complete Trip-5 laboratory table (178 selected sample sheets). The legacy
# xrf_lab_combined.tsv silently omitted 20 records and is retained only for
# provenance/audit comparisons.
XRF_PATH = os.path.join(
    DATA_DIR, "processed/geochemistry/xrf_lab_table_filtered.tsv"
)
GEO_DIR = os.path.join(DATA_DIR, "metadata/geodata")
PICRUST2_DIR = os.path.join(DATA_DIR, "processed/functional/picrust2/merged")
CLIMATE_PATH = os.path.join(DATA_DIR, "processed/climate/monthly_weather_averages.tsv")

# Trip prefix -> trip number
TRIP_PREFIX_MAP = {"": 1, "T": 2, "F": 3, "S": 4, "V": 5}
TRIP_SEASON_MAP = {1: "Spring", 2: "Summer", 3: "Winter", 4: "Summer", 5: "Autumn"}
SOIL_TYPE_MAP = {"S": "Surface", "D": "Deep", "P": "Rhizosphere"}

# Sample ID regex
SAMPLE_REGEX = re.compile(
    r"^(?:e\d+_)?([TFSV])?(\d+)(PR|[PDS])r(\d+)(O|T|RE|R)?$"
)

# XRF metadata columns (not analyte data)
XRF_META_COLS = {"SoilType", "Material", "Mode", "Diameter", "Method"}

# Elements to use for analysis (excludes rare earths with many zeros)
XRF_MAJOR_ELEMENTS = [
    "Al", "Ba", "Ca", "Cl", "Cr", "Cu", "Fe", "K", "Mg", "Mn",
    "Mo", "Na", "Ni", "P", "S", "Si", "Sr", "Ti", "V", "Zn", "Zr"
]


def parse_sample_id(sid):
    """Parse a sample ID into components. Returns dict or None."""
    m = SAMPLE_REGEX.match(sid)
    if not m:
        return None
    prefix = m.group(1) or ""
    site = m.group(2)
    stype = m.group(3)
    rep = m.group(4)
    suffix = m.group(5) or ""
    trip = TRIP_PREFIX_MAP.get(prefix, 0)
    if stype == "PR":
        stype = "P"
    full_type = SOIL_TYPE_MAP.get(stype, stype)
    season = TRIP_SEASON_MAP.get(trip, "Unknown")
    try:
        site_int = int(site)
    except ValueError:
        site_int = site
    return {
        "SampleID": sid,
        "Trip": trip,
        "Site": site_int,
        "Type": full_type,
        "Rep": int(rep),
        "Suffix": suffix,
        "Season": season,
    }


def parse_metadata(sample_ids, climate_map=None):
    """Parse metadata from sample IDs, optionally joining with climate data."""
    rows = []
    for sid in sample_ids:
        parsed = parse_sample_id(sid)
        if parsed is None:
            rows.append({"SampleID": sid, "Trip": 0, "Site": 0, "Type": "Unknown",
                         "Season": "Unknown", "Rep": 0, "Suffix": ""})
            continue
        if climate_map:
            clim = climate_map.get((parsed["Trip"], str(parsed["Site"])), {})
            parsed["Precip"] = clim.get("Precip")
            parsed["Temp"] = clim.get("Temp")
            parsed["Lat"] = clim.get("Lat")
            parsed["Lon"] = clim.get("Lon")
        rows.append(parsed)
    return pd.DataFrame(rows).set_index("SampleID")


def load_climate_data():
    """Load climate/geodata for all trips. Returns dict of (trip, site) -> values."""
    climate = {}
    for t in range(1, 6):
        path = os.path.join(GEO_DIR, f"trip{t}_geodata.tsv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, sep="\t")
        for _, r in df.iterrows():
            try:
                site = str(int(float(r["Site"]))) if pd.notna(r.get("Site")) else None
                if site is None:
                    continue
                entry = {}
                # Try common column names
                for col in ["AnnualTotalPrecip", "Precip", "TotalPrecip"]:
                    if col in r and pd.notna(r[col]):
                        entry["Precip"] = float(r[col])
                        break
                for col in ["AnnualMeanTemp", "Temp", "MeanTemp"]:
                    if col in r and pd.notna(r[col]):
                        entry["Temp"] = float(r[col])
                        break
                if "Latitude" in r and pd.notna(r["Latitude"]):
                    entry["Lat"] = float(r["Latitude"])
                    entry["Lon"] = float(r["Longitude"])
                climate[(t, site)] = entry
            except (ValueError, KeyError):
                pass
    return climate


def load_feature_table(path=None, min_reads=None):
    """Load feature table (ASVs x Samples), removing controls."""
    path = path or FT_PATH
    print(f"Loading feature table from {path}...")
    # Skip the "# Constructed from biom file" comment line; header is "#OTU ID ..."
    ft = pd.read_csv(path, sep="\t", index_col=0, skiprows=[0])
    if "Taxon" in ft.columns:
        ft = ft.drop(columns=["Taxon"])
    # Remove control samples
    sample_cols = [c for c in ft.columns
                   if not c.startswith("EB") and not c.startswith("Negative")]
    ft = ft[sample_cols]
    # Optional minimum read depth filter
    if min_reads is not None:
        depths = ft.sum(axis=0)
        keep = depths[depths >= min_reads].index
        removed = len(ft.columns) - len(keep)
        if removed > 0:
            print(f"  Removed {removed} samples with <{min_reads} reads")
        ft = ft[keep]
    # Remove ASVs with zero total
    ft = ft.loc[ft.sum(axis=1) > 0]
    print(f"  {ft.shape[0]} ASVs x {ft.shape[1]} samples")
    return ft


def load_taxonomy(path=None):
    """Load taxonomy table."""
    path = path or TAX_PATH
    print(f"Loading taxonomy from {path}...")
    tax = pd.read_csv(path, sep="\t", index_col=0)
    return tax


def load_xrf_data(path=None, aggregate_by=None):
    """
    Load XRF lab data.

    Args:
        path: Path to XRF TSV file
        aggregate_by: None (return per-sample), 'site' (mean per site),
                      'site_type' (mean per site+compartment)
    Returns:
        DataFrame with numeric analyte columns, plus SoilType if not aggregated
    """
    path = path or XRF_PATH
    if not os.path.exists(path):
        print("XRF data file not found!")
        return pd.DataFrame()
    print(f"Loading XRF data from {path}...")
    xrf = pd.read_csv(path, sep="\t", index_col=0)

    # Separate metadata and numeric columns
    meta_present = [c for c in XRF_META_COLS if c in xrf.columns]
    numeric_cols = [c for c in xrf.columns if c not in XRF_META_COLS]

    soil_type = xrf["SoilType"] if "SoilType" in xrf.columns else None
    xrf_numeric = xrf[numeric_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # Parse site number from sample IDs (handles both V-prefix and plain)
    sites = []
    types = []
    for sid in xrf_numeric.index:
        m = re.match(r"^V?(\d+)(PR|[PDS])r(\d+)", str(sid))
        if m:
            sites.append(int(m.group(1)))
            stype = m.group(2)
            if stype == "PR":
                stype = "P"
            types.append(SOIL_TYPE_MAP.get(stype, stype))
        else:
            sites.append(None)
            types.append(None)

    xrf_numeric["Site"] = sites
    xrf_numeric["Type"] = types
    if soil_type is not None:
        xrf_numeric["SoilType"] = soil_type
    xrf_numeric = xrf_numeric.dropna(subset=["Site"])
    xrf_numeric["Site"] = xrf_numeric["Site"].astype(int)

    if aggregate_by == "site":
        analyte_cols = [c for c in xrf_numeric.columns if c not in {"Site", "Type", "SoilType"}]
        result = xrf_numeric.groupby("Site")[analyte_cols].mean()
        print(f"  XRF data for {len(result)} sites (aggregated by site)")
        return result
    elif aggregate_by == "site_type":
        analyte_cols = [c for c in xrf_numeric.columns if c not in {"Site", "Type", "SoilType"}]
        result = xrf_numeric.groupby(["Site", "Type"])[analyte_cols].mean()
        print(f"  XRF data for {len(result)} site-type combinations")
        return result

    print(f"  XRF data: {len(xrf_numeric)} samples")
    return xrf_numeric


def _load_picrust2_table(path, label):
    """Helper to load a PICRUST2 table, strip prefixes, average duplicates, remove controls."""
    print(f"Loading PICRUST2 {label} from {path}...")
    df = pd.read_csv(path, sep="\t", index_col=0)
    # Strip e#### prefix from column names to match sample IDs
    df.columns = [re.sub(r"^e\d+_", "", c) for c in df.columns]
    # Remove controls
    df = df[[c for c in df.columns if not c.startswith("EB") and not c.startswith("Negative")]]
    # Average duplicate sequencing runs
    if df.columns.duplicated().any():
        n_dups = df.columns.duplicated().sum()
        print(f"  Averaging {n_dups} duplicate run columns...")
        df = df.T.groupby(level=0).mean().T
    print(f"  {df.shape[0]} {label} x {df.shape[1]} samples")
    return df


def load_picrust2_pathways(path=None):
    """Load PICRUST2 MetaCyc pathway abundance table."""
    path = path or os.path.join(PICRUST2_DIR, "path_abun_unstrat.tsv")
    return _load_picrust2_table(path, "pathways")


def load_picrust2_ko(path=None):
    """Load PICRUST2 KEGG Ortholog abundance table."""
    path = path or os.path.join(PICRUST2_DIR, "ko_metagenome_unstrat.tsv")
    return _load_picrust2_table(path, "KOs")


def load_picrust2_ec(path=None):
    """Load PICRUST2 EC number abundance table."""
    path = path or os.path.join(PICRUST2_DIR, "ec_metagenome_unstrat.tsv")
    return _load_picrust2_table(path, "ECs")


def load_picrust2_nsti(path=None):
    """Load PICRUST2 weighted NSTI scores."""
    path = path or os.path.join(PICRUST2_DIR, "weighted_nsti.tsv")
    df = pd.read_csv(path, sep="\t", index_col=0)
    df.index = [re.sub(r"^e\d+_", "", i) for i in df.index]
    return df


def load_picrust2_metadata(path=None):
    """Load unified PICRUST2 sample metadata."""
    path = path or os.path.join(PICRUST2_DIR, "sample_metadata.tsv")
    df = pd.read_csv(path, sep="\t")
    return df


def clr_transform(df):
    """Centered Log-Ratio transformation (rows are samples, columns are features)."""
    vals = df.values.copy().astype(float)
    if vals.size == 0:
        return df.copy()
    # Add pseudocount
    if vals.max() > 100:
        vals = vals + 1
    else:
        vals = vals + 1e-6
    gm = np.exp(np.mean(np.log(vals), axis=1))
    return pd.DataFrame(
        np.log(vals / gm[:, np.newaxis]),
        index=df.index, columns=df.columns
    )


def relative_abundance(ft):
    """Convert counts to relative abundance (columns are samples)."""
    return ft.div(ft.sum(axis=0), axis=1)


def filter_prevalence(ft, min_prevalence=0.01):
    """Keep ASVs present in at least min_prevalence fraction of samples."""
    prevalence = (ft > 0).sum(axis=1) / ft.shape[1]
    keep = prevalence[prevalence >= min_prevalence].index
    print(f"  Prevalence filter ({min_prevalence}): {len(ft)} -> {len(keep)} ASVs")
    return ft.loc[keep]


def parse_taxonomy_ranks(tax):
    """Parse semicolon-delimited taxonomy into rank columns.
    Format: Kingdom;Phylum;Class;Order;Family;Genus;Species;Confidence
    (No rank prefixes like d__, p__, etc.)
    """
    ranks = ["Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species"]
    splits = tax["Taxon"].str.split(";", expand=True)
    # Assign rank names (may have more columns like confidence)
    for i, rank in enumerate(ranks):
        if i < splits.shape[1]:
            splits = splits.rename(columns={i: rank})
    # Clean empty strings
    for col in ranks:
        if col in splits.columns:
            splits[col] = splits[col].replace("", np.nan).str.strip()
    return splits


def aggregate_by_genus(ft, tax):
    """Aggregate feature table to genus level."""
    tax_aligned = tax.loc[tax.index.intersection(ft.index)]
    ranks = parse_taxonomy_ranks(tax_aligned)
    genera = ranks["Genus"].dropna()
    genera = genera[genera != ""]
    ft_g = ft.loc[genera.index].copy()
    ft_g["Genus"] = genera.values
    return ft_g.groupby("Genus").sum()


def aggregate_by_phylum(ft, tax):
    """Aggregate feature table to phylum level."""
    tax_aligned = tax.loc[tax.index.intersection(ft.index)]
    ranks = parse_taxonomy_ranks(tax_aligned)
    phyla = ranks["Phylum"].dropna()
    phyla = phyla[phyla != ""]
    ft_p = ft.loc[phyla.index].copy()
    ft_p["Phylum"] = phyla.values
    return ft_p.groupby("Phylum").sum()


def shannon_diversity(counts):
    """Shannon diversity index H' for a single sample (array of counts)."""
    counts = np.asarray(counts, dtype=float)
    total = counts.sum()
    if total == 0:
        return 0.0
    p = counts[counts > 0] / total
    return -np.sum(p * np.log(p))


def compute_alpha_diversity(ft):
    """Compute Shannon and Observed Richness for all samples in feature table.
    ft: ASVs x Samples (columns are samples)."""
    shannon = ft.apply(shannon_diversity, axis=0)
    richness = (ft > 0).sum(axis=0)
    return pd.DataFrame({"Shannon": shannon, "Richness": richness})


def identify_duplicate_runs(meta):
    """Identify samples that are duplicate sequencing runs (from PICRUST2 metadata)."""
    p2meta = load_picrust2_metadata()
    dups = p2meta[p2meta["duplicate_run"] == True]["sample_id"].tolist()
    return [s for s in meta.index if s in dups]


def save_figure(fig, path_stem, dpi=300):
    """Save figure as both PNG and PDF."""
    os.makedirs(os.path.dirname(path_stem) if os.path.dirname(path_stem) else ".", exist_ok=True)
    fig.savefig(f"{path_stem}.png", dpi=dpi, bbox_inches="tight")
    fig.savefig(f"{path_stem}.pdf", dpi=dpi, bbox_inches="tight")
    print(f"  Saved {path_stem}.png and .pdf")


def strip_sample_prefix(ft):
    """Strip e####_ prefix from feature table columns and average duplicate runs.
    Returns the modified feature table with clean sample IDs as columns."""
    import re as _re
    clean_cols = [_re.sub(r"^e\d+_", "", c) for c in ft.columns]
    ft = ft.copy()
    ft.columns = clean_cols
    if ft.columns.duplicated().any():
        n_dups = ft.columns.duplicated().sum()
        print(f"  Averaging {n_dups} duplicate sequencing run columns...")
        ft = ft.T.groupby(level=0).mean().T
    return ft


def load_all():
    """Load all data sources. Returns dict with all data."""
    climate = load_climate_data()
    ft = load_feature_table()
    tax = load_taxonomy()
    meta = parse_metadata(ft.columns, climate)
    xrf = load_xrf_data()
    return {
        "ft": ft, "tax": tax, "meta": meta, "xrf": xrf, "climate": climate
    }
