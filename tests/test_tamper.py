from eth_account import Account

from app.ree.claims import check_receipt_claim
from app.tamper.adversarial import (
    ATTACKS,
    field_tamper_after_sign,
    forged_signature_with_attacker_key,
    receipt_status_overclaim,
    role_substitution,
    signer_swap_in_envelope,
)
from app.tamper.detector import detect_tampering
from app.tamper.harness import (
    DEMO_ATTACKER_KEY,
    build_honest_execution,
    run_side_by_side,
)


def test_honest_execution_is_clean() -> None:
    execution = build_honest_execution()
    result = detect_tampering(execution)

    assert result.status == "clean"
    assert result.failed_check_names == []
    assert check_receipt_claim(execution.response).valid is True


def test_tamper_attacks_are_caught() -> None:
    honest = build_honest_execution()
    attacker = Account.from_key(DEMO_ATTACKER_KEY).address

    cases = [
        (field_tamper_after_sign(honest), {"output_hash_match"}),
        (
            signer_swap_in_envelope(honest, attacker),
            {"signer_equals_identity_wallet", "signature_recovers_signer"},
        ),
        (
            forged_signature_with_attacker_key(honest, DEMO_ATTACKER_KEY),
            {"signature_recovers_signer"},
        ),
        (role_substitution(honest), {"identity_role_match"}),
        (receipt_status_overclaim(honest), {"receipt_consistency"}),
    ]

    for execution, failed_checks in cases:
        result = detect_tampering(execution)
        assert result.status == "tampered"
        assert failed_checks.issubset(set(result.failed_check_names))


def test_harness_metadata_matches_detector_results() -> None:
    artifact = run_side_by_side()

    assert artifact["honest"]["detection"]["status"] == "clean"
    assert artifact["summary"]["attack_count"] == len(ATTACKS)
    assert artifact["summary"]["all_attacks_caught"] is True
    for scenario in artifact["attacks"]:
        expected = scenario["attack"]["expected_failed_checks"]
        observed = scenario["detection"]["failed_check_names"]
        assert set(expected).issubset(set(observed))
