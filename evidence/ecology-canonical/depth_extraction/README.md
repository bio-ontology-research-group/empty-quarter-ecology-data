# Sequencing-depth and extraction-protocol sensitivity

- Status: `compartment_wording_retained_with_interaction_dependence`
- Profiles joined to the release ledger: 1221 exact, 16 by Trip-5 suffix fallback, 0 unmatched
- Profiles with a recorded extraction kit: 858 / 1237
- Campaign-by-position interaction Wald p: 0.008306 unadjusted, 0.1748 depth-adjusted

## Deep-Surface (shallow subsurface minus surface)

- Status: `direction_only`
- Depth-adjusted GEE estimate: 0.1026 (95% CI -0.0119 to 0.2171; p = 0.07905)
- Interval excludes zero by model: additive_unadjusted=False, additive_depth_adjusted=False, depth_and_kit_as_recorded=False, complete_case_cohort=True, depth_and_kit_kit_varying_campaigns=True, protocol_matched_pairs=True
- Direction stable across models: True

## Rhizosphere-Surface (root-adjacent minus surface)

- Status: `sensitivity_dependent`
- Depth-adjusted GEE estimate: -0.1709 (95% CI -0.3214 to -0.0203; p = 0.02609)
- Interval excludes zero by model: additive_unadjusted=True, additive_depth_adjusted=True, depth_and_kit_as_recorded=False, complete_case_cohort=False, depth_and_kit_kit_varying_campaigns=False, protocol_matched_pairs=True
- Direction stable across models: True

## Rhizosphere-Deep (root-adjacent minus shallow subsurface)

- Status: `supported`
- Depth-adjusted GEE estimate: -0.2735 (95% CI -0.4245 to -0.1225; p = 0.0003852)
- Interval excludes zero by model: additive_unadjusted=True, additive_depth_adjusted=True, depth_and_kit_as_recorded=True, complete_case_cohort=True, depth_and_kit_kit_varying_campaigns=True, protocol_matched_pairs=True
- Direction stable across models: True

## Permitted wording

After adjusting for log sequencing depth in the site-clustered GEE, the root-adjacent minus shallow subsurface Shannon contrast was -0.273 (95% CI -0.424 to -0.122). The root-adjacent minus surface contrast is sensitivity-dependent: its direction is stable but its interval or adjusted test changes across the prespecified extraction models, so it is reported as such rather than as a general result. The campaign-by-position interaction changed materially with depth adjustment (Wald p = 0.00831 unadjusted, 0.175 after log sequencing depth). Report that dependence in the Results and abstract; do not present either model as the single campaign-by-position result. Extraction metadata are incomplete and partly confounded with campaign (858 of 1237 profiles carry a recorded kit), so these fits are a robustness check and do not remove laboratory batch effects.

## Prohibited wording

Do not describe the extraction sensitivity as removal of all laboratory batch effects; campaign, processing context and missing extraction metadata remain coupled.
