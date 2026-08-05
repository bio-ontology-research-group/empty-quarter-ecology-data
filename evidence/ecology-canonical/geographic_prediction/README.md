# Geographic prediction and collection-order alias

**Status: `joint_campaign_block_not_supported_site_block_sensitivity_supported`**

## Primary arm — whole campaign and contiguous block held out together

This is the requested leakage-free design: a whole campaign and a contiguous transect block are excluded together, taxa are selected inside the training fold only, and scoring uses within-compartment CLR differences between held-out sites so that no held-out campaign intercept is estimated.

- Supported: **False**
- Equal-weight cross-validated R2: -0.0015
- Pooled cross-validated R2: -0.0004
- Folds with positive skill: 10/18
- Strictest null p value: 0.354

## Sensitivity arm — contiguous site block only

Every campaign remains on both sides of this split, so it cannot test transport to an unseen campaign. It does not determine the status above.

- Supported: **True**
- Out-of-block R2: 0.2526
- Blocks with positive skill: 6/6
- Strictest null p value: 0.025

## Collection-order alias

- Campaigns audited: 5
- Absolute Spearman correlation between elapsed collection time and transect position: 0.9938 to 1.0000
- Status: collection_order_aliased_with_transect_position

## Permitted and prohibited wording

The primary test holds out a whole campaign and a contiguous transect block together and scores within-compartment differences between held-out sites. It did not support cross-campaign, cross-block transport of the transect gradient (equal-weight R2 -0.0015, pooled -0.0004, 10/18 folds positive, strictest null p = 0.354). As a sensitivity, holding out a contiguous site block alone while keeping the same campaigns on both sides of the split did predict the site-averaged composition of the held-out block (out-of-block R2 0.2526, 6/6 blocks positive, strictest null p = 0.025). This sensitivity does not hold out a campaign and therefore does not demonstrate transport to an unseen campaign.

Do not report the site-block-only sensitivity as the geographic prediction result, and do not describe geographic prediction as succeeding: the requested campaign-plus-block design is the primary arm and it is not supported. Do not describe any out-of-block skill as evidence for a geographic driver. Elapsed collection time and transect position are aliased in every campaign, so a repeated pattern cannot be separated from a repeated collection order or from order-dependent instrument effects.

Evidence files: `collection_order_alias.tsv`, `prediction_folds.tsv`,
`site_level_block_folds.tsv`, `prediction_nulls.tsv`,
`claim_verdict.json`.
