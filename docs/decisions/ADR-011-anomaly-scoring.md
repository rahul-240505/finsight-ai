# ADR-011: Unsupervised anomaly scoring with Isolation Forest, evaluated on a time split

- Status: Accepted · Date: 2026-11-26

## Context
Analysts need a ranked list of *unusual* transactions to review, with reasons. Real fraud labels are not available for users' own data, so the served model must work without labels. Any reported quality must come from an honest, leak-free evaluation.

## Options
1. **Rules only** (e.g. amount far above the account's average). Transparent; catches one pattern.
2. **Isolation Forest** on per-account behavioural features. No labels needed, fast, gives a score.
3. **Supervised classifier.** Needs labels we don't have for user data; evaluated separately on a public labelled dataset.
4. **Autoencoder / deep models.** More moving parts and compute for no demonstrated gain at this scale.

## Decision
- Serve **Isolation Forest** (scikit-learn, 200 trees, `max_samples=256`, fixed seed) on 8 features computed by one shared function (`app/modules/ml/features.py`), using only each account's *earlier* transactions.
- **Time-based split** (train Jan-Sep, validation Oct-Nov, test Dec). Threshold = max F1 on validation; candidates compared by validation PR-AUC; the test set is used once for reporting.
- **Risk score = percentile of the training distribution**, interpolated so it keeps rising with the raw score (no ties at 1.0). A threshold of 0.9817 flags about 0.8-1.6% of rows.
- **Reasons** are rule-based descriptions of the unusual inputs (amount vs history, new merchant, burst, night-time), not the model's internals. Wording is always "unusual", never "fraud".
- **Registry:** `model_versions` stores params, features, metrics, threshold, data description, artifact path and SHA-256; a partial unique index allows one active version per model name. A model file is loaded only if its path stays inside `MODEL_DIR` and its hash matches (joblib files are pickles and can run code when loaded).
- Scores are stored per (transaction, model version); re-scoring a dataset replaces that version's scores in one transaction.

## Consequences
- Test PR-AUC 0.658 vs 0.202 for the best single rule and 0.011 for random (docs/evaluation.md).
- Isolation Forest cannot rank values far *outside* the training range above the most extreme training points, so very large single amounts are under-ranked (large_amount recall 0.33). A hybrid with the amount rule fixed that type but lowered overall validation PR-AUC (0.615 vs 0.682) and was rejected.
- Cold start: accounts with little history are over-flagged (8.3% in January vs ~0.9% later).
- Scoring is synchronous (~21 s for 500k rows); moving it to the background worker is planned.

## Revisit when
Reviewed analyst decisions provide labels (then train a supervised model on them), the cold-start rate matters to users, or a new pattern appears that the features can't express.
