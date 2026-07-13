# Public Evidence Index

This index is the reviewer path for the Signal Count evidence-tag candidate.
The canonical bundle is [`evidence/public-fixture-v1`](../../evidence/public-fixture-v1).

## Reproduce in Five Minutes

From a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt -e .
python -m pip check
python scripts/build_public_evidence.py --verify evidence/public-fixture-v1
```

Expected addresses:

- Evidence: `sha256:14e6b45b0ed10634ef97d0c5597a7ce8341248541e7bd29bdbd40eed1ff12b64`
- Manifest: `sha256:c9b8d34a1612b6019bd08af2c44b6cd736b59e4043342e3563eb6d2f7e7ffce4`

`manifest.json` binds the evidence and environment bytes to the fixture, the
synthetic receipt, the dependency lock, the generator, and the historical
testnet source document. `environment.json` records the exact canonical build
environment and clearly states that it is provenance, not remote attestation.

## Claim Matrix

| Surface | Tracked evidence | Verified statement | Boundary |
| --- | --- | --- | --- |
| Specialist routing | `routing_selection` | The real capability registry selects one topology-up fixture peer for each of three roles and derives an MCP target. | Selection only; no AXL request was sent. |
| Specialist signatures | `signed_executions` | Three EIP-191 signatures recover their public fixture wallets and bind canonical task/output hashes, role, and peer. | Synthetic responses and identities; no external specialist ran. |
| Verifier attestations | `verifier_attestations` | Three accepted verdicts have recomputable attestation hashes and recover the fixture verifier wallet. | Acceptance is deterministic fixture scoring, not correctness of a market thesis. |
| REE receipt | `receipt_claim_checks` | The synthetic prompt, canonical parameters, and text output match their component hashes; the master commitment matches all declared component hashes. | Commit/config source bytes and non-content metadata are not reconstructed. No model inference or external re-execution; `validated` is not `verified`. |
| Testnet provenance | `historical_testnet_provenance` | Three deployment references are byte-bound to `docs/gensyn-contracts.md` and have deterministic explorer URLs. | Historical documentation references only; no RPC lookup or transaction write occurred. |
| Environment | `environment.json`, `requirements-lock.txt` | Canonical bytes have an exact recorded environment and locked Python dependency set. | The environment record is not a hardware, enclave, or remote-runtime attestation. |

## Files

- `evidence.json`: signed fixture executions, signed verifier attestations,
  receipt checks, routing selections, historical testnet references, and claim
  boundaries.
- `environment.json`: exact canonical generation environment and runtime
  contract.
- `manifest.json`: SHA-256 checksums and the evidence content address.
- `app/evidence/fixtures/public_signed_run.json`: public synthetic task,
  topology, responses, and historical references.
- `app/ree/fixtures/synthetic_public_receipt.json`: REE-shaped synthetic body
  whose local consistency is deliberately reproducible.

No ignored database, `.runtime` output, wallet credential, operator artifact,
or private data was imported. The older full-battle notes in the README remain
`present_only` because their ignored runtime pack is absent from a clean public
checkout.

## Negative Claims

This bundle is not evidence of live networking, users, production operation,
trading performance, model quality, economic security, protocol security, a
remote AXL mesh, a real REE run, or a new testnet transaction. Report a mismatch
with the proof-verification issue form; never attach secrets or private runtime
artifacts.
