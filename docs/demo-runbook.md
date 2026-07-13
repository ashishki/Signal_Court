# Signal Count Demo Runbook

## Judge-First Demo Target

If a new demo run is executed and its raw artifacts are retained, the walkthrough
should start from that completed proof console, not from setup or a blank thesis
form.

One-sentence pitch:

```text
Signal Count lets you verify every AI agent behind a risk memo: AXL peer,
wallet, output hash, REE receipt, verifier attestation, and Gensyn Testnet tx.
```

Conditional 90-second flow after a newly verified prewarm:

1. Open `/` after the new run is prewarmed. Confirm the displayed job ID matches
   the retained raw job artifact before using the active `Verify Run` tab.
2. Say: "Do not trust the memo. Verify every specialist behind it."
3. Click `open proof bundle` and show output hashes, verifier attestations, REE,
   and chain status. Say which rows are `verified`, `validated`, `present`, or
   `missing`.
4. Return to the proof console and show `Task Trace`: role, AXL peer, wallet,
   output hash, REE status, and tx link.
5. Show `Risk REE Proof` and explain that `validated` means local receipt
   consistency, while `verified` is reserved for checks that recompute or verify
   the underlying proof/signature.
6. Open one Gensyn Testnet explorer link if the run has real chain receipts.
7. Show `Run Evidence` and topology / peer selection. If fallback happened,
   point at `fallback_from=...` and the attempted peer chain.
8. Switch to `Risk Memo`, show source quality, counter-thesis, and invalidation
   triggers. Say: "This is decision support, not trading advice."
9. End with: "AXL makes coordination visible; REE and receipts make the AI work
   auditable."

30-second sponsor pitch:

```text
Signal Count is a proof console for AXL-routed AI analyst work. A coordinator
routes regime, narrative, and risk specialists through AXL, then the UI lets a
judge verify the run: peer IDs, wallet attestations, output hashes, REE receipt
metadata, Gensyn Testnet txs, and source quality. The point is not that agents
wrote a memo. The point is that every agent behind the memo is auditable.
```

Remove from the judge-visible flow:

- long terminal setup
- raw JSON unless asked
- random mesh animation metrics as proof
- native test payout discussion unless the judge asks about incentives
- offline fixture evidence unless it is clearly labelled as non-live

## Historical Recording Notes (`present_only`)

Older operator notes described a May 2026 full-battle capture, but its ignored
`.runtime/full-battle` directory and submission pack are absent from a clean
checkout. Those notes are `present_only`: this runbook does not claim an active
successful full-battle run, available Docker images, open browser session,
verified proof bundle, or replayable raw evidence.

For a new capture, first run the credential and dependency preflight:

```bash
scripts/run_full_battle_demo.sh --preflight-only
```

Only after a new full-battle run has produced raw artifacts, run the artifact
rehearsal helper:

```bash
scripts/verify_latest_artifact.sh
```

The command must fail when `.runtime/full-battle` is absent. With a newly
generated directory it writes `.runtime/full-battle/rehearsal-report.json`.
If the matching proof-console process was independently started, the optional
`--require-live` mode also checks that run's `/jobs/{job_id}/verify` response:

```bash
scripts/verify_latest_artifact.sh --require-live
```

To replay a newly generated full-battle artifact without starting the app, run:

```bash
scripts/replay_full_battle_artifact.sh
```

This writes `.runtime/full-battle/artifact-replay-report.json`. Any artifact
that lacks repeat-validation material such as `specialist_responses` or the full
REE receipt body/path must remain `present_only`.

No browser URL or job-specific proof-bundle URL is a tracked evidence claim.
Use only URLs printed by the new capture and bind them to its retained job ID.

## Offline Preview

Use this mode for stable screenshots and UI walkthroughs when a live AXL mesh is
not running.

```bash
scripts/run_offline_demo.sh
```

Open:

```text
http://127.0.0.1:8000
```

The topology section should show:

```text
Mode: offline-demo-preview
```

## Partial-Failure Preview

Use this mode to demonstrate degraded execution without pretending the missing
node answered:

```bash
scripts/run_offline_partial_demo.sh
```

Expected UI evidence:

- The memo shows a partial coverage warning.
- `Run Metadata` lists `risk` in `missing_roles`.
- `Run Evidence` shows the risk role as timed out.
- The final memo does not invent risk-node provenance.

## Live AXL Mode

Run these commands in separate terminals after the Gensyn AXL node and MCP
router dependencies are available.

```bash
scripts/run_node_regime.sh
scripts/run_node_narrative.sh
scripts/run_node_risk.sh
scripts/run_app_live.sh
```

Check the AXL state:

```bash
scripts/check_axl.sh
```

Expected evidence for a successful local AXL run:

- The MCP router lists `regime_analyst`, `narrative_analyst`, and `risk_analyst`
  as registered services.
- The AXL topology endpoint returns `our_public_key`.
- A completed job shows `transport=axl-mcp`.
- `Run Evidence` shows all three roles as `completed`.
- Each dispatch target uses `/mcp/{axl_public_key}/{service_name}`.
- `Topology Snapshot` shows the same AXL public key.

Evidence classification for a newly captured run:

- The checks above can establish a local Gensyn AXL node -> MCP router ->
  specialist `/mcp` path when their raw output is retained.
- A completed job can establish coordinator dispatch through `axl-mcp` when the
  job ledger and topology snapshot are retained together.
