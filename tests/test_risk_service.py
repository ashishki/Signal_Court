import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import Settings
from app.identity.hashing import canonical_json_hash, keccak256_hex
from app.nodes.risk.service import RiskService
from app.ree.receipts import ReeReceipt, compute_receipt_hash
from app.ree.runner import ReeRunOutcome, ReeRunRequest
from app.ree.validator import ReeValidationResult, validate_ree_receipt
from app.schemas.contracts import SpecialistResponse


class StubLLMClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, object]] = []

    async def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        self.calls.append({"model": model, "messages": messages})
        return self.response_text


def test_risk_service_returns_valid_specialist_response() -> None:
    stub_client = StubLLMClient(
        json.dumps(
            {
                "summary": "The thesis faces a material risk of fading if follow-through demand fails to appear.",
                "counter_thesis": "The recent move is positioning-driven and vulnerable to reversal.",
                "risks": [
                    "Momentum buyers may exhaust quickly if flows slow",
                    "Macro repricing can compress risk appetite",
                ],
                "invalidation_triggers": [
                    "Spot demand fails to hold above the breakout zone"
                ],
                "scenario_view": {"bull": 0.20, "base": 0.35, "bear": 0.45},
                "confidence": 0.64,
            }
        )
    )
    service = RiskService(llm_client=stub_client, settings=Settings())

    response = asyncio.run(
        service.analyze(
            job_id="job-risk-123",
            peer_id="peer-risk-example",
            thesis="ETH breaks higher on sustained ETF demand.",
        )
    )

    assert isinstance(response, SpecialistResponse)
    assert response.job_id == "job-risk-123"
    assert response.node_role == "risk"
    assert response.peer_id == "peer-risk-example"
    assert response.summary
    assert any(signal.startswith("counter_thesis: ") for signal in response.signals)
    assert response.confidence == 0.64
    total = (
        response.scenario_view.bull
        + response.scenario_view.base
        + response.scenario_view.bear
    )
    assert total == 1.0
    assert stub_client.calls


def test_risk_service_emits_risks_and_invalidation_triggers() -> None:
    stub_client = StubLLMClient(
        json.dumps(
            {
                "summary": "Upside remains fragile because supporting flows are still unproven.",
                "counter_thesis": "The move can unwind once event-driven enthusiasm fades.",
                "risks": ["Flows reverse after the initial catalyst window"],
                "invalidation_triggers": [
                    "Price closes back below the prior range high",
                    "ETF flow data misses expectations for multiple sessions",
                ],
                "scenario_view": {"bull": 0.25, "base": 0.35, "bear": 0.40},
                "confidence": 0.58,
            }
        )
    )
    service = RiskService(llm_client=stub_client, settings=Settings())

    response = asyncio.run(
        service.analyze(
            job_id="job-risk-456",
            peer_id="peer-risk-example",
            thesis="ETH can sustain a breakout through continued ETF inflows.",
        )
    )

    assert any(risk.startswith("risk: ") for risk in response.risks)
    assert any(signal.startswith("invalidation: ") for signal in response.signals)


def test_risk_service_raises_value_error_for_non_json_response() -> None:
    stub_client = StubLLMClient("not json")
    service = RiskService(llm_client=stub_client, settings=Settings())

    try:
        asyncio.run(
            service.analyze(
                job_id="job-risk-invalid-json",
                peer_id="peer-risk-example",
                thesis="A thesis string",
            )
        )
    except ValueError as exc:
        assert str(exc) == "LLM response is not valid JSON"
    else:
        raise AssertionError("Expected ValueError for invalid JSON response")


def test_risk_service_uses_safe_default_for_missing_counter_thesis() -> None:
    stub_client = StubLLMClient(
        json.dumps(
            {
                "summary": "Risk conditions remain fragile.",
                "risks": ["A risk item"],
                "invalidation_triggers": ["An invalidation trigger"],
                "scenario_view": {"bull": 0.20, "base": 0.30, "bear": 0.50},
                "confidence": 0.5,
            }
        )
    )
    service = RiskService(llm_client=stub_client, settings=Settings())

    response = asyncio.run(
        service.analyze(
            job_id="job-risk-missing-counter-thesis",
            peer_id="peer-risk-example",
            thesis="A thesis string",
        )
    )

    assert (
        "counter_thesis: The thesis can fail if the expected catalyst does not arrive."
        in response.signals
    )


@dataclass
class _StubReeRunner:
    receipt: ReeReceipt
    calls: list[ReeRunRequest]

    def run(
        self, request: ReeRunRequest, *, workspace: Path | None = None
    ) -> ReeRunOutcome:
        self.calls.append(request)
        validation: ReeValidationResult = validate_ree_receipt(self.receipt)
        return ReeRunOutcome(
            receipt=self.receipt,
            validation=validation,
            receipt_path=Path("/tmp/stub-ree-receipt.json"),
            receipt_status="validated" if validation.matches else "parsed",
        )


