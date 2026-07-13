"""Tamper demo artifact builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eth_account import Account

from app.identity.signing import sign_agent_execution
from app.schemas.contracts import (
    AgentIdentity,
    ScenarioView,
    SignedAgentExecution,
    SpecialistResponse,
    TaskSpec,
)
from app.tamper.adversarial import (
    ATTACK_FUNCTIONS,
    ATTACKS,
)
from app.tamper.detector import detect_tampering

DEMO_VICTIM_KEY = "0x1111111111111111111111111111111111111111111111111111111111111111"
DEMO_ATTACKER_KEY = "0x2222222222222222222222222222222222222222222222222222222222222222"
SYNTHETIC_RECEIPT = (
    Path(__file__).resolve().parents[1]
    / "ree"
    / "fixtures"
    / "synthetic_public_receipt.json"
)


def build_honest_execution() -> SignedAgentExecution:
    victim_address = Account.from_key(DEMO_VICTIM_KEY).address
    receipt_body = json.loads(SYNTHETIC_RECEIPT.read_text(encoding="utf-8"))
    task = TaskSpec(
        job_id="demo-job-tamper-001",
        thesis="ETH continues to lead L2 settlement volume into the next quarter.",
        asset="ETH",
        horizon_days=30,
    )
    response = SpecialistResponse(
        job_id=task.job_id,
        node_role="risk",
        peer_id="peer-risk-demo-001",
        summary=(
            "Counter-thesis exists: rollup-fee compression could materially "
            "lower settlement revenue if blob market clears below 2 gwei."
        ),
        scenario_view=ScenarioView(bull=0.30, base=0.50, bear=0.20),
        signals=[
            "Blob fee market is below the prior 30-day median.",
            "L2 sequencer revenue concentrated in two operators.",
        ],
        risks=[
            "Rollup operator outage with no fast-bridge fallback.",
            "Fee market regression below settlement breakeven.",
        ],
        confidence=0.62,
        citations=[],
        timestamp="2026-05-03T00:00:00Z",
        agent_wallet=victim_address,
        ree_receipt_hash=receipt_body["receipt_hash"],
        receipt_status="validated",
        ree_prompt_hash=receipt_body["prompt_hash"],
        ree_tokens_hash=receipt_body["tokens_hash"],
        ree_model_name=receipt_body["model_name"],
        ree_receipt_body=receipt_body,
        ree_receipt_path=None,
    )
    identity = AgentIdentity(
        role="risk",
        peer_id=response.peer_id,
        wallet=victim_address,
    )
    return sign_agent_execution(
        task=task,
        response=response,
        identity=identity,
        private_key=DEMO_VICTIM_KEY,
    )


def run_side_by_side() -> dict[str, Any]:
    honest = build_honest_execution()
    honest_result = detect_tampering(honest)

    attacker_address = Account.from_key(DEMO_ATTACKER_KEY).address
    scenarios: list[dict[str, Any]] = []

    for attack in ATTACKS:
        mutate = ATTACK_FUNCTIONS[attack.name]
        if attack.name in {"agent_wallet_substitution", "signer_swap_in_envelope"}:
            tampered = mutate(honest, attacker_address)
        elif attack.name == "forged_signature_with_attacker_key":
            tampered = mutate(honest, DEMO_ATTACKER_KEY)
        else:
            tampered = mutate(honest)

        result = detect_tampering(tampered)
        scenarios.append(
            {
                "attack": {
                    "name": attack.name,
                    "description": attack.description,
                    "expected_failed_checks": list(attack.expected_failed_checks),
                },
                "detection": result.to_dict(),
                "tampered_execution": tampered.model_dump(mode="json"),
            }
        )

    return {
        "schema": "signal-count.tamper-evidence/v1",
        "honest": {
            "execution": honest.model_dump(mode="json"),
            "detection": honest_result.to_dict(),
        },
        "attacks": scenarios,
        "summary": {
            "honest_status": honest_result.status,
            "attack_count": len(scenarios),
            "all_attacks_caught": all(
                scenario["detection"]["status"] == "tampered" for scenario in scenarios
            ),
            "attacks_caught": [
                scenario["attack"]["name"]
                for scenario in scenarios
                if scenario["detection"]["status"] == "tampered"
            ],
            "attacks_missed": [
                scenario["attack"]["name"]
                for scenario in scenarios
                if scenario["detection"]["status"] != "tampered"
            ],
        },
    }
