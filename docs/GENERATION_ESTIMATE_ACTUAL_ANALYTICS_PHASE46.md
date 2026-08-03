# Generation Estimate vs Actual Analytics — Phase 46

Phase 46 closes the feedback loop between Batch Generation Planning and real execution evidence.

## Evidence sources

The analytics service joins three integrity-aware artifacts by Run ID and persisted links:

- Launch Receipt: planned files, characters, provider requests, ETA and estimated provider cost.
- Execution Session: processed characters, retries, lifecycle status and actual elapsed time.
- Execution Receipt: actual output count, disposition, final status and linked evidence.

No source text, API key, credential or provider token is copied into analytics records or exports.

## Cost semantics

The displayed actual cost is **derived**, not billed cost. It uses the price rate represented by the launch estimate and applies it to processed plus retry characters. The UI and export label the source as `derived_from_launch_rate`. When pricing or character evidence is unavailable, cost remains unavailable rather than being guessed.

## Accuracy metrics

Each run records estimate, actual, variance and bounded accuracy for:

- files;
- processed characters;
- provider requests;
- duration;
- provider cost.

Material duration overruns, cost overruns, incomplete outcomes and integrity issues are surfaced as attention reasons.

## Provider calibration

Runs are grouped by provider, model and voice. The advisory calibration view shows:

- success rate and retry volume;
- ETA and cost accuracy;
- actual-to-estimated duration multiplier;
- actual-to-estimated cost multiplier;
- observed characters per minute;
- confidence based on sample size and evidence completeness;
- practical recommendations.

Calibration suggestions are exported but never applied automatically.

## UI access

Open **Reports → Estimate vs Actual**. The workspace is also available from the toolbar overflow and Command Palette.

## Export

The center exports:

- a JSON analytics package;
- a CSV run catalog;
- an advisory provider calibration JSON file.

## Compatibility

- Database schema remains 22.
- Existing Launch Receipts are compatible; missing ETA data is shown as unavailable.
- Existing Execution Sessions and Execution Receipts are not rewritten.