def test_risk_service_uses_ree_output_when_enabled() -> None:
    text_output = json.dumps(
        {
            "summary": "REE-backed risk view: thesis fragility centers on flow exhaustion.",
            "counter_thesis": "Spot demand is fragile and can revert quickly.",
            "risks": [
                "Persistent leverage may unwind on a flow miss",
                "Cross-asset correlation tightens in risk-off regimes",
            ],
            "invalidation_triggers": ["Spot ETF flow trend reverses for 3+ sessions"],
            "scenario_view": {"bull": 0.20, "base": 0.30, "bear": 0.50},
            "confidence": 0.66,
        }
    )
    model_name = "Qwen/Qwen3-0.6B"
    commit_hash = keccak256_hex(b"model:Qwen/Qwen3-0.6B")
    config_hash = keccak256_hex(b'{"max_new_tokens":300}')
    prompt_hash = keccak256_hex(b"ree-prompt-bytes")
    parameters_hash = canonical_json_hash({"max_new_tokens": 300})
    tokens_hash = keccak256_hex(text_output.encode("utf-8"))
    receipt_hash = compute_receipt_hash(
        commit_hash=commit_hash,
        config_hash=config_hash,
        prompt_hash=prompt_hash,
        parameters_hash=parameters_hash,
        tokens_hash=tokens_hash,
    )
    receipt = ReeReceipt(
        model_name=model_name,
        commit_hash=commit_hash,
        config_hash=config_hash,
        prompt="ree-prompt-bytes",
        prompt_hash=prompt_hash,
        parameters={"max_new_tokens": 300},
        parameters_hash=parameters_hash,
        tokens_hash=tokens_hash,
        receipt_hash=receipt_hash,
        text_output=text_output,
        token_count=42,
        finish_reason="eos_token",
    )
    stub_ree = _StubReeRunner(receipt=receipt, calls=[])
    stub_llm = StubLLMClient("UNUSED LLM RESPONSE")
    service = RiskService(
        llm_client=stub_llm,
        settings=Settings(),
        ree_runner=stub_ree,
    )

    response = asyncio.run(
        service.analyze(
            job_id="job-risk-ree",
            peer_id="peer-risk-example",
            thesis="ETH sustains breakout through ETF flows.",
        )
    )

    assert isinstance(response, SpecialistResponse)
    assert response.summary.startswith("REE-backed risk view")
    assert response.ree_receipt_hash == receipt_hash
    assert response.receipt_status == "validated"
    # The LLM client must NOT be invoked when REE supplies the output.
    assert stub_llm.calls == []
    assert len(stub_ree.calls) == 1
    assert stub_ree.calls[0].max_new_tokens == 300


def test_risk_service_keeps_ree_receipt_when_output_is_not_json() -> None:
    text_output = "The primary risk is that ETF demand fades before liquidity improves."
    model_name = "Qwen/Qwen3-0.6B"
    commit_hash = keccak256_hex(b"model:Qwen/Qwen3-0.6B")
    config_hash = keccak256_hex(b'{"max_new_tokens":300}')
    prompt_hash = keccak256_hex(b"ree-prompt-bytes")
    parameters_hash = canonical_json_hash({"max_new_tokens": 300})
    tokens_hash = keccak256_hex(text_output.encode("utf-8"))
    receipt_hash = compute_receipt_hash(
        commit_hash=commit_hash,
        config_hash=config_hash,
        prompt_hash=prompt_hash,
        parameters_hash=parameters_hash,
        tokens_hash=tokens_hash,
    )
    receipt = ReeReceipt(
        model_name=model_name,
        commit_hash=commit_hash,
        config_hash=config_hash,
        prompt="ree-prompt-bytes",
        prompt_hash=prompt_hash,
        parameters={"max_new_tokens": 300},
        parameters_hash=parameters_hash,
        tokens_hash=tokens_hash,
        receipt_hash=receipt_hash,
        text_output=text_output,
        token_count=21,
        finish_reason="eos_token",
    )
    service = RiskService(
        llm_client=StubLLMClient("UNUSED LLM RESPONSE"),
        settings=Settings(),
        ree_runner=_StubReeRunner(receipt=receipt, calls=[]),
    )

    response = asyncio.run(
        service.analyze(
            job_id="job-risk-ree-text",
            peer_id="peer-risk-example",
            thesis="ETH sustains breakout through ETF flows.",
        )
    )

    assert response.summary == text_output
    assert response.ree_receipt_hash == receipt_hash
    assert response.receipt_status == "validated"
    assert response.confidence == 0.35
