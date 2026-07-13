import asyncio
from pathlib import Path

import httpx
from httpx import ASGITransport

from app.chain.broadcaster import GensynReceiptRecorder
from app.chain.config import ChainConfig
from app.coordinator.service import CoordinatorDispatchResult
from app.coordinator.synthesis import MemoSynthesisService
from app.main import app
from app.schemas.contracts import (
    FinalMemo,
    ScenarioView,
    SpecialistResponse,
    ThesisRequest,
)
from app.store import JobStore


class StubCoordinator:
    def __init__(self, *, include_reputation_update: bool = False) -> None:
        self.include_reputation_update = include_reputation_update

    async def dispatch(
        self,
        job_id: str,
        request: ThesisRequest,
    ) -> CoordinatorDispatchResult:
        return CoordinatorDispatchResult(
            responses=[
                SpecialistResponse(
                    job_id=job_id,
                    node_role="risk",
                    peer_id="peer-risk-test",
                    summary="Break below support invalidates the thesis.",
                    scenario_view=ScenarioView(bull=0.3, base=0.45, bear=0.25),
                    signals=[],
                    risks=["Macro volatility can pressure beta assets"],
                    confidence=0.7,
                    citations=[],
                    timestamp="2026-04-27T00:00:00Z",
                )
            ],
            topology_snapshot={"mode": "live-axl"},
            market_snapshot={"price_return": 0.08},
            news_headlines=[],
            run_metadata=_run_metadata(
                job_id=job_id,
                include_reputation_update=self.include_reputation_update,
            ),
        )


def _run_metadata(
    *,
    job_id: str,
    include_reputation_update: bool,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "run_mode": "live-axl",
        "expected_roles": ["risk"],
        "completed_roles": ["risk"],
        "missing_roles": [],
    }
    if include_reputation_update:
        metadata["reputation_updates"] = [
            {
                "job_id": job_id,
                "node_role": "risk",
                "peer_id": "peer-risk-test",
                "agent_wallet": "0x00000000000000000000000000000000000000a1",
                "verifier_status": "accepted",
                "verifier_score": 0.85,
                "credit_eligible": True,
                "reputation_points": 85.0,
                "reason": "verifier_score_credit",
            },
            {
                "job_id": job_id,
                "node_role": "narrative",
                "peer_id": "peer-narrative-test",
                "agent_wallet": "0x00000000000000000000000000000000000000a2",
                "verifier_status": "rejected",
                "verifier_score": 0.0,
                "credit_eligible": False,
                "reputation_points": 0.0,
                "reason": "no_credit_for_rejected_verifier_status",
            },
        ]
    return metadata


class FailingLLMClient:
    async def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("force fallback path")


class FailingChainReceiptService:
    async def record_job_receipts(self, **kwargs: object) -> object:
        raise RuntimeError("rpc unavailable: secret should not leak")


class FakeRpcTransport:
    def __init__(self) -> None:
        self.sent_raw_transactions: list[str] = []
        self._tx_index = 0

    def call(self, method: str, params: list[object]) -> object:
        if method == "eth_getTransactionCount":
            return "0x5"
        if method == "eth_gasPrice":
            return "0x1f5"
        if method == "eth_sendRawTransaction":
            self.sent_raw_transactions.append(str(params[0]))
            self._tx_index += 1
            return f"0x{self._tx_index:064x}"
        if method == "eth_getTransactionReceipt":
            return {"status": "0x1"}
        if method == "eth_call":
            return "0x" + "02".zfill(64)
        raise AssertionError(f"unexpected rpc method: {method}")


def test_gensyn_receipt_recorder_broadcasts_task_and_contributions() -> None:
    transport = FakeRpcTransport()
    recorder = GensynReceiptRecorder(
        config=_chain_config(),
        transport=transport,
        confirmations_timeout_seconds=0.1,
    )
    dispatch_result = asyncio.run(StubCoordinator().dispatch("job-123", _request()))

    receipts = asyncio.run(
        recorder.record_job_receipts(
            job_id="job-123",
            request=_request(),
            dispatch_result=dispatch_result,
            memo=_memo(),
        )
    )

    assert len(transport.sent_raw_transactions) == 2
    assert receipts.to_metadata() == {
        "receipt_status": "confirmed",
        "chain_receipts": [
            {
                "kind": "task",
                "status": "confirmed",
                "tx_hash": "0x" + "01".zfill(64),
                "explorer_url": (
                    "https://gensyn-testnet.explorer.alchemy.com/tx/"
                    + "0x"
                    + "01".zfill(64)
                ),
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
                "role": "risk",
            },
        ],
    }


