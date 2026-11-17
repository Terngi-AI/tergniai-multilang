# Dataset card: {{ dataset name }}

> Template: copy this file next to every dataset under `data/` and fill in every section.
> A dataset without a completed card must not be committed (see `data/README.md`).

- **Version / date**:
- **Owner** (the maintainer who added it and vouches for the licences):
- **Purpose** (evaluation, fine-tuning, benchmark):

## Sources and licences

| Source | URL | Licence | Redistribution allowed? | Notes |
|---|---|---|---|---|
| | | | yes / no | |

Every row must name a real licence. If the licence does not allow redistribution, do not
commit the data — commit a pointer (URL + how to obtain it) instead.

## Contents

- Languages:
- Size (rows, characters, or duration for audio):
- Format, and the command (script + commit) that regenerates or re-downloads it:

## Collection and consent

- How the data was collected (public benchmark, crowdsourced, user feedback, ...).
- Consent: what people agreed to, the version of the consent text, and the date. If the
  data is user-generated, this section is mandatory.
- Withdrawal: how a contributor's rows are found and removed.
- PII: everything user-generated was run through `scripts/redact_pii.py` before commit.
  Note the redaction date and the `--names` list used.

## Known limitations and biases

- (e.g. dialect coverage, region of the speakers, gender/age balance, known errors)

## Splits

Which files are train / dev / test, and how the test set is kept held out: the
de-duplication check (command) and its result.

## Contact

Questions, or data-subject requests (access, correction, deletion): <maintainer e-mail>.
