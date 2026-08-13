# Roadmap 2 A7.2 — Short-Utterance & Pronunciation Hardening

## Goal

A7.2 makes short and ambiguous TTS inputs inspectable without weakening A7.1 Language Lock. The selected project language, or an explicit per-job language override, remains authoritative. Text analysis never detects a replacement language and never changes provider, account, voice, model, or language.

## Risk analysis

`PronunciationAssuranceService` evaluates each job for deterministic pronunciation-risk signals:

- very short utterances;
- digits and standalone numeric values;
- DKK currency forms;
- standalone dates;
- acronyms and abbreviations;
- proper-name-like short strings;
- symbols;
- script mismatch against an explicitly selected Latin-script target language.

The result records the original text, selected language, risk level, flags, and an optional safe normalized candidate. Source text is never mutated.

## Conservative Danish normalization

A7.2 provides language-locked normalized candidates only for narrowly bounded standalone Danish forms:

- integers, e.g. `10` → `ti`;
- DKK amounts, e.g. `20 kr.` → `tyve kroner`;
- valid standalone calendar dates, rendered with Danish day/month/number words.

Acronyms, abbreviations, proper names, mixed prose, and unsupported languages are never guessed or rewritten automatically.

## Explicit execution contract

A normalized candidate is not sent to a provider by default. `PronunciationService` uses it only when the user explicitly sets the job pronunciation override to `normalized` after review. If such an override is requested but no safe candidate exists, Preflight blocks generation for that row.

The existing pronunciation-dictionary metadata remains provider metadata. `dictionary_disabled` continues to disable dictionary use for a job. A7.2 does not silently reinterpret the global pronunciation checkbox as permission to rewrite text.

## Language Probe

The Generation menu and queue context menu expose **Language Probe (1–3 samples)**. The dialog:

- accepts only one to three selected jobs;
- shows the authoritative language, risk level, flags, original text, and normalized candidate;
- can explicitly apply or clear the per-job normalized override;
- can preload original or normalized text into Voice Browser;
- never starts preview audio automatically.

The user must press **Preview** in Voice Browser. No provider, account, voice, model, language, Preflight, or generation action is automatically applied by the probe.

## Preflight and launch safety

Preflight persists pronunciation evidence and:

- warns when medium/high-risk jobs remain unresolved;
- highlights risk more strongly when Language Lock itself is best-effort;
- blocks an unsafe explicit `normalized` override;
- records multiple explicit target languages without content-based detection;
- includes `pronunciation_override` in the Preflight revision key so a pronunciation decision makes old Preflight evidence stale.

Generation confirmation exposes a dedicated pronunciation-review launch check and requires acknowledgement while medium/high-risk pronunciation rows remain.

## Non-goals / invariants

A7.2 does **not**:

- auto-detect a target language;
- auto-change provider/account/voice/model/language;
- auto-run a provider preview;
- auto-run Preflight or generation;
- add hidden cross-provider failover;
- change database schema 23;
- mutate source/job text.
