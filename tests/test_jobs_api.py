import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from eth_account import Account
from httpx import ASGITransport

from app.chain.receipts import ChainReceipt, JobChainReceipts
from app.chain.verification import ChainTxVerification
from app.coordinator.service import CoordinatorDispatchResult
from app.coordinator.synthesis import MemoSynthesisService
from app.evaluation.attestations import (
    verification_attestation_hash,
    verification_attestation_message,
)
from app.evaluation.reputation import build_reputation_updates
from app.identity.hashing import canonical_json_hash
from app.main import app
from app.schemas.contracts import (
    ScenarioView,
    SpecialistResponse,
    ThesisRequest,
    VerificationAttestation,
)
from app.store import JobStore


REE_FIXTURES = Path(__file__).parent / "fixtures" / "ree"
TEST_VERIFIER_PRIVATE_KEY = "0x" + "01" * 32


class StubCoordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ThesisRequest]] = []

    async def dispatch(
        self,
        job_id: str,
        request: ThesisRequest,
    ) -> CoordinatorDispatchResult:
        self.calls.append((job_id, request))
        return CoordinatorDispatchResult(
            responses=[
                _specialist_response(
                    job_id=job_id,
                    node_role="regime",
                    peer_id="peer-regime-test",
                    summary="Regime supports upside.",
                    signals=["Positive liquidity regime"],
                    risks=[],
                    scenario_view=ScenarioView(bull=0.45, base=0.35, bear=0.2),
                ),
                _specialist_response(
                    job_id=job_id,
                    node_role="narrative",
                    peer_id="peer-narrative-test",
                    summary="ETF narrative remains active.",
                    signals=["ETF flows remain constructive"],
                    risks=[],
                    scenario_view=ScenarioView(bull=0.4, base=0.4, bear=0.2),
                ),
                _specialist_response(
                    job_id=job_id,
                    node_role="risk",
                    peer_id="peer-risk-test",
                    summary="Break below support invalidates the thesis.",
                    signals=[],
                    risks=["Macro volatility can pressure beta assets"],
                    scenario_view=ScenarioView(bull=0.3, base=0.45, bear=0.25),
                ),
            ],
            topology_snapshot={
                "local_peer_id": "peer-coordinator-test",
                "peers": [
                    "peer-regime-test",
                    "peer-narrative-test",
                    "peer-risk-test",
                ],
            },
            market_snapshot={"price_return": 0.08},
            news_headlines=["ETF flows remain constructive"],
            run_metadata={
                "run_mode": "live-axl",
                "expected_roles": ["regime", "narrative", "risk"],
                "completed_roles": ["regime", "narrative", "risk"],
                "missing_roles": [],
            },
        )


class FailingLLMClient:
    async def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("force fallback path")


class StubChainReceiptService:
    async def record_job_receipts(
        self,
        *,
        job_id: str,
        request: ThesisRequest,
        dispatch_result: CoordinatorDispatchResult,
        memo: object,
    ) -> JobChainReceipts:
        return JobChainReceipts(
            receipt_status="confirmed",
            receipts=[
                ChainReceipt.confirmed(
                    kind="task",
                    tx_hash="0x" + "aa" * 32,
                    explorer_base_url="https://gensyn-testnet.explorer.alchemy.com",
                ),
                *[
                    ChainReceipt.confirmed(
                        kind="contribution",
                        role=response.node_role,
                        tx_hash=f"0x{index:064x}",
                        explorer_base_url=(
                            "https://gensyn-testnet.explorer.alchemy.com"
                        ),
                    )
                    for index, response in enumerate(
                        dispatch_result.responses,
                        start=1,
                    )
                ],
            ],
        )


