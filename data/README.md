# Data directory

This folder hosts sample data and small request payloads used by the
GridWise service.

* `example_request.json` -- a minimal, runnable payload illustrating the
  shape of a valid POST body.
* `generated_samples.json` -- **self-generated** synthetic cases produced
  by `scripts/generate_samples.py`. These are NOT official organizer
  samples and must not be relied on as a contract. The generation is
  deterministic (fixed seed) so the validator can run in CI without
  network access.
* `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` (optional) -- if
  the official public sample cases are present in the repository root
  or in this folder, the validator automatically picks them up.

The schema is described in `app/schemas/`. Examples include single
notes, multiple applicable directives, paraphrased hidden-style notes,
and decimal numeric values.