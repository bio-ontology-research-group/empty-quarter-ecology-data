# Open-Meteo daily input with the corrected Site 52 series (4 Oct 2026)

The data repository (pinned commit `5a17782`) corrected the Site 52 position
on the Trip 1 and Trip 3 field sheets (`a3f1c21`) but did not refetch the daily
Open-Meteo series. Its correction record
(`evidence/environmental/site52_coordinate_correction.json`) lists
`metadata/climate/daily_weather.tsv` among the consumers not regenerated: the
Site 52 series was retrieved at the mean of the four pre-correction campaign
coordinates (20.83968 N, 53.66812 E). `daily_weather_canonical.tsv` inherits
that series.

This directory is an explicit input override for the ecology rainfall
analyses. The data repository is not modified.

- `open_meteo_site52_corrected_{request,response}.json`: archive-API request
  (URL, parameters, UTC retrieval time, response SHA-256) and raw response at
  the corrected position 20.82784 N, 53.57835 E, with the request shape of the
  original acquisition (`scripts/utils/fetch_daily_weather.py`: daily
  `temperature_2m_mean`, `rain_sum`, `precipitation_sum`, 2022-01-01 to
  2026-02-01, `timezone=auto`).
- `open_meteo_site52_averaged_{request,response}.json`: the same request at the
  averaged position. It reproduces the pinned Site 52 precipitation on all
  1,493 days, which confirms where the pinned series came from.
- `daily_weather_canonical_site52_corrected.tsv`: the pinned
  `daily_weather_canonical.tsv` (SHA-256 `6cb570e7…`) with the three Site 52
  value columns replaced by the corrected-position response. All other rows
  are unchanged. Site 52 precipitation differs on 37 days (183.0 mm compared
  with 173.5 mm over the period).
- `manifest.json`: input and output hashes, requests, API grid cells and the
  per-day precipitation changes.

NASA POWER is unaffected because Sites 51 to 55 share one POWER grid cell.

Rebuild (add `--fetch` to query the API again; without it the stored
responses are reused):

```bash
python analysis/v3/open_meteo_site52_corrected_20261004/package_open_meteo_site52.py \
  --canonical /path/to/data-paper/metadata/climate/daily_weather_canonical.tsv
python -m pytest -q tests/test_open_meteo_site52_input.py
```

Consumers: `rain_calendar_refit_20260909` (`--open-meteo`), and the default
Open-Meteo input of `run_rain_pulse_suite.py` and `rain_response_window.py`.
