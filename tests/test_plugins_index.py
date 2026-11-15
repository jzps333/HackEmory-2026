"""plugins/: the format, validation, verification and tool gating (api/plugins_index.py)."""
import json
from pathlib import Path

from api import plugins_index as pi

SQUAT = """id: squat-coach
name: Squat coach
summary: Watches your squats on FaceTime and calls out form cues.
author: scansafe-team
version: 1
kind: live
runs_on: server
triggers:
  phrases: ["coach my squats", "squat coach"]
  qr: false
tools: [camera, speak, screen, memory]
permissions: This plugin watches your camera and saves your rep counts.
instructions: Watch the person squat and give one short cue per rep.
"""


def _plugin(root: Path, folder: str, yaml_text: str, readme: str = "# Plugin\n") -> Path:
    d = root / folder
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(yaml_text)
    (d / "README.md").write_text(readme)
    return d


def _verify(root: Path, *ids: str) -> None:
    (root / "verified.json").write_text(json.dumps(
        {i: {"sha256": pi.content_hash(root / i), "by": "jzps333"} for i in ids}))


def test_valid_plugin_loads_with_fields(tmp_path):
    _plugin(tmp_path, "squat-coach", SQUAT)
    plugins, skipped = pi.load_plugins(tmp_path)
    assert skipped == {} and len(plugins) == 1
    p = plugins[0]
    assert p.id == "squat-coach" and p.kind == "live" and p.runs_on == "server"
    assert p.tools == ["camera", "speak", "screen", "memory"] and p.phrases == ["coach my squats", "squat coach"]
    assert p.qr is False and p.verified is False and p.readme == "# Plugin\n"


def test_bad_plugins_are_skipped_with_reasons(tmp_path):
    _plugin(tmp_path, "broken-yaml", "id: [unclosed\n")
    _plugin(tmp_path, "shell-tool", SQUAT.replace("squat-coach", "shell-tool").replace("memory]", "shell]"))
    _plugin(tmp_path, "wrong-folder", SQUAT)                     # id squat-coach != folder
    (tmp_path / "no-yaml").mkdir()
    plugins, skipped = pi.load_plugins(tmp_path)
    assert plugins == []
    assert set(skipped) == {"broken-yaml", "shell-tool", "wrong-folder", "no-yaml"}
    assert "shell" in skipped["shell-tool"]


def test_validate_limits():
    import yaml
    data = yaml.safe_load(SQUAT)
    assert pi.validate(data, "squat-coach") == []
    assert pi.validate({**data, "instructions": "x" * 2001}, "squat-coach")
    assert pi.validate({**data, "runs_on": "laptop"}, "squat-coach")
    assert pi.validate({**data, "id": "Bad_ID"}, "Bad_ID")
    assert pi.validate({**data, "tools": "camera"}, "squat-coach")         # not a list


def test_verified_needs_matching_hash(tmp_path):
    _plugin(tmp_path, "squat-coach", SQUAT)
    _verify(tmp_path, "squat-coach")
    (p,), _ = pi.load_plugins(tmp_path)
    assert p.verified is True and p.sha256 == pi.content_hash(tmp_path / "squat-coach")


def test_edit_after_approval_is_unverified(tmp_path):
    d = _plugin(tmp_path, "squat-coach", SQUAT)
    _verify(tmp_path, "squat-coach")
    (d / "README.md").write_text("# Plugin\nnow also sends texts\n")
    (p,), _ = pi.load_plugins(tmp_path)
    assert p.verified is False


def test_unverified_plugins_lose_money_tools(tmp_path):
    pay = SQUAT.replace("squat-coach", "pay-x").replace("[camera, speak, screen, memory]",
                                                        "[speak, solana_pay, parking]")
    _plugin(tmp_path, "pay-x", pay)
    (p,), _ = pi.load_plugins(tmp_path)
    assert pi.effective_tools(p) == ["speak"]
    _verify(tmp_path, "pay-x")
    (p,), _ = pi.load_plugins(tmp_path)
    assert pi.effective_tools(p) == ["speak", "solana_pay", "parking"]
    pub = pi.to_public(p, installs=3)
    assert pub["verified"] is True and pub["installs"] == 3 and pub["effective_tools"] == pi.effective_tools(p)


def test_repo_plugins_are_all_valid_and_verified():
    plugins, skipped = pi.load_plugins(pi.PLUGINS_DIR)
    assert skipped == {}
    assert {p.id for p in plugins} == {"qr-checker", "safe-browser", "solana-pay", "parking",
                                       "squat-coach", "plugin-finder"}
    assert all(p.verified for p in plugins)
