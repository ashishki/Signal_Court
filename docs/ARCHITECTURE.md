# Architecture — Signal Count

## Overview

Signal Count is a backend-first market thesis review system. A user submits one
thesis, an asset, and a horizon. The coordinator dispatches structured requests
through AXL to specialist services and synthesizes the responses into a compact
risk memo.

The product is decision support, not trading execution or market prediction.
The strategic architecture direction is proof-first: the memo is the artifact,
but the system should make every agent contribution inspectable and eventually
actively verifiable.

## Runtime Shape

```text
User / Demo UI
  |
FastAPI API
  |
Coordinator
  |
AXL local HTTP bridge
  |
AXL peer services
  |-- Regime analyst
  |-- Narrative analyst
  |-- Risk analyst
  |
Verifier
  |
Memo synthesis
  |
SQLite job store + provenance ledger
```

## Proof-First Shape

The system exposes active verification instead of treating proof metadata as a
passive appendix:

```text
Completed job
  |
Verification endpoint / UI action
  |-- recompute specialist output hashes
  |-- check verifier attestations/signatures
  |-- validate or verify REE receipts according to policy
  |-- check Gensyn Testnet tx presence
  |-- compare indexed-chain projection
  |
Proof result: verified / validated / present / missing / failed
```

The proof console should make this path the primary user experience. A judge
should not need to read raw JSON to understand what was produced by which AXL
peer, which wallet is attributed, which output hash was recorded, which REE
receipt exists, and which transaction backs the claim.

## Architecture Priorities

1. Demo reliability: direct full-battle execution, passing format checks,
   fast prewarmed recording path, and truthful fallback labels.
2. Verification-first product surface: `GET /jobs/{job_id}/verify` and UI
   controls that expose output hash, attestation, REE, and chain verification.
3. REE policy: explicitly choose `risk-only-ree` or `all-llm-ree` and reserve
   `verified` for full verification rather than local receipt hash consistency.
4. AXL coordination depth: peer capability registry, health/reputation-aware
   selection, fallback, and visible selection reasons.
5. Evidence-grade inputs: real source adapters or fixture labels with source
   hashes and retrieval timestamps.

## Demo Runtime

`scripts/run_full_battle_demo.sh` is the one-command presentation path. It
starts the local two-node AXL mesh, MCP router, specialist services, coordinator
app, REE-enabled risk path, Gensyn Testnet task/contribution receipt writes, and
one-shot indexer. Normal AXL dispatch currently returns unsigned
`SpecialistResponse` objects, so the script disables reputation transactions
and native test-ETH payouts and treats either one as an error. It prints
sectioned terminal logs for video capture and writes a plain summary to
`.runtime/full-battle/summary.txt`.

The web viewer remains available at `http://127.0.0.1:8004` after the run so
the proof console can be captured from the completed job state.

## Main Components

| Component | Location | Responsibility |
| --- | --- | --- |
| API | `app/api/` | Health, job submission, demo page routes, proof-console evidence display |
| AXL client | `app/axl/` | Local bridge calls, peer/service addressing, topology fetch |
| Chain integration | `app/chain/` | Gensyn Testnet task/contribution runtime writes plus isolated reputation/payout transaction helpers |
| Coordinator | `app/coordinator/` | Fetch context, fan out specialist calls, collect responses |
| Evaluation | `app/evaluation/` | Verifier scoring, attestation hashing, wallet attribution, and reputation projection |
| Event indexer | `app/indexer/` | Gensyn Testnet event decoding and local indexed-chain projections |
| Specialist services | `app/nodes/` | Regime, narrative, and risk analysis |
| Verifier service | `app/nodes/verifier/` | Signed execution checks and deterministic verifier attestations |
| REE integration | `app/ree/` | Gensyn REE subprocess runner, receipt parsing, and hash validation |
| Orchestration | `app/orchestration/` | Declared workflow graph and serializable per-node graph state |
| Schemas | `app/schemas/` | Pydantic request, response, memo, and provenance contracts |
| Persistence | `app/store/` | SQLite job and memo storage |
| Rendering | `app/rendering/` | HTML rendering for the demo memo and specialist evidence source metadata |
| Operator UI | `app/templates/` | Proof console shell, thesis form, mesh visualization, latest-run tabs, and responsive evidence layout |
| Observability | `app/observability/` | Tracing, metrics, node execution records |

