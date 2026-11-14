"""Tests for the parts that don't need network: Jev parsing, the verdict rule, Solana Pay."""
from api.jev import build_payload, parse_answers
from api.scan import decide, mock_result, parse_solana_pay, payment_result
from api.schema import JevChecks


def jev_response(imp="fake_parking_or_toll", verdict_probs=None, pw=0.1, pay=0.95, inj=0.0):
    verdict_probs = verdict_probs or {"safe": 0.03, "suspicious": 0.06, "malicious": 0.91}
    return {"answers": {
        "impersonates": {"type": "choice", "choice": imp, "probabilities": {imp: 0.9}},
        "asks_password": {"type": "noul", "noul": pw},
        "asks_payment": {"type": "noul", "noul": pay},
        "prompt_injection": {"type": "noul", "noul": inj},
        "verdict": {"type": "choice", "choice": max(verdict_probs, key=verdict_probs.get),
                    "probabilities": verdict_probs},
    }}


def test_payload_has_all_questions():
    p = build_payload({"url": "https://x.test", "page_text": "a" * 10000})
    assert set(p["questions"]) == {"impersonates", "asks_password", "asks_payment",
                                   "prompt_injection", "verdict"}
    assert len(p["state"]["page_text"]) == 4000


def test_parse_scam():
    checks = parse_answers(jev_response())
    assert checks.impersonates == "fake_parking_or_toll"
    assert checks.malicious_p == 0.94          # 0.91 + half of 0.06


def test_decide_blocks_high_score():
    verdict, score, scam_type = decide(JevChecks(impersonates="fake_bank", malicious_p=0.9))
    assert (verdict, scam_type) == ("malicious", "fake_bank")


def test_decide_safe():
    assert decide(JevChecks(malicious_p=0.1))[0] == "safe"


def test_decide_middle_is_suspicious():
    assert decide(JevChecks(malicious_p=0.6))[0] == "suspicious"


def test_prompt_injection_is_malicious():
    verdict, score, _ = decide(JevChecks(malicious_p=0.1, prompt_injection_p=0.8))
    assert verdict == "malicious" and score >= 0.9


def test_download_is_malicious():
    verdict, _, scam_type = decide(JevChecks(malicious_p=0.1), tried_download=True)
    assert (verdict, scam_type) == ("malicious", "malware_download")


def test_solana_pay_verified():
    qr = ("solana:6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL?amount=0.02"
          "&label=Peachtree%20Parking%20Co.&message=Meter%2042")
    pay = parse_solana_pay(qr)
    assert pay and pay.amount_sol == 0.02 and pay.merchant_verified
    assert payment_result(qr, pay).verdict == "safe"


def test_solana_pay_wrong_wallet_blocked():
    qr = "solana:So11111111111111111111111111111111111111112?amount=5&label=Peachtree%20Parking%20Co."
    pay = parse_solana_pay(qr)
    assert pay and not pay.merchant_verified
    assert payment_result(qr, pay).verdict == "malicious"


def test_not_solana():
    assert parse_solana_pay("https://example.com") is None


def test_mock_mode_returns_valid_result():
    r = mock_result("https://bit.ly/whatever")
    assert r.verdict == "malicious" and r.url == "https://bit.ly/whatever"
