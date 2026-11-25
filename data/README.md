# data/

Evaluation and training data lives here. The rules:

1. **Never commit raw user data.** Conversation exports, feedback text and WhatsApp
   transcripts do not go into git, redacted or not.
2. **Every dataset needs a dataset card** using the [template in docs/DATASET.md](../docs/DATASET.md),
   stored next to the files, stating sources, licences, size, collection method, consent
   and known biases.
3. **Everything published goes through [`scripts/redact_pii.py`](../scripts/redact_pii.py)**
   before commit, and a maintainer reviews the card and the redaction run.
4. **Licences are recorded per dataset.** If a licence does not allow redistribution,
   commit a pointer (URL + access instructions) instead of the data.

Datasets in this folder:

- [`terngi-eval/`](terngi-eval/README.md): the native-speaker evaluation set (#14). Native
  speakers, your references are very welcome.

Suggested layout:

```
data/
  flores200/
    README.md        # the dataset card
    devtest.tsv
  mafand-mt/
    README.md
    ...
```
