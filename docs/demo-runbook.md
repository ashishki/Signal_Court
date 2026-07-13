# Signal Count Demo Runbook

## Judge-First Demo Target

The winning demo should start from a completed proof console, not from setup or
a blank thesis form.

One-sentence pitch:

```text
Signal Count lets you verify every AI agent behind a risk memo: AXL peer,
wallet, output hash, REE receipt, verifier attestation, and Gensyn Testnet tx.
```

Target 90-second flow after prewarm:

1. Open `/` after the run is prewarmed. The first screen should already show
   `Latest Verified Run` and the active `Verify Run` / proof ledger tab.
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

## Current Recording State

Current status from May 1, 2026:

- `scripts/run_full_battle_demo.sh` now executes directly and supports
  `--preflight-only`.
- Required Docker images are available locally: `ree` / `gensynai/ree:v0.2.0`
  and `gensyn-axl-local`.
- Full-battle preflight passes outside the sandbox when the recording ports are
  free.
- The latest full-battle run completed successfully and wrote artifacts to
  `.runtime/full-battle/`.
- The proof console is currently meant to be recorded from a prewarmed completed
  run, not from terminal setup.
- CPU-only REE can exceed 900 seconds on some local machines. The full-battle
  runner uses `FULL_BATTLE_JOB_TIMEOUT_SECONDS=1500` by default; override it
  only when you know the local REE path is faster or slower.

Run this before final recording:

```bash
scripts/run_full_battle_demo.sh --preflight-only
```

Run the latest-artifact rehearsal before opening the browser:

```bash
scripts/verify_latest_artifact.sh
```

This validates `.runtime/full-battle` locally and writes
`.runtime/full-battle/rehearsal-report.json`. If the proof console is already
running at `http://127.0.0.1:8004`, it also fetches the live
`/jobs/{job_id}/verify` bundle. To make the live proof-console check mandatory,
run:

```bash
scripts/verify_latest_artifact.sh --require-live
```

To replay the saved full-battle artifact without starting the app, run:

```bash
scripts/replay_full_battle_artifact.sh
```

This writes `.runtime/full-battle/artifact-replay-report.json` and labels old
artifact checks as `present_only` when the saved job lacks repeat-validation
material such as `specialist_responses` or full REE receipt body/path.

If `http://127.0.0.1:8004` is already serving the saved proof console, preflight
will fail on the occupied app port. Stop that UI before running a new full-battle
capture.

Current browser walkthrough target:

```text
http://127.0.0.1:8004
```

Current proof bundle:

```text
http://127.0.0.1:8004/jobs/10ffc70d-1149-490a-8287-51c74d36cf01/verify
```

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

Current verified full-battle reference run from May 2, 2026:

- Job ID: `3beec5c8-3a95-4058-8962-9408fb951465`.
- Runtime: `773s` end to end.
- Live job completed at `+760s`; the remaining time was one-shot indexing and
  evidence summary generation.
- Roles: `regime`, `narrative`, and `risk` completed.
- REE status: `validated`.
- Chain receipts: 7 transaction receipts.
- Live verification bundle: `output_hashes=verified`, `attestations=present`,
  `ree=validated`, `chain=verified`.
- Indexed projection after replay: `tasks=9`, `contributions=23`,
  `verifications=0`, `reputation=23`.
- Latest evidence pack:
  `.runtime/submission-pack/20260502_125554`.

## Screenshot Set

Capture these screenshots in order:

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
- Same-machine multi-peer AXL mesh proves distinct local AXL peer identities,
  not remote multi-machine deployment.
- REE should be described as present only when a real receipt exists for the
  run being shown.
- Gensyn Testnet receipt claims require real tx hashes or explorer links.
- Native test-ETH payouts are tiny, capped, opt-in testnet evidence; do not
  describe them as stablecoin or real-money rewards.
