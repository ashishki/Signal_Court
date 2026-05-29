# Signal Count Tasks

Status: research reference / proof-console artifact
Last updated: 2026-05-29

Signal Count is not an active product line. It is preserved as a visual and
architectural reference for Entropy Core receipts, referee verdicts, and
Telegram Trader Intelligence evidence UI.

## Active Tasks

### SC-001: Preserve Proof Console Reference

Owner: codex
Priority: P1
Status: planned

Objective: |
  Keep README and runbook understandable enough that the proof-console idea can
  be reused later.

Acceptance-Criteria:
  - README explains the proof trail, not trading performance.
  - Setup/demo notes are either current or clearly marked stale.
  - No claim implies trading advice, prediction, or live execution.

### SC-002: Extract Entropy Receipt Patterns

Owner: codex
Priority: P1
Status: planned

Objective: |
  Extract useful ideas for Entropy Core V2: signed envelopes, receipt hashes,
  referee/proof UI, specialist contribution records, and explicit degradation.

Acceptance-Criteria:
  - Extraction note maps Signal Count concepts to Entropy Core candidate
    schemas.
  - It distinguishes reusable patterns from Gensyn/OpenAgents-specific
    integration details.
  - No implementation is started in this repo.

### SC-003: Telegram Trader Intelligence UI Reference

Owner: codex
Priority: P2
Status: planned

Objective: |
  Capture how the proof console could inform future Telegram trader intelligence
  reports: evidence trail, accepted/rejected claims, source links, and referee
  verdicts.

Acceptance-Criteria:
  - Reference note lists UI sections that are useful for trader-channel reports.
  - It avoids marketplace/leaderboard framing.
  - It points downstream work to `Entropy_Protocol`, not this repo.
