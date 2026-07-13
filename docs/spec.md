# Product Specification — Signal Count

## Overview

Signal Count is a backend-first hackathon application that evaluates one market
thesis through specialist services routed via AXL. The system returns a
structured risk memo with scenarios, supporting evidence, opposing evidence,
counter-thesis, invalidation conditions, and provenance rather than a generic
conversational answer.

Strategic product direction: Signal Count is a proof console for decentralized
AI work. The market-risk memo is the artifact; the differentiator is that a
judge or operator can verify which peer produced each claim, which wallet and
hash are bound to it, whether REE evidence exists, and which Gensyn Testnet
transactions recorded the work.

## User Roles

| Role | Capabilities |
| --- | --- |
| Operator | Submit a thesis, view job progress, inspect final memo, replay a demo thesis |
| Judge / viewer | Observe node participation, topology evidence, proof ledger, and final memo artifact |

## Feature Area 1 — Thesis Intake

Accept a single thesis request with asset and time horizon, validate the payload,
and normalize it into a bounded analysis job.

Acceptance criteria:

- The API accepts a thesis payload with `thesis`, `asset`, and `horizon_days`.
- Invalid requests receive structured validation errors.
- A valid request creates a job record with a stable `job_id`.
- The operator can see the normalized forecast question associated with the job.

Out of scope:

- User accounts.
- Batch thesis uploads.
- Multi-asset comparative jobs.

## Feature Area 2 — Distributed Specialist Analysis

Dispatch one job from the coordinator through the local AXL node to specialist
services on separate AXL peers and collect structured responses.

Acceptance criteria:

- The coordinator uses the local AXL bridge for specialist calls rather than
  direct specialist HTTP bypass.
- At least three specialist roles are supported: regime, narrative, and risk.
- Each specialist response includes `job_id`, `node_role`, `peer_id`, structured
  findings, and a timestamp.
- The operator can inspect topology and node participation evidence.
- Live local verification shows coordinator -> AXL bridge -> MCP router ->
  specialist `/mcp` services.
- Multi-peer local verification shows coordinator -> AXL node A -> AXL node B ->
  remote MCP router -> specialist `/mcp` services with distinct AXL public keys.

Out of scope:

- Dynamic service discovery.
- Reputation or marketplace pricing.
- Arbitrary third-party agent joining.
- Claiming remote multi-machine execution when the demo only runs a same-machine
  multi-peer mesh.

## Feature Area 3 — Memo Synthesis

Combine specialist outputs into a final memo that is useful for a fast decision
review and clearly separates support, opposition, and uncertainty.

Acceptance criteria:

- The final memo includes a normalized thesis, scenario table, key catalysts,
  top risks, and invalidation triggers.
- The final memo preserves specialist provenance by node role and peer ID.
- The system can render the memo as structured JSON and HTML.
- The final memo avoids generic chatbot formatting and uses fixed sections.

Out of scope:

- Personalized recommendations.
- Trading recommendations with position sizing.
- Long-form research reports.

## Feature Area 4 — Failure Handling and Observability

Make distributed execution understandable during the demo and degrade safely if
one specialist is unavailable.

Acceptance criteria:

- Per-node status and latency are recorded for each job.
- If one specialist fails or times out, the job still completes with an explicit
  partial-coverage warning.
- The system never silently substitutes a local fake specialist when a remote
  node is unavailable in live mode.
- `GET /health` returns `{"status": "ok"}` when the API is healthy.

Out of scope:

- Full monitoring dashboards.
- Complex retry queues.
- Production-grade SLO alerting.

## Feature Area 5 — Demo Operator View

Provide an operator screen that makes thesis input, node participation,
topology evidence, proof status, and final memo easy to understand.

Acceptance criteria:

- The operator can submit a thesis from a simple web form.
- The operator can see node-role participation, proof status, and final memo
  output in one place.
- A demo fixture can be replayed without depending on unstable live data.

Out of scope:

- Portfolio dashboarding.
- Decorative charts that do not explain the proof path.
- User management or saved portfolios.

## Feature Area 5A — Proof Console UX

Upgrade the demo operator view into a proof-first console for judges and
operators.

Acceptance criteria:

- The first completed-run screen shows command controls, current mode, proof
  capability state, mesh visualization, run timeline, task trace, final memo,
  and reputation/indexed event context.
- Agent rows show role, service, AXL peer ID, wallet, status, and reputation
  when available.
