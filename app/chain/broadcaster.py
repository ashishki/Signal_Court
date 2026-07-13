"""RPC-backed chain receipt recorder for completed jobs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from eth_utils import keccak

from app.chain.client import SignalContractsClient
from app.chain.config import ChainConfig
from app.chain.receipts import ChainReceipt, JobChainReceipts
from app.coordinator.service import CoordinatorDispatchResult
from app.identity.hashing import canonical_json_hash
from app.schemas.contracts import FinalMemo, TaskSpec, ThesisRequest

ZERO_BYTES32 = "0x" + "00" * 32
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SCORE_SCALE = 1_000_000


@dataclass(frozen=True)
class BroadcastReceipt:
    tx_hash: str
    status: str


class JsonRpcTransport:
    def __init__(self, rpc_url: str) -> None:
        self._rpc_url = rpc_url
        self._request_id = 0

    def call(self, method: str, params: list[object]) -> object:
        self._request_id += 1
        request = Request(
            self._rpc_url,
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("Gensyn Testnet RPC request failed") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("Gensyn Testnet RPC response must be an object")
        if "error" in payload:
            raise RuntimeError("Gensyn Testnet RPC returned an error")
        return payload.get("result")


class GensynReceiptRecorder:
    def __init__(
        self,
        *,
        config: ChainConfig,
        transport: JsonRpcTransport | None = None,
        confirmations_timeout_seconds: float = 60.0,
    ) -> None:
        self._config = config
        self._client = SignalContractsClient(config)
        self._transport = transport or JsonRpcTransport(config.rpc_url)
        self._confirmations_timeout_seconds = confirmations_timeout_seconds

    async def record_job_receipts(
        self,
        *,
        job_id: str,
        request: ThesisRequest,
        dispatch_result: CoordinatorDispatchResult,
        memo: FinalMemo,
    ) -> JobChainReceipts:
        del memo
        nonce = self._get_nonce()
        gas_price = self._get_gas_price()
        receipts: list[ChainReceipt] = []

        task_spec = TaskSpec(
            job_id=job_id,
            thesis=request.thesis,
            asset=request.asset,
            horizon_days=request.horizon_days,
        )
        task_hash = canonical_json_hash(task_spec)
        task_tx = self._client.sign_create_task_transaction(
            task_hash=task_hash,
            metadata_uri=f"signal-count://jobs/{job_id}/task",
            nonce=nonce,
            gas_price_wei=gas_price,
        )
        task_receipt = self._broadcast_and_wait(task_tx.raw_transaction)
        receipts.append(
            ChainReceipt.confirmed(
                kind="task",
                tx_hash=task_receipt.tx_hash,
                explorer_base_url=self._config.explorer_base_url,
            )
        )

        task_id = self._latest_task_id()
        for index, response in enumerate(dispatch_result.responses, start=1):
            ree_receipt_hash = (
                getattr(response, "ree_receipt_hash", None) or ZERO_BYTES32
            )
            contribution_tx = self._client.sign_record_contribution_transaction(
                task_id=task_id,
                agent=self._writer_address(),
                role=response.node_role,
                output_hash=canonical_json_hash(response),
                ree_receipt_hash=ree_receipt_hash,
                metadata_uri=(
                    f"signal-count://jobs/{job_id}/contributions/{response.node_role}"
                ),
                nonce=nonce + index,
                gas_price_wei=gas_price,
            )
            contribution_receipt = self._broadcast_and_wait(
                contribution_tx.raw_transaction
            )
            receipts.append(
                ChainReceipt.confirmed(
                    kind="contribution",
                    role=response.node_role,
                    tx_hash=contribution_receipt.tx_hash,
                    explorer_base_url=self._config.explorer_base_url,
                    ree_receipt_hash=(
                        None if ree_receipt_hash == ZERO_BYTES32 else ree_receipt_hash
                    ),
                    ree_status=getattr(response, "receipt_status", None),
                )
            )

        if self._config.reputation_vault_address != ZERO_ADDRESS:
            receipts.extend(
                self._record_reputation_updates(
                    job_id=job_id,
                    task_id=task_id,
                    updates=_accepted_reputation_updates(dispatch_result.run_metadata),
                    starting_nonce=nonce + len(dispatch_result.responses) + 1,
                    gas_price=gas_price,
                )
            )

        return JobChainReceipts(receipt_status="confirmed", receipts=receipts)

    def _record_reputation_updates(
        self,
        *,
        job_id: str,
        task_id: int,
        updates: list[dict[str, object]],
        starting_nonce: int,
        gas_price: int,
    ) -> list[ChainReceipt]:
        receipts: list[ChainReceipt] = []
        for index, update in enumerate(updates):
            score = _scaled_int(update["verifier_score"])
            points = _scaled_int(update["reputation_points"])
            role = str(update["node_role"])
            agent = str(update["agent_wallet"])
            payout_wei = _update_payout_wei(
                update=update,
                fallback=self._native_test_payout_wei(),
                max_wei=self._config.native_test_payout_max_wei,
            )
            if payout_wei:
                reputation_tx = self._client.sign_record_reputation_payout_transaction(
                    task_id=task_id,
                    agent=agent,
                    role=role,
                    score=score,
                    points=points,
                    payout_wei=payout_wei,
                    metadata_uri=f"signal-count://jobs/{job_id}/reputation/{role}",
                    nonce=starting_nonce + index,
                    gas_price_wei=gas_price,
                )
            else:
                reputation_tx = self._client.sign_record_reputation_transaction(
                    task_id=task_id,
                    agent=agent,
                    role=role,
                    score=score,
                    points=points,
                    metadata_uri=f"signal-count://jobs/{job_id}/reputation/{role}",
                    nonce=starting_nonce + index,
                    gas_price_wei=gas_price,
                )
            reputation_receipt = self._broadcast_and_wait(reputation_tx.raw_transaction)
            receipts.append(
                ChainReceipt.confirmed(
                    kind="reputation",
                    role=role,
                    agent=agent,
                    tx_hash=reputation_receipt.tx_hash,
                    explorer_base_url=self._config.explorer_base_url,
                    verifier_score=float(update["verifier_score"]),
                    reputation_points=float(update["reputation_points"]),
                    native_test_payout_wei=payout_wei or None,
                )
            )
        return receipts

    def _native_test_payout_wei(self) -> int:
        if not self._config.native_test_payouts_enabled:
            return 0
        return min(
            self._config.native_test_payout_wei,
            self._config.native_test_payout_max_wei,
        )

    def _get_nonce(self) -> int:
        result = self._transport.call(
            "eth_getTransactionCount",
            [self._writer_address(), "pending"],
        )
        return _hex_to_int(result)

    def _get_gas_price(self) -> int:
        return _hex_to_int(self._transport.call("eth_gasPrice", []))

    def _broadcast_and_wait(self, raw_transaction: str) -> BroadcastReceipt:
        result = self._transport.call("eth_sendRawTransaction", [raw_transaction])
        tx_hash = _expect_hex_string(result)
        receipt = self._wait_for_receipt(tx_hash)
        if _hex_to_int(receipt.get("status")) != 1:
            raise RuntimeError("Gensyn Testnet transaction failed")
        return BroadcastReceipt(tx_hash=tx_hash, status="confirmed")

    def _wait_for_receipt(self, tx_hash: str) -> dict[str, object]:
        deadline = time.monotonic() + self._confirmations_timeout_seconds
        while time.monotonic() < deadline:
            result = self._transport.call("eth_getTransactionReceipt", [tx_hash])
            if isinstance(result, dict):
                return result
            time.sleep(1.0)
        raise TimeoutError("Gensyn Testnet transaction receipt timed out")

    def _latest_task_id(self) -> int:
        data = "0x" + keccak(text="nextTaskId()")[:4].hex()
        result = self._transport.call(
            "eth_call",
            [{"to": self._config.task_registry_address, "data": data}, "latest"],
        )
        return _hex_to_int(result) - 1

    def _writer_address(self) -> str:
        from eth_account import Account

        return Account.from_key(self._config.writer_private_key).address


def _hex_to_int(value: object) -> int:
    return int(_expect_hex_string(value), 16)


def _expect_hex_string(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RuntimeError("Gensyn Testnet RPC returned an invalid hex value")
    return value


def _accepted_reputation_updates(
    run_metadata: dict[str, object],
) -> list[dict[str, object]]:
    raw_updates = run_metadata.get("reputation_updates", [])
    if not isinstance(raw_updates, list):
        return []
    return [
        update
        for update in raw_updates
        if isinstance(update, dict)
        and update.get("verifier_status") == "accepted"
        and update.get("credit_eligible") is True
        and update.get("agent_wallet")
        and float(update.get("verifier_score", 0.0)) > 0.0
        and float(update.get("reputation_points", 0.0)) > 0.0
    ]


def _update_payout_wei(
    *,
    update: dict[str, object],
    fallback: int,
    max_wei: int,
) -> int:
    raw = update.get("native_test_payout_wei")
    if raw is None:
        return fallback
    return min(max(int(raw), 0), max_wei)


def _scaled_int(value: object) -> int:
    return round(float(value) * SCORE_SCALE)
