"""Tests for REE receipt parsing and local consistency validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ree.receipts import compute_receipt_hash, parse_ree_receipt
from app.ree.validator import validate_ree_receipt

FIXTURES = Path(__file__).parent / "fixtures" / "ree"


def test_parse_ree_receipt_fixture() -> None:
    receipt = parse_ree_receipt(FIXTURES / "valid_receipt.json")

    assert receipt.model_name == "Qwen/Qwen3-0.6B"
    assert receipt.commit_hash.startswith("0x") and len(receipt.commit_hash) == 66
    assert receipt.config_hash.startswith("0x") and len(receipt.config_hash) == 66
    assert receipt.prompt_hash.startswith("0x") and len(receipt.prompt_hash) == 66
    assert (
        receipt.parameters_hash.startswith("0x") and len(receipt.parameters_hash) == 66
    )
    assert receipt.tokens_hash.startswith("0x") and len(receipt.tokens_hash) == 66
    assert (
        receipt.receipt_hash.startswith("sha256:") and len(receipt.receipt_hash) == 71
    )
    assert receipt.text_output.strip() != ""
    assert receipt.token_count >= 0
    assert receipt.finish_reason != "" or receipt.finish_reason == ""

    expected = compute_receipt_hash(
        commit_hash=receipt.commit_hash,
        config_hash=receipt.config_hash,
        prompt_hash=receipt.prompt_hash,
        parameters_hash=receipt.parameters_hash,
        tokens_hash=receipt.tokens_hash,
    )
    assert receipt.receipt_hash == expected


def test_valid_ree_receipt_passes_validation() -> None:
    receipt = parse_ree_receipt(FIXTURES / "valid_receipt.json")

    result = validate_ree_receipt(receipt)

    assert result.matches is True
    assert result.is_valid is True
    assert result.expected_receipt_hash == receipt.receipt_hash
    assert result.prompt_hash_matches is True
    assert result.parameters_hash_matches is True
    assert result.tokens_hash_matches is True
    assert result.failure_reasons == ()


def test_parse_nested_gensyn_receipt_schema() -> None:
    receipt = parse_ree_receipt(
        {
            "version": "1.1.0",
            "ree_version": "0.1.0",
            "model": {
                "name": "Qwen/Qwen3-0.6B",
                "commit_hash": "c1899de289a04d12100db370d81485cdf75e47ca",
                "config_hash": (
                    "sha256:01a2cd6eaa6ffadcfbf29bf5de383834dde68122b10edc73873d4a06b6758723"
                ),
            },
            "input": {
                "prompt": "Reply with exactly one word: confirmed.",
                "prompt_hash": (
                    "sha256:20d1bf8485ff04df38d3e1dcfdfd0a0e0f1f396767d6339cb8328b995373ae5c"
                ),
                "parameters": {"max_new_tokens": 20, "seed": 12345},
                "parameters_hash": (
                    "sha256:05553f56b3c7f21e35d9e67dae7f1be91af0dee290d9f024e50a41b87cc8a25d"
                ),
            },
            "output": {
                "tokens_hash": (
                    "sha256:9599915bd8cd62b6b42e6c37b5b681a76991a7c5be1fde9971278ce65b99d550"
                ),
                "token_count": 20,
                "finish_reason": "max_length",
                "text_output": "confirmed",
            },
            "execution": {"device_type": "cpu", "device_name": "x86_64"},
            "hashes": {
                "receipt_hash": (
                    "sha256:984f2f2e031e39d37afe04060db89515026bf4f464bcba770ec46cedddb36f18"
                )
            },
        }
    )

    assert receipt.model_name == "Qwen/Qwen3-0.6B"
    assert receipt.version == "1.1.0"
    assert receipt.ree_version == "0.1.0"
    assert receipt.prompt == "Reply with exactly one word: confirmed."
    assert receipt.parameters["max_new_tokens"] == 20
    assert receipt.text_output == "confirmed"
    assert receipt.device_type == "cpu"
    assert receipt.receipt_hash.startswith("sha256:")


def test_nested_gensyn_receipt_passes_validation() -> None:
    receipt = parse_ree_receipt(
        {
            "version": "1.1.0",
            "ree_version": "0.1.0",
            "model": {
                "name": "Qwen/Qwen3-0.6B",
                "commit_hash": "c1899de289a04d12100db370d81485cdf75e47ca",
                "config_hash": (
                    "sha256:01a2cd6eaa6ffadcfbf29bf5de383834dde68122b10edc73873d4a06b6758723"
                ),
            },
            "input": {
                "prompt": "Reply with exactly one word: confirmed.",
                "prompt_hash": (
                    "sha256:20d1bf8485ff04df38d3e1dcfdfd0a0e0f1f396767d6339cb8328b995373ae5c"
                ),
                "parameters": {"max_new_tokens": 20, "seed": 12345},
                "parameters_hash": (
                    "sha256:05553f56b3c7f21e35d9e67dae7f1be91af0dee290d9f024e50a41b87cc8a25d"
                ),
            },
            "output": {
                "tokens_hash": (
                    "sha256:9599915bd8cd62b6b42e6c37b5b681a76991a7c5be1fde9971278ce65b99d550"
                ),
                "token_count": 20,
                "finish_reason": "max_length",
                "text_output": "confirmed",
            },
            "execution": {"device_type": "cpu", "device_name": "x86_64"},
            "hashes": {
                "receipt_hash": (
                    "sha256:984f2f2e031e39d37afe04060db89515026bf4f464bcba770ec46cedddb36f18"
                )
            },
        }
    )

    result = validate_ree_receipt(receipt)

    assert result.matches is True
    assert result.expected_receipt_hash == receipt.receipt_hash


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    (
        ("prompt", "attacker-substituted prompt", "prompt_hash_mismatch"),
        (
            "parameters",
            {"max_new_tokens": 999},
            "parameters_hash_mismatch",
        ),
        ("text_output", "attacker-substituted output", "tokens_hash_mismatch"),
    ),
)
def test_receipt_content_tampering_fails_component_validation(
    field: str,
    replacement: object,
    reason: str,
) -> None:
    receipt = parse_ree_receipt(FIXTURES / "valid_receipt.json")
    tampered = receipt.model_copy(update={field: replacement})

    result = validate_ree_receipt(tampered)

    assert result.receipt_hash_matches is True
    assert result.matches is False
    assert reason in result.failure_reasons


def test_unknown_component_hash_algorithm_fails_closed() -> None:
    receipt = parse_ree_receipt(FIXTURES / "valid_receipt.json")
    unsupported_prompt_hash = "blake3:" + "11" * 32
    tampered = receipt.model_copy(
        update={
            "prompt_hash": unsupported_prompt_hash,
            "receipt_hash": compute_receipt_hash(
                commit_hash=receipt.commit_hash,
                config_hash=receipt.config_hash,
                prompt_hash=unsupported_prompt_hash,
                parameters_hash=receipt.parameters_hash,
                tokens_hash=receipt.tokens_hash,
            ),
        }
    )

    result = validate_ree_receipt(tampered)

    assert result.receipt_hash_matches is True
    assert result.matches is False
    assert result.unsupported_component_hashes == ("prompt",)
    assert "prompt_hash_algorithm_unsupported" in result.failure_reasons


def test_invalid_ree_receipt_fails_validation() -> None:
    receipt = parse_ree_receipt(FIXTURES / "invalid_receipt.json")

    result = validate_ree_receipt(receipt)

    assert result.matches is False
    assert result.is_valid is False
    assert result.expected_receipt_hash != receipt.receipt_hash
    assert result.expected_receipt_hash.startswith("sha256:")