- Neither result establishes a remote multi-machine AXL mesh.

If the UI returns a server error after a live run, check the topology shape. The
live AXL node may return `peers=null`; the UI now handles that shape and falls
back to `our_public_key` for the local peer display.

## Multi-Peer AXL Mesh Mode

Use this mode for the strongest sponsor demo. It runs two separate AXL nodes
with distinct public keys on the same machine:

- Node A is the coordinator bridge at `http://127.0.0.1:9022`.
- Node B is the remote specialist peer at `http://127.0.0.1:9024`.
- Node B registers specialist services with its own MCP router at
  `http://127.0.0.1:9014`.

Prepare node keys and configs:

```bash
scripts/prepare_axl_mesh_demo.sh
```

Run these in separate terminals:

```bash
scripts/run_axl_mesh_router.sh
scripts/run_axl_mesh_node_a.sh
scripts/run_axl_mesh_node_b.sh
```

Read Node B's public key:

```bash
curl -fsS http://127.0.0.1:9024/topology
```

Export it for the specialist and app terminals:

```bash
export AXL_REMOTE_PEER_ID="<node-b-our_public_key>"
```

Run the specialist services behind Node B's router:

```bash
scripts/run_axl_mesh_specialist.sh regime
scripts/run_axl_mesh_specialist.sh narrative
scripts/run_axl_mesh_specialist.sh risk
```

Run the coordinator app through Node A:

```bash
scripts/run_app_mesh_live.sh
```

Open:

```text
http://127.0.0.1:8004
```

Check the mesh state:

```bash
scripts/check_axl_mesh.sh
```

Expected mesh evidence:

- Coordinator topology shows Node A `our_public_key`.
- Coordinator topology lists Node B as an `up` peer with a different
  `public_key`.
- Remote topology shows Node B `our_public_key`.
- Remote MCP router lists all three specialist services.
- Completed jobs show `AXL_LOCAL_BASE_URL=http://127.0.0.1:9022`.
- `Run Evidence` dispatch targets use Node B's public key.
- `partial=false` and all three roles are `completed`.

When retained with the process logs and topology snapshots, those results
support a local multi-peer AXL claim with distinct peer identities. They do not
support a remote or multi-machine claim unless the run actually uses separate
machines and records that boundary.

## Full Battle Demo

Use this path for the recorded terminal segment. It runs the full stack in one
script and prints video-friendly logs with sections for preflight, AXL mesh,
specialist services, app startup, live job submission, indexer, evidence
summary, and shutdown instructions.

```bash
scripts/run_full_battle_demo.sh
```

The script uses:

- Local two-node AXL mesh.
- MCP router and three specialist services.
- Coordinator app on `http://127.0.0.1:8004`.
- Gensyn REE for the risk specialist path.
- Gensyn Testnet task/contribution/reputation receipts.
- Tiny capped native test-ETH payouts of `1000000000 wei` per role by default.
- One-shot chain indexer after the run completes.

Artifacts are written under:

```text
.runtime/full-battle/
```

Important files:

- `summary.txt` - plain-text run summary without terminal color codes.
- `job.json` - completed job immediately after submission.
- `job-after-indexer.json` - job fetched after the indexer run.
- `index-after-indexer.html` - rendered proof console after indexing.
- `logs/` - per-process logs.

The script leaves the viewer running for screen capture. Stop all demo processes
after recording:

```bash
scripts/stop_full_battle_demo.sh
```

Historical operator notes mention a May 2026 run, but the raw job, logs,
receipts, browser snapshot, verification response, and submission pack are not
tracked. Treat every historical full-battle result as `present_only`; do not
quote its job ID, runtime, counts, REE status, chain status, or bundle status as
active or verified evidence. A replacement claim requires a new capture whose
raw artifact set passes the rehearsal and replay commands above.

## Screenshot Set

For a newly executed and retained run, capture these screenshots in order:

1. Completed proof console with active `Verify Run` tab.
2. `/jobs/{job_id}/verify` proof bundle.
3. `Risk REE Proof` receipt detail.
4. `Task Trace` with AXL peer, wallet, output hash, REE status, and tx link.
5. `Run Evidence` with peer selection/fallback and topology public keys.
6. `Risk Memo` source quality, counter-thesis, and invalidation triggers.
7. Gensyn Testnet explorer tx when real chain receipts are configured.
8. Replayable fixtures and thesis form, only after the completed proof surface.

## Video Structure

- 0:00-0:10: one sentence: "Do not trust the memo. Verify every specialist behind
  it."
- 0:10-0:30: active `Verify Run` tab and proof bundle.
- 0:30-0:55: `Task Trace`, AXL peer IDs, REE status, and chain tx.
- 0:55-1:15: topology / peer selection / fallback evidence.
- 1:15-1:30: memo source quality, counter-thesis, invalidation triggers, and
  claim boundary: decision support, not trading advice.

## Claim Boundaries

- Offline preview is only for stable UI capture and must stay labelled as
  `offline-demo-preview`.
- A same-machine multi-peer AXL capture can evidence distinct local peer
  identities only when its raw topology and process artifacts are retained; it
  does not evidence a remote multi-machine deployment.
- REE should be described as present only when a real receipt exists for the
  run being shown.
- Gensyn Testnet receipt claims require real tx hashes or explorer links.
- Native test-ETH payouts are tiny, capped, opt-in testnet evidence; do not
  describe them as stablecoin or real-money rewards.