- Proof details expose full hashes, verifier signature metadata, REE receipt
  status, and explorer links without crowding the memo.
- Long peer IDs, hashes, and tx links wrap or truncate predictably without
  overlapping adjacent UI.
- Offline preview, live AXL, REE, chain receipt, and indexed-chain facts are
  labelled truthfully.
- The full battle script can produce readable terminal logs for video capture
  and a plain-text summary for evidence review.

Out of scope:

- Marketing landing page redesign.
- Decorative charts that do not improve proof comprehension.
- Hiding proof details behind unsupported claims or ambiguous badges.

## Feature Area 6 — Proof and Recovery Layer

Make the proof path inspectable without requiring judges to read raw JSON.

Acceptance criteria:

- Each completed run can expose AXL peer, wallet, output hash, verifier status,
  REE receipt status, and tx link metadata when available.
- Memo evidence bullets can be traced back to accepted specialist output hashes.
- Chain receipt events can be indexed into a local projection after restart.
- Duplicate event replay does not duplicate indexed facts.
- The indexer records failure status and repairs a configured shallow reorg
  window.

Out of scope:

- Claiming REE or Gensyn Testnet evidence for offline preview fixtures.
- Full archival reorg rollback beyond the configured repair window.
- ERC20, USDC, stablecoin, or real-money rewards.

## Feature Area 7 — Active Run Verification

Make verification a user-visible action rather than a passive metadata table.

Acceptance criteria:

- A completed job exposes a structured verification bundle through
  `GET /jobs/{job_id}/verify`.
- Verification requires a one-to-one match between stored attestations and
  specialist payloads on `(job_id, node_role, peer_id)`, rejects duplicate,
  missing, or unmatched contexts, and recomputes every matched output hash.
- Verification checks verifier attestation signatures when signer metadata is
  configured; unknown attestation fields are rejected instead of being dropped
  before signature verification.
- Verification checks REE receipt consistency when receipt content is available
  and distinguishes `present`, `parsed`, `validated`, and `verified`.
- Verification checks recorded Gensyn Testnet transaction hashes through RPC or
  indexed-chain projection.
- The proof console renders verification results as explicit pass/fail/missing
  states without modifying the memo.

Out of scope:

- Treating local REE receipt hash recomputation as full REE re-execution.
- Hiding missing verification evidence behind a generic "confirmed" badge.

## Feature Area 8 — REE-Backed Inference Policy

Make the REE claim precise enough to defend in judging.

Acceptance criteria:

- The project declares either `risk-only-ree` or `all-llm-ree` as its active
  policy.
- If `risk-only-ree`, the risk specialist is the hero proof path and shows
  prompt hash, token hash, receipt hash, output hash, verifier attestation, and
  contribution tx together.
- If `all-llm-ree`, every stochastic specialist output is REE-backed or clearly
  labelled as non-REE evidence.
- Verifier scoring downgrades outputs that lack required REE evidence under the
  active policy.
- UI copy reserves `verified` for full verification and uses `validated` only
  for local receipt consistency checks.

Out of scope:

- Claiming that all reasoning is verifiable when only one role is REE-backed.
- Claiming receipt presence proves output quality.

## Feature Area 9 — AXL Peer Selection and Fallback

Make AXL coordination affect runtime behavior, not only routing labels.

Acceptance criteria:

- The app records peer capability state: role, service, peer ID, wallet,
  health, latency, and recent verifier/reputation score.
- Specialist dispatch can select from available peers based on capability and
  score instead of relying only on static env mapping.
- Peer selection reason is persisted in run metadata.
- If a selected peer fails, fallback or partial behavior is explicit and
  auditable.
- The UI shows selected peer, selection reason, fallback status, and final
  accepted/rejected state.

Out of scope:

- Open-ended autonomous peer marketplaces.
- Unbounded agent loops.
- Silently replacing a failed peer with local fixture output.

## Feature Area 10 — Evidence-Grade Inputs

Improve memo quality so the proof layer protects something worth reading.

Acceptance criteria:

- Market and news inputs are either real source adapters with retrieval
  metadata or explicitly labelled demo fixtures.
- Evidence bullets include source URL or fixture source, retrieval timestamp,
  and source hash when available.
- The final memo marks source quality: live source, fixture source, stale
  source, or missing source.
- At least one demo fixture creates material disagreement between specialists.
- The memo highlights invalidation conditions and counter-thesis before generic
  catalysts.

Out of scope:

- Trading execution.
- Price targets.
- Personalized financial advice.