class StubChainTxVerifier:
    def __init__(self, outcomes: dict[str, ChainTxVerification]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def verify_transaction(self, tx_hash: str) -> ChainTxVerification:
        self.calls.append(tx_hash)
        return self.outcomes[tx_hash]


def _specialist_response(
    job_id: str,
    node_role: str,
    peer_id: str,
    summary: str,
    signals: list[str],
    risks: list[str],
    scenario_view: ScenarioView,
) -> SpecialistResponse:
    return SpecialistResponse(
        job_id=job_id,
        node_role=node_role,
        peer_id=peer_id,
        summary=summary,
        scenario_view=scenario_view,
        signals=signals,
        risks=risks,
        confidence=0.7,
        citations=[],
        timestamp="2026-04-23T00:00:00Z",
    )


def _configure_test_store(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    app.state.job_store = JobStore(database_url=database_url)
    app.state.coordinator_service = StubCoordinator()
    app.state.memo_synthesis_service = MemoSynthesisService(
        llm_client=FailingLLMClient()
    )
    if hasattr(app.state, "chain_receipt_service"):
        delattr(app.state, "chain_receipt_service")
    if hasattr(app.state, "chain_tx_verifier"):
        delattr(app.state, "chain_tx_verifier")
    asyncio.run(app.state.job_store.initialize())


def test_create_job_returns_job_id_and_status(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/jobs",
                json={
                    "thesis": "ETH can rally on improving ETF flows.",
                    "asset": "ETH",
                    "horizon_days": 30,
                },
            )

    response = asyncio.run(_exercise())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"
    assert UUID(payload["job_id"])
    coordinator = app.state.coordinator_service
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0][0] == payload["job_id"]


def test_get_job_returns_persisted_result(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            create_response = await client.post(
                "/jobs",
                json={
                    "thesis": "BTC remains range-bound until macro volatility fades.",
                    "asset": "BTC",
                    "horizon_days": 14,
                },
            )
            job_id = create_response.json()["job_id"]
            get_response = await client.get(f"/jobs/{job_id}")
            return create_response, get_response

    create_response, get_response = asyncio.run(_exercise())
    job_id = create_response.json()["job_id"]

    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["job_id"] == job_id
    assert payload["status"] == "completed"
    assert payload["payload"] == {
        "thesis": "BTC remains range-bound until macro volatility fades.",
        "asset": "BTC",
        "horizon_days": 14,
    }
    assert payload["memo"]["job_id"] == job_id
    assert payload["memo"]["normalized_thesis"] == (
        "Will BTC validate this thesis over 14 days: "
        "BTC remains range-bound until macro volatility fades."
    )
    assert payload["memo"]["partial"] is False
    assert payload["memo"]["provenance"] == [
        {
            "node_role": "regime",
            "peer_id": "peer-regime-test",
            "timestamp": "2026-04-23T00:00:00Z",
        },
        {
            "node_role": "narrative",
            "peer_id": "peer-narrative-test",
            "timestamp": "2026-04-23T00:00:00Z",
        },
        {
            "node_role": "risk",
            "peer_id": "peer-risk-test",
            "timestamp": "2026-04-23T00:00:00Z",
        },
    ]
    assert payload["memo"]["catalysts"] == [
        "Positive liquidity regime",
        "ETF flows remain constructive",
    ]
    assert payload["memo"]["risks"] == ["Macro volatility can pressure beta assets"]
    assert payload["memo"]["invalidation_triggers"] == [
        "Break below support invalidates the thesis."
    ]
    assert payload["run_metadata"]["run_mode"] == "live-axl"
    assert payload["run_metadata"]["completed_roles"] == [
        "regime",
        "narrative",
        "risk",
    ]


def test_job_persists_chain_receipts(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)
    app.state.chain_receipt_service = StubChainReceiptService()

    async def _exercise() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            create_response = await client.post(
                "/jobs",
                json={
                    "thesis": "ETH can rally on improving ETF flows.",
                    "asset": "ETH",
                    "horizon_days": 30,
                },
            )
            job_id = create_response.json()["job_id"]
            return (await client.get(f"/jobs/{job_id}")).json()

    payload = asyncio.run(_exercise())
    run_metadata = payload["run_metadata"]

    assert run_metadata["receipt_status"] == "confirmed"
    assert run_metadata["chain_receipts"] == [
        {
            "kind": "task",
            "status": "confirmed",
            "tx_hash": "0x" + "aa" * 32,
            "explorer_url": (
                "https://gensyn-testnet.explorer.alchemy.com/tx/" + "0x" + "aa" * 32
            ),
        },
        {
            "kind": "contribution",
            "status": "confirmed",
            "tx_hash": "0x" + "01".zfill(64),
            "explorer_url": (
                "https://gensyn-testnet.explorer.alchemy.com/tx/"
                + "0x"
                + "01".zfill(64)
            ),
            "role": "regime",
        },
        {
            "kind": "contribution",
            "status": "confirmed",
            "tx_hash": "0x" + "02".zfill(64),
            "explorer_url": (
                "https://gensyn-testnet.explorer.alchemy.com/tx/"
                + "0x"
                + "02".zfill(64)
            ),
            "role": "narrative",
        },
        {
            "kind": "contribution",
            "status": "confirmed",
            "tx_hash": "0x" + "03".zfill(64),
            "explorer_url": (
                "https://gensyn-testnet.explorer.alchemy.com/tx/"
                + "0x"
                + "03".zfill(64)
            ),
            "role": "risk",
        },
    ]


def test_job_verify_endpoint_returns_proof_bundle(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "verification_attestations": [
                    {
                        "job_id": "job-placeholder",
                        "node_role": "risk",
                        "peer_id": "peer-risk-test",
                        "status": "accepted",
                        "score": 0.91,
                        "output_hash": "0x" + "11" * 32,
                        "ree_receipt_hash": "sha256:" + "22" * 32,
                        "receipt_status": "validated",
                    }
                ],
                "chain_receipts": [
                    {
                        "kind": "contribution",
                        "status": "confirmed",
                        "role": "risk",
                        "tx_hash": "0x" + "33" * 32,
                        "explorer_url": (
                            "https://gensyn-testnet.explorer.alchemy.com/tx/"
                            + "0x"
                            + "33" * 32
                        ),
                        "ree_receipt_hash": "sha256:" + "22" * 32,
                        "ree_status": "validated",
                    }
                ],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    assert payload["status"] == "validated"
    checks = payload["checks"]
    assert checks["output_hashes"]["status"] == "present"
    assert checks["output_hashes"]["items"][0]["output_hash"] == "0x" + "11" * 32
    assert checks["attestations"]["status"] == "present"
    assert checks["ree"]["status"] == "validated"
    assert checks["ree"]["items"][0]["receipt_hash"] == "sha256:" + "22" * 32
    assert checks["chain"]["status"] == "present"
    assert checks["chain"]["items"][0]["tx_hash"] == "0x" + "33" * 32


def test_job_verify_endpoint_recomputes_signed_attestation_hash(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_signed_attestation()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    attestations = payload["checks"]["attestations"]
    assert attestations["status"] == "verified"
    assert attestations["items"][0]["status"] == "verified"


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("attestation_hash", "0x" + "00" * 32),
        ("verifier_signature", "0x" + "00" * 65),
        ("job_id", "job-attacker"),
        ("node_role", "regime"),
        ("peer_id", "peer-attacker"),
        ("status", "rejected"),
        ("score", 0.01),
        ("reasons", ["tampered_after_signing"]),
        ("signature_algorithm", "untrusted"),
    ],
)
def test_job_verify_endpoint_rejects_tampered_signed_attestation_fields(
    tmp_path: Path,
    field: str,
    tampered_value: object,
) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_signed_attestation(
            mutation=(field, tampered_value)
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    assert payload["status"] == "failed"
    attestations = payload["checks"]["attestations"]
    assert attestations["status"] == "failed"
    assert attestations["items"][0]["status"] == "failed"


def test_job_verify_endpoint_marks_missing_evidence(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(run_metadata={})
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    assert payload["status"] == "missing"
    assert payload["checks"]["output_hashes"] == {"status": "missing", "items": []}
    assert payload["checks"]["attestations"] == {"status": "missing", "items": []}
    assert payload["checks"]["ree"] == {"status": "missing", "items": []}
    assert payload["checks"]["chain"] == {"status": "missing", "items": []}


def test_job_verify_endpoint_recomputes_specialist_output_hash(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)
    response = _specialist_response(
        job_id="job-output-hash",
        node_role="risk",
        peer_id="peer-risk-test",
        summary="Risk output is structured.",
        signals=[],
        risks=["Support can fail."],
        scenario_view=ScenarioView(bull=0.3, base=0.4, bear=0.3),
    ).model_dump(mode="json")
    output_hash = canonical_json_hash(response)

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "verification_attestations": [
                    {
                        "job_id": "job-placeholder",
                        "node_role": "risk",
                        "peer_id": "peer-risk-test",
                        "status": "accepted",
                        "score": 0.91,
                        "output_hash": output_hash,
                    }
                ],
                "specialist_responses": [response],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    output_hashes = payload["checks"]["output_hashes"]
    assert output_hashes["status"] == "verified"
    assert output_hashes["items"][0]["status"] == "verified"
    assert output_hashes["items"][0]["output_hash"] == output_hash
    assert output_hashes["items"][0]["recomputed_output_hash"] == output_hash


def test_job_verify_endpoint_fails_tampered_specialist_output_hash(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)
    response = _specialist_response(
        job_id="job-output-hash",
        node_role="risk",
        peer_id="peer-risk-test",
        summary="Risk output is structured.",
        signals=[],
        risks=["Support can fail."],
        scenario_view=ScenarioView(bull=0.3, base=0.4, bear=0.3),
    ).model_dump(mode="json")
    output_hash = canonical_json_hash(response)
    response["summary"] = "Tampered after attestation."

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "verification_attestations": [
                    {
                        "job_id": "job-placeholder",
                        "node_role": "risk",
                        "peer_id": "peer-risk-test",
                        "status": "accepted",
                        "score": 0.91,
                        "output_hash": output_hash,
                    }
                ],
                "specialist_responses": [response],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    output_hashes = payload["checks"]["output_hashes"]
    assert payload["status"] == "failed"
    assert output_hashes["status"] == "failed"
    assert output_hashes["items"][0]["status"] == "failed"
    assert output_hashes["items"][0]["output_hash"] == output_hash
    assert output_hashes["items"][0]["recomputed_output_hash"] != output_hash


def test_job_verify_endpoint_rpc_verifies_confirmed_chain_receipt(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)
    tx_hash = "0x" + "44" * 32
    app.state.chain_tx_verifier = StubChainTxVerifier(
        {
            tx_hash: ChainTxVerification(
                tx_hash=tx_hash,
                status="verified",
                rpc_status="confirmed",
                block_number=123,
                transaction_index=2,
            )
        }
    )

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "chain_receipts": [
                    {
                        "kind": "task",
                        "status": "confirmed",
                        "tx_hash": tx_hash,
                        "explorer_url": (
                            "https://gensyn-testnet.explorer.alchemy.com/tx/" + tx_hash
                        ),
                    }
                ],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    chain = payload["checks"]["chain"]
    assert chain["status"] == "verified"
    assert chain["items"] == [
        {
            "kind": "task",
            "role": "",
            "status": "verified",
            "tx_hash": tx_hash,
            "explorer_url": (
                "https://gensyn-testnet.explorer.alchemy.com/tx/" + tx_hash
            ),
            "rpc_status": "confirmed",
            "block_number": 123,
            "transaction_index": 2,
        }
    ]
    assert app.state.chain_tx_verifier.calls == [tx_hash]


def test_job_verify_endpoint_reports_rpc_chain_edge_states(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)
    failed_tx = "0x" + "55" * 32
    missing_tx = "0x" + "66" * 32
    unavailable_tx = "0x" + "77" * 32
    app.state.chain_tx_verifier = StubChainTxVerifier(
        {
            failed_tx: ChainTxVerification(
                tx_hash=failed_tx,
                status="failed",
                rpc_status="reverted",
            ),
            missing_tx: ChainTxVerification(
                tx_hash=missing_tx,
                status="missing",
                rpc_status="not_found",
            ),
            unavailable_tx: ChainTxVerification(
                tx_hash=unavailable_tx,
                status="present",
                rpc_status="rpc_unavailable",
                error="Gensyn Testnet RPC receipt lookup failed",
            ),
        }
    )

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "chain_receipts": [
                    {
                        "kind": "contribution",
                        "role": "risk",
                        "status": "confirmed",
                        "tx_hash": failed_tx,
                    },
                    {
                        "kind": "contribution",
                        "role": "narrative",
                        "status": "confirmed",
                        "tx_hash": missing_tx,
                    },
                    {
                        "kind": "contribution",
                        "role": "regime",
                        "status": "confirmed",
                        "tx_hash": unavailable_tx,
                    },
                ],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    chain = payload["checks"]["chain"]
    assert chain["status"] == "failed"
    statuses = {item["tx_hash"]: item for item in chain["items"]}
    assert statuses[failed_tx]["status"] == "failed"
    assert statuses[failed_tx]["rpc_status"] == "reverted"
    assert statuses[missing_tx]["status"] == "missing"
    assert statuses[missing_tx]["rpc_status"] == "not_found"
    assert statuses[unavailable_tx]["status"] == "present"
    assert statuses[unavailable_tx]["rpc_status"] == "rpc_unavailable"
    assert statuses[unavailable_tx]["error"] == (
        "Gensyn Testnet RPC receipt lookup failed"
    )


def test_job_verify_endpoint_recomputes_persisted_ree_receipt_body(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)
    receipt_body = json.loads((REE_FIXTURES / "valid_receipt.json").read_text())
    receipt_hash = str(receipt_body["receipt_hash"])

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "verification_attestations": [
                    {
                        "job_id": "job-placeholder",
                        "node_role": "risk",
                        "peer_id": "peer-risk-test",
                        "status": "accepted",
                        "score": 0.91,
                        "output_hash": "0x" + "11" * 32,
                        "ree_receipt_hash": receipt_hash,
                        "receipt_status": "validated",
                        "ree_receipt_body": receipt_body,
                    }
                ],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    ree = payload["checks"]["ree"]
    assert ree["status"] == "validated"
    assert ree["items"][0]["status"] == "validated"
    assert ree["items"][0]["receipt_hash"] == receipt_hash
    assert ree["items"][0]["recomputed_receipt_hash"] == receipt_hash
    assert ree["items"][0]["validation_source"] == "body"


def test_job_verify_endpoint_fails_tampered_ree_receipt_body(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)
    receipt_body = json.loads((REE_FIXTURES / "valid_receipt.json").read_text())
    receipt_hash = str(receipt_body["receipt_hash"])
    receipt_body["receipt_hash"] = "sha256:" + "ff" * 32

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "verification_attestations": [
                    {
                        "job_id": "job-placeholder",
                        "node_role": "risk",
                        "peer_id": "peer-risk-test",
                        "status": "accepted",
                        "score": 0.91,
                        "output_hash": "0x" + "11" * 32,
                        "ree_receipt_hash": receipt_hash,
                        "receipt_status": "validated",
                        "ree_receipt_body": receipt_body,
                    }
                ],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    ree = payload["checks"]["ree"]
    assert payload["status"] == "failed"
    assert ree["status"] == "failed"
    assert ree["items"][0]["status"] == "failed"
    assert ree["items"][0]["recomputed_receipt_hash"] == receipt_hash
    assert ree["items"][0]["error"] == (
        "REE receipt hash does not match recomputed hash"
    )


def test_job_verify_endpoint_recomputes_persisted_ree_receipt_path(
    tmp_path: Path,
) -> None:
    _configure_test_store(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text((REE_FIXTURES / "valid_receipt.json").read_text())
    receipt_body = json.loads(receipt_path.read_text())
    receipt_hash = str(receipt_body["receipt_hash"])

    async def _exercise() -> dict[str, object]:
        job_id = await _create_completed_job_with_metadata(
            run_metadata={
                "verification_attestations": [
                    {
                        "job_id": "job-placeholder",
                        "node_role": "risk",
                        "peer_id": "peer-risk-test",
                        "status": "accepted",
                        "score": 0.91,
                        "output_hash": "0x" + "11" * 32,
                        "ree_receipt_hash": receipt_hash,
                        "receipt_status": "validated",
                        "ree_receipt_path": str(receipt_path),
                    }
                ],
            }
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get(f"/jobs/{job_id}/verify")).json()

    payload = asyncio.run(_exercise())

    ree = payload["checks"]["ree"]
    assert ree["status"] == "validated"
    assert ree["items"][0]["validation_source"] == "path"
    assert ree["items"][0]["recomputed_receipt_hash"] == receipt_hash


def test_reputation_endpoint_returns_local_projection(tmp_path: Path) -> None:
    _configure_test_store(tmp_path)

    async def _exercise() -> dict[str, object]:
        job = await app.state.job_store.create_job(
            ThesisRequest(
                thesis="ETH can rally on improving ETF flows.",
                asset="ETH",
                horizon_days=30,
            )
        )
        memo = await MemoSynthesisService(llm_client=FailingLLMClient()).synthesize(
            job_id=job.job_id,
            request=ThesisRequest(
                thesis="ETH can rally on improving ETF flows.",
                asset="ETH",
                horizon_days=30,
            ),
            dispatch_result=CoordinatorDispatchResult(
                responses=[],
                topology_snapshot={},
                market_snapshot={},
                news_headlines=[],
            ),
        )
        await app.state.job_store.complete_job(
            job_id=job.job_id,
            memo=memo,
            run_metadata={
                "reputation_updates": [
                    update.to_dict()
                    for update in build_reputation_updates(
                        [
                            VerificationAttestation(
                                job_id=job.job_id,
                                node_role="regime",
                                peer_id="peer-regime-test",
                                signer="0xFCAd0B19bB29D4674531d6f115237E16AfCE377c",
                                agent_wallet="0xFCAd0B19bB29D4674531d6f115237E16AfCE377c",
                                output_hash="0x" + "11" * 32,
                                status="accepted",
                                score=0.9,
                            )
                        ]
                    )
                ]
            },
        )
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get("/reputation")).json()

    payload = asyncio.run(_exercise())

    assert payload == {
        "leaderboard": [
            {
                "node_role": "regime",
                "peer_id": "peer-regime-test",
                "reputation_points": 90.0,
                "accepted_contributions": 1,
                "rejected_contributions": 0,
                "total_verifier_score": 0.9,
            }
        ]
    }


async def _create_completed_job_with_metadata(
    run_metadata: dict[str, object],
) -> str:
    request = ThesisRequest(
        thesis="ETH can rally on improving ETF flows.",
        asset="ETH",
        horizon_days=30,
    )
    job = await app.state.job_store.create_job(request)
    memo = await MemoSynthesisService(llm_client=FailingLLMClient()).synthesize(
        job_id=job.job_id,
        request=request,
        dispatch_result=CoordinatorDispatchResult(
            responses=[],
            topology_snapshot={},
            market_snapshot={},
            news_headlines=[],
        ),
    )
    metadata = {
        key: [
            {**item, "job_id": job.job_id}
            if isinstance(item, dict) and item.get("job_id") == "job-placeholder"
            else item
            for item in value
        ]
        if isinstance(value, list)
        else value
        for key, value in run_metadata.items()
    }
    await app.state.job_store.complete_job(
        job_id=job.job_id,
        memo=memo,
        provenance_ledger=[
            {
                "node_role": "risk",
                "peer_id": "peer-risk-test",
                "status": "completed",
                "latency_ms": 12.5,
            }
        ],
        run_metadata=metadata,
    )
    return job.job_id


async def _create_completed_job_with_signed_attestation(
    *,
    mutation: tuple[str, object] | None = None,
) -> str:
    request = ThesisRequest(
        thesis="ETH can rally on improving ETF flows.",
        asset="ETH",
        horizon_days=30,
    )
    job = await app.state.job_store.create_job(request)
    unsigned = VerificationAttestation(
        job_id=job.job_id,
        node_role="risk",
        peer_id="peer-risk-test",
        status="accepted",
        score=0.91,
        reasons=["deterministic_score=0.9100", "risks_present"],
        signer="0xFCAd0B19bB29D4674531d6f115237E16AfCE377c",
        agent_wallet="0xFCAd0B19bB29D4674531d6f115237E16AfCE377c",
        output_hash="0x" + "11" * 32,
    )
    attestation_hash = verification_attestation_hash(unsigned)
    verifier = Account.from_key(TEST_VERIFIER_PRIVATE_KEY).address
    signature = Account.sign_message(
        verification_attestation_message(attestation_hash),
        private_key=TEST_VERIFIER_PRIVATE_KEY,
    )
    signed = unsigned.model_copy(
        update={
            "verifier": verifier,
            "attestation_hash": attestation_hash,
            "verifier_signature": f"0x{signature.signature.hex()}",
            "signature_algorithm": "eip191",
        }
    ).model_dump(mode="json")
    if mutation is not None:
        field, value = mutation
        signed[field] = value

    memo = await MemoSynthesisService(llm_client=FailingLLMClient()).synthesize(
        job_id=job.job_id,
        request=request,
        dispatch_result=CoordinatorDispatchResult(
            responses=[],
            topology_snapshot={},
            market_snapshot={},
            news_headlines=[],
        ),
    )
    await app.state.job_store.complete_job(
        job_id=job.job_id,
        memo=memo,
        run_metadata={"verification_attestations": [signed]},
    )
    return job.job_id