## AXL Integration Boundary

The configured coordinator path does not call specialist hosts directly. It
resolves a specialist role to a configured AXL peer ID and service name, then
builds an MCP route through the local AXL bridge:

```text
{AXL_LOCAL_BASE_URL}/mcp/{peer_id}/{service_name}
```

Each job also records a topology snapshot and per-node execution records so a
demo can show which peers participated, whether any role failed, and how long
each specialist took.

Payloads crossing this boundary are transport-safe JSON data only. Runtime
objects such as Python LLM client instances stay inside the receiving process.
This matters because the configured AXL path serializes requests over HTTP; an
in-process object in the payload would work only in a fake local workflow and
fail through the HTTP bridge.

## Event Indexer

The event indexer adds a local chain-event projection path beside job metadata. Indexed
events are stored in SQLite as `indexed_chain_events` with
`transaction_hash:log_index` as the idempotency key. Indexed blocks and the
polling cursor are stored separately, so replay, restart, and shallow reorg
repair do not mutate local-only job metadata. Projection rows are explicitly
labelled `source=indexed_chain`, separate from local-only `run_metadata`.

The indexer decodes the current Signal Count contract events:

- `TaskCreated`
- `TaskFinalized`
- `ContributionRecorded`
- `VerificationRecorded`
- `ReputationRecorded`

The projection can rebuild task finalization state, contribution/verification
receipt facts, and an agent reputation leaderboard from events after an app
restart. The scheduler polls `latest - confirmations`, stores block hashes, and
repairs a configured recent window if a stored block hash changes. Replay is
idempotent. Full archival rollback beyond the configured repair window is not
claimed.

A freshly captured single-node run can provide evidence for:

- coordinator -> local AXL bridge
- local AXL bridge -> MCP router
- MCP router -> specialist `/mcp` endpoints
- job ledger recording `axl-mcp` transport and dispatch targets

The multi-peer mesh demo strengthens that path:

```text
Coordinator app
  |
AXL node A: local bridge
  |
AXL node B: remote peer identity
  |
MCP router B
  |
regime / narrative / risk specialist services
```

In that mode, `AXL_LOCAL_BASE_URL` points to Node A while role peer IDs point to
Node B. A successful run should record both public keys in its topology evidence
and use Node B's public key in its dispatch targets. That run is evidence of
same-machine peer separation only when its process logs and topology artifact
are retained; it is not evidence of a remote deployment.

## Specialist Node Server

`app/nodes/server.py` provides the AXL-facing process for a specialist node. It
exposes:

- `GET /health` for local service checks.
- `POST /mcp` for routed specialist requests.

On startup the server registers with the AXL MCP router:

```text
POST {AXL_MCP_ROUTER_URL}/register
{
  "service": "<service_name>",
  "endpoint": "<node_public_url>/mcp"
}
```

The same server binary is used for all three roles by changing environment
variables such as `NODE_ROLE`, `NODE_SERVICE_NAME`, and `NODE_PUBLIC_URL`.

## Workflow Graph

The coordinator uses a declared workflow graph rather than a hidden role list:

```text
regime    -> verifier
narrative -> verifier -> synthesis
risk      -> verifier
```

The graph is finite and acyclic. Each run stores both the declared graph and
per-node graph state in `run_metadata`, so the UI can distinguish completed,
missing, rejected, skipped, and pending nodes without changing the `/jobs`
contract.

## Specialist Roles

| Role | Purpose |
| --- | --- |
| Regime | Interprets market snapshot context and scenario balance |
| Narrative | Reviews recent headlines and possible catalysts |
| Risk | Produces counter-thesis, risks, and invalidation conditions |

## Final Memo

The final memo contains:

- normalized thesis
- bull/base/bear scenario weights
- supporting evidence
- opposing evidence
- catalysts
- risks
- invalidation triggers
- confidence rationale
- specialist provenance
- specialist evidence source hashes for supporting and opposing evidence
- verifier attestations
- partial-run warning when a role is unavailable

Rejected specialist output is not silently discarded. The verifier records an
attestation, the coordinator keeps rejected responses separate from accepted
responses, and synthesis surfaces rejected output in opposing evidence.

## Non-Goals

- No trade execution.
- No brokerage or exchange integration.
- No portfolio optimization.
- No generic chatbot interface as the primary product.
- No hidden local fallback that pretends to be a remote AXL peer.