def test_gensyn_receipt_recorder_broadcasts_accepted_reputation_updates() -> None:
    transport = FakeRpcTransport()
    recorder = GensynReceiptRecorder(
        config=_chain_config(
            reputation_vault_address="0x3a89E81bd2BAE43CbAB6C41c064057CFaa227C87"
        ),
        transport=transport,
        confirmations_timeout_seconds=0.1,
    )
    dispatch_result = asyncio.run(
        StubCoordinator(include_reputation_update=True).dispatch(
            "job-123",
            _request(),
        )
    )

    receipts = asyncio.run(
        recorder.record_job_receipts(
            job_id="job-123",
            request=_request(),
            dispatch_result=dispatch_result,
            memo=_memo(),
        )
    )

    assert len(transport.sent_raw_transactions) == 3
    assert receipts.to_metadata()["chain_receipts"][-1] == {
        "kind": "reputation",
        "status": "confirmed",
        "tx_hash": "0x" + "03".zfill(64),
        "explorer_url": (
            "https://gensyn-testnet.explorer.alchemy.com/tx/" + "0x" + "03".zfill(64)
        ),
        "role": "risk",
        "agent": "0x00000000000000000000000000000000000000a1",
        "verifier_score": 0.85,
        "reputation_points": 85.0,
    }


def test_gensyn_receipt_recorder_broadcasts_capped_native_test_payout() -> None:
    transport = FakeRpcTransport()
    recorder = GensynReceiptRecorder(
        config=_chain_config(
            reputation_vault_address="0x3a89E81bd2BAE43CbAB6C41c064057CFaa227C87",
            native_test_payouts_enabled=True,
            native_test_payout_wei=1_000_000_000,
        ),
        transport=transport,
        confirmations_timeout_seconds=0.1,
    )
    dispatch_result = asyncio.run(
        StubCoordinator(include_reputation_update=True).dispatch(
            "job-123",
            _request(),
        )
    )

    receipts = asyncio.run(
        recorder.record_job_receipts(
            job_id="job-123",
            request=_request(),
            dispatch_result=dispatch_result,
            memo=_memo(),
        )
    )

    assert receipts.to_metadata()["chain_receipts"][-1]["native_test_payout_wei"] == (
        1_000_000_000
    )


def test_chain_failure_degrades_explicitly(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    app.state.job_store = JobStore(database_url=database_url)
    app.state.coordinator_service = StubCoordinator()
    app.state.memo_synthesis_service = MemoSynthesisService(
        llm_client=FailingLLMClient()
    )
    app.state.chain_receipt_service = FailingChainReceiptService()
    asyncio.run(app.state.job_store.initialize())

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

    assert payload["status"] == "completed"
    assert payload["memo"]["job_id"] == payload["job_id"]
    assert payload["memo"]["partial"] is False
    assert payload["run_metadata"]["receipt_status"] == "failed"
    assert payload["run_metadata"]["chain_receipts"] == [
        {
            "kind": "job_receipts",
            "status": "failed",
            "error": "chain receipt write failed",
        }
    ]


def _request() -> ThesisRequest:
    return ThesisRequest(
        thesis="ETH can rally on improving ETF flows.",
        asset="ETH",
        horizon_days=30,
    )


def _memo() -> FinalMemo:
    return FinalMemo(
        job_id="job-123",
        normalized_thesis="Will ETH validate the thesis?",
        scenarios=ScenarioView(bull=0.3, base=0.45, bear=0.25),
    )


def _chain_config(
    *,
    reputation_vault_address: str = "0x0000000000000000000000000000000000000000",
    native_test_payouts_enabled: bool = False,
    native_test_payout_wei: int = 1_000_000_000,
) -> ChainConfig:
    return ChainConfig(
        rpc_url="https://gensyn-testnet.g.alchemy.com/public",
        chain_id=685685,
        explorer_base_url="https://gensyn-testnet.explorer.alchemy.com",
        agent_registry_address="0x9Aa7E223B5bd2384cea38F0d2464Aa6cbB0146A9",
        task_registry_address="0x7b0ED22C93eBdF6Be5c3f6D6fC8F7B51fdFBd861",
        receipt_registry_address="0xb67E197538F2cF9d398c28ec85d4f99fb2e668cf",
        reputation_vault_address=reputation_vault_address,
        native_test_payouts_enabled=native_test_payouts_enabled,
        native_test_payout_wei=native_test_payout_wei,
        writer_private_key=(
            "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
    )
