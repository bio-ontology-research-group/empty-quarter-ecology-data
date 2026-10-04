# Five-product Trip 1 rainfall exposure with the corrected Site 52 position (4 Oct 2026)

The pinned data repository (`5a17782`) table
`metadata/climate/rain_event_product_exposures.tsv` was built on 4 Aug 2026
from the pre-correction Trip 1 geodata: its Site 52 rows use the Site 53
position (20.851514 N, 53.757884 E) for all five products, and its Open-Meteo
column uses the averaged-position Site 52 series. This directory is the
corrected override used by the ecology paper (supplement, rainfall robustness:
four complete days before Trip 1 collection, CHIRPS v2.0, CMORPH V1.0,
GPM IMERG Final V07B, NASA POWER and Open-Meteo).

Raw inputs: the 21 CHIRPS, CMORPH and IMERG daily files listed in the pinned
source ledger, downloaded again on 4 Oct 2026 from their official URLs and
verified against the ledger SHA-256 (all 21 identical). IMERG files are now
under month directories (`.../GPM_3IMERGDF.07/2023/03/`); the day-of-year path
in the original ledger returns an HTML banner, so the URL template in
`scripts/climate/build_rain_event_product_exposures.py` was updated.

Reproduction check: with the pre-correction geodata and the pinned NASA POWER
and Open-Meteo tables, the builder reproduces the pinned exposure table
byte-identically.

Corrected build (ecology root; geodata identical to `5a17782`):

```bash
python scripts/climate/build_rain_event_product_exposures.py \
  --power /path/to/data-paper/metadata/climate/nasa_power_daily_precipitation.tsv.gz \
  --open-meteo analysis/v3/open_meteo_site52_corrected_20261004/daily_weather_canonical_site52_corrected.tsv \
  --chirps-dir RAW/chirps --cmorph-dir RAW/cmorph --imerg-dir RAW/imerg \
  --output analysis/v3/rain_event_product_exposures_site52_corrected_20261004/rain_event_product_exposures.tsv \
  --sources analysis/v3/rain_event_product_exposures_site52_corrected_20261004/rain_event_product_sources.tsv \
  --manifest analysis/v3/rain_event_product_exposures_site52_corrected_20261004/rain_event_product_exposures.manifest.json
python analysis/v3/rain_event_product_exposures_site52_corrected_20261004/product_correlations.py \
  analysis/v3/rain_event_product_exposures_site52_corrected_20261004/rain_event_product_exposures.tsv \
  analysis/v3/rain_event_product_exposures_site52_corrected_20261004/product_correlations.tsv
```

Only the five Site 52 rows change: coordinates, and grid cells for CHIRPS
(`20.875_53.775` → `20.825_53.575`), CMORPH (`20.875_53.875` → `20.875_53.625`)
and IMERG (`20.85_53.75` → `20.85_53.55`). Site 52 received no rain in this
window in CHIRPS, CMORPH, IMERG or Open-Meteo at either position, and 0.06 mm
in NASA POWER (shared cell). Every row was checked to lie at the corrected
Trip 1 coordinates and inside its nearest product cell.

Pairwise agreement across the 60 sites (`product_correlations.tsv`), unchanged
by the correction: Pearson r 0.501–0.917, Spearman rho 0.554–0.881.
