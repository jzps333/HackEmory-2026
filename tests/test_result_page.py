import json
from pathlib import Path

from fastapi.testclient import TestClient

from api import main as api_main, result_store
from api.schema import ScanResult

SHARED = Path(__file__).resolve().parent.parent / "shared"


def _result(**kw) -> ScanResult:
    data = json.loads((SHARED / "mock_malicious.json").read_text())
    data.update(kw)
    return ScanResult(**data)


def test_saved_result_is_served_and_unknown_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path)
    r = _result(scan_id="abc123def456")
    result_store.save(r)
    client = TestClient(api_main.app)
    got = client.get("/result/abc123def456")
    assert got.status_code == 200 and got.json()["verdict"] == r.verdict
    assert client.get("/result/ffffffffffff").status_code == 404
    assert client.get("/result/../../etc").status_code == 404     # ids are hex only
    assert result_store.get("not-hex!") is None


def test_expired_result_is_gone(tmp_path, monkeypatch):
    import os, time
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path)
    result_store.save(_result(scan_id="0123456789ab"))
    p = tmp_path / "0123456789ab.json"
    old = time.time() - result_store.TTL_S - 10
    os.utime(p, (old, old))
    assert result_store.get("0123456789ab") is None and not p.exists()
