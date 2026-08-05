# Compartment distance decay and turnover/nestedness

Aitchison dissimilarity increased with geographic distance in every soil position. Paired distance contrasts, tested with whole-site permutations and family-wise maximum-statistic control, supported a difference between compartment decay slopes (omnibus p = 0.0053). After coverage standardisation to 12865 reads, Simpson replacement accounted for the majority of Sorensen dissimilarity in every compartment.

Do not treat site pairs as independent observations, do not report a p-value from permuting the pairwise distance vector, and do not read compartment slope differences as a plant or root process. The abundance-gradient component of Bray-Curtis is reported only with its library-size diagnostic and supports no claim, because it is identically zero under coverage standardisation.

Sampling uncertainty is reported as a 95% t interval from a delete-one-site jackknife. Every distance involving the omitted site is removed together, so site pairs are never treated as independent.

Evidence files: `distance_decay_pairs.tsv`,
`distance_decay_slopes.tsv`, `turnover_nestedness_components.tsv`,
and `claim_verdict.json`.
