# Author control confirmation received 29 July 2026

This note records the control information Robert Hoehndorf supplied in the
Codex thread, together with a relevant Mattermost exchange with Marwa
Abdelhakim pasted by Robert. The Mattermost transcript displayed times
10:04--11:08 but did not display a calendar date; it was supplied on
29 July 2026.

## Confirmed

- Different positive controls were used in different trips. Two mock
  communities were used, but their compositions and trip assignments are not
  yet available.
- `=+ Ctrl 1`--`3` are replicates, and `- Ctrl 1`--`3` are replicates.
- Extraction controls and PCR blanks were two distinct negative-control types.
- `EB` means extraction blank.
- `Negative1`--`Negative7` are extraction blanks.
- One EB was used per extraction day. Samples from multiple trips could be
  extracted on the same day, so an EB cannot meaningfully be assigned to one
  trip.
- EB identifiers do not encode a trip. Sequence indices may distinguish
  sequenced libraries or help adjudicate reused-label collisions, but they do
  not turn an extraction-day blank into a trip-specific control.

## Pending or ambiguous

- Marwa will provide the compositions of the two mock communities and review
  which control was used for each trip.
- The exact extraction dates and sample-to-extraction-batch memberships remain
  pending. Robert's current interpretation is that EB labels were reused, but
  the July-era `EB1`--`EB5` records and Trip-5-era `EB1`--`EB5` records must
  not yet be asserted to be the same or different libraries. Sequence-index
  evidence can address that library-identity question, not assign an EB to a
  single trip.
- Marwa wrote that the PCR blank “should have the same name”. The antecedent is
  ambiguous in the supplied exchange, so this does not support assigning a
  specific EB, Negative, or numbered-Ctrl identifier to the PCR blank.
- The reason `Negative3` is absent remains unknown.
- Mock-community organisms, proportions, lots, preparation stages, and
  trip-specific assignments remain unknown.

These confirmations improve stage and replicate metadata but do not establish
positive-control composition. `control_ground_truth.tsv` must remain absent.
