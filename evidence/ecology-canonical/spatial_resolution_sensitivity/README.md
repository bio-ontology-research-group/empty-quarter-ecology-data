# ASV-resolution and neighbour-graph sensitivity

The transect association is not an artefact of genus aggregation: at amplicon-sequence-variant resolution the same model gives partial R2 0.3462 to 0.3737 against 0.4016 at genus level. The comparison runs on the 629-group intersection of the two caches, covering 629 of the 630 genus-reference groups (1 reference group absent from the ASV cache, 2 extra ASV-cache groups dropped); the genus figure quoted here is the 630-group primary fit. The residual Moran diagnostic declines with the neighbour count: it is detected at k = [3, 4, 5, 6, 8] and not at k = [10] (Moran I 0.1104 down to -0.0097). The fixed-k residual autocorrelation statement is bounded to the short-neighbourhood scale.

Do not promote the ASV-resolution fit to the primary result; it is a supplementary resolution sensitivity on the same design and inherits every design limit of the primary model, including the collection-order alias. Do not state unqualified residual spatial autocorrelation without naming the neighbour count.

Evidence files: `asv_resolution_sensitivity.tsv`,
`moran_k_sensitivity.tsv`, `claim_verdict.json`.
