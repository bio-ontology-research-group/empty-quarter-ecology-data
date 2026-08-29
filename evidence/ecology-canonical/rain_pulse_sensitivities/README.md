# Rainfall pulse-response sensitivities

`summary.tsv` compares the primary NASA POWER model with an Open-Meteo rainfall
product, control filtering, a complete paired-bulk cohort, pH adjustment and
more flexible route trends. Each run uses the same rise-and-decay kernel search
and corrects jointly over all candidate peak times and three diversity
endpoints.

Each run also gives a 95% site-block bootstrap interval for the selected
effect and partial R2, and a peak-selection interval obtained by repeating the
peak search in resampled complete site histories. These intervals condition
on the rainfall product and nuisance adjustment; product and route-model
uncertainty remain separate sensitivities.

The suite does not require the rainfall pattern to recur across campaigns.
Rain is too rare for that to be a meaningful stability criterion. Instead,
the conditional timing null preserves the amount, rarity and spatial field of
rain observed within every campaign and rotates its lag relative to sampling.

Run from the project root:

```bash
.venv/bin/python analysis/v3/run_rain_pulse_suite.py
```
