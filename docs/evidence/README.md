# Public Evidence Index

This index is the reviewer path for the Signal Count evidence-tag candidate.
The canonical bundle is [`evidence/public-fixture-v1`](../../evidence/public-fixture-v1).

## Reproduce in Five Minutes

From a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r requirements-lock.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
python scripts/build_public_evidence.py --verify evidence/public-fixture-v1
```

Expected addresses:

- Evidence: `sha256:0b1691ae31b574072e1bac0d52a375e1cae6329bccb82f1143bc18571fa3ef2e`
- Manifest: `sha256:f6cb59c6ab618f23c4b3cbb4e0c3b44baf45b1b936e6dc4fca4d6b2cfcd19f1a`

`manifest.json` binds the evidence and environment bytes to the fixture, the
synthetic receipt, the dependency lock, the generator, and the historical
testnet source document. `environment.json` records the exact canonical build
environment and clearly states that it is provenance, not remote attestation.

## Claim Matrix

| Surface | Tracked evidence | Verified statement | Boundary |
| --- | --- | --- | --- |
| Specialist routing | `routing_selection` | The repository's application capability registry selects one topology-up fixture peer for each of three roles and derives an MCP target. | Selection only; no AXL request was sent. |
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

## Version and Network Prerequisites

The public fixture needs neither Docker nor network access after its hashed
Python distributions are installed. Local receipt validation supports the
repository's documented REE v0.2-style master commitment and content hashes
encoded as `sha256:<digest>` or Ethereum-compatible `0x<keccak256>` values.
Unknown component algorithms fail closed; a newer
[Gensyn REE](https://github.com/gensyn-ai/ree) receipt remains `parsed` until its
schema and algorithms receive an explicit compatibility review.

Historical Gensyn Testnet references use chain ID `685685` and are bound only
to [`docs/gensyn-contracts.md`](../gensyn-contracts.md). Reproduction performs
no RPC lookup, receipt confirmation, transaction submission, or balance check.

## Negative Claims

This bundle is not evidence of live networking, users, production operation,
trading performance, model quality, economic security, protocol security, a
remote AXL mesh, a real REE run, or a new testnet transaction. Report a mismatch
with the proof-verification issue form; never attach secrets or private runtime
artifacts.
