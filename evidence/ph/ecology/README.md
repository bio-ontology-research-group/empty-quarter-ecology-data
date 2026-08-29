# Frozen pH ecology sensitivity

Dataset version: `EQ-PH-SHARED-v1.0.0`. Analysis version: `ph-shared-v1.1.0`.

The immutable, incomplete workbook contributed 702 exact pH/specimen/ecology joins and 562 site-campaign-position groups.
Group-mean pH ranged from 7.290 to 9.980.

The pipeline tests exact specimen reconciliation, site-fixed alpha models, paired position contrasts, Bray-Curtis and Aitchison composition models, a same-cohort geographic model before and after pH adjustment, and deletion diagnostics for the singleton maximum-pH group and its site.

Rows that are pending, depleted, date-quarantined, or quality-control-quarantined are absent from every model. Availability is non-random, so results are bounded to this fixed cohort.

The ecology and data papers use this same frozen source. Future corrections or recovered measurements require a successor version and a new comparison.
