"""api.scansafe.nyc/r/<id>: the page linked from the follow-up text."""
import time

from fastapi.testclient import TestClient

from api import main as api_main, result_store
from api.schema import ScanResult

client = TestClient(api_main.app)


def _save(monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path)
    base = dict(scan_id="abc123def456", url="https://cafe.example/menu", final_url="https://cafe.example/menu",
                domain="cafe.example", verdict="safe", jev_score=0.05, explanation="Ordinary cafe menu.",
                scanned_at=int(time.time()))
    r = ScanResult(**{**base, **kw})
    result_store.save(r)
    return r


def test_safe_page_links_to_the_real_site(monkeypatch, tmp_path):
    _save(monkeypatch, tmp_path)
    r = client.get("/r/abc123def456")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "Looks safe" in r.text and 'href="https://cafe.example/menu"' in r.text and "Continue to cafe.example" in r.text
    assert "script-src" not in r.headers["content-security-policy"] and "default-src 'none'" in r.headers["content-security-policy"]
    assert "<script" not in r.text


def test_scam_page_never_links_to_the_site_and_offers_reporting(monkeypatch, tmp_path):
    _save(monkeypatch, tmp_path, verdict="malicious", scam_type="fake_parking_or_toll", jev_score=0.97,
          url="https://pay-meter.example/x", final_url="https://pay-meter.example/x", domain="pay-meter.example",
          explanation='Asks for card details <script>alert(1)</script> "now"')
    r = client.get("/r/abc123def456")
    assert r.status_code == 200 and "Likely a scam" in r.text and "Fake parking or toll payment" in r.text
    assert 'href="https://pay-meter.example' not in r.text
    assert "https://reportfraud.ftc.gov/" in r.text and "https://www.ic3.gov/" in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_no_continue_link_for_non_web_codes(monkeypatch, tmp_path):
    _save(monkeypatch, tmp_path, url="javascript:alert(1)", final_url=None, domain=None)
    r = client.get("/r/abc123def456")
    assert r.status_code == 200 and "javascript:" not in r.text and "Continue to" not in r.text


def test_unknown_or_bad_id_is_a_friendly_404(monkeypatch, tmp_path):
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path)
    r = client.get("/r/nope00000000")
    assert r.status_code == 404 and "couldn't find this check" in r.text
    assert client.get("/r/..%2F..%2Fetc").status_code == 404      # never reaches a file
