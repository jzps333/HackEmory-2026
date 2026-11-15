"""Community plugins for Chert: the plugins/ folder of this repo.

Each plugin is plugins/<id>/plugin.yaml + README.md. A plugin is DATA: plain-text instructions for
the agent plus a list of tools from a fixed allowlist. Nothing in a plugin is ever executed; tools
are wired by name from our own code (chert/plugins.py).

Verified = plugins/verified.json[id].sha256 equals content_hash(folder), which only admins can
change (.github/CODEOWNERS). Edit a verified plugin and it is unverified again until re-approved.
Unverified plugins never get the money tools (solana_pay, parking).

CLI:  python -m api.plugins_index --check        exit 1 if any plugin is invalid
      python -m api.plugins_index --hash <id>    print the hash to put in verified.json
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR") or Path(__file__).resolve().parent.parent / "plugins")
TOOLS = frozenset({"camera", "speak", "screen", "memory", "safe_browser", "scam_check",
                   "plugin_search", "solana_pay", "parking"})
MONEY_TOOLS = frozenset({"solana_pay", "parking"})
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
KINDS = ("live",)
RUNS_ON = ("server", "vm")
LIMITS = {"name": 60, "summary": 200, "author": 40, "permissions": 300, "instructions": 2000}
MAX_PHRASES = 8
MAX_FILE_BYTES = 64 * 1024


@dataclass
class Plugin:
    id: str
    name: str
    summary: str
    author: str
    version: int
    kind: str
    runs_on: str
    phrases: list[str] = field(default_factory=list)
    qr: bool = False
    tools: list[str] = field(default_factory=list)
    permissions: str = ""
    instructions: str = ""
    readme: str = ""
    sha256: str = ""
    verified: bool = False


def content_hash(folder: Path) -> str:
    """sha256 of plugin.yaml bytes + b"\\n" + README.md bytes (README may be missing)."""
    y = (folder / "plugin.yaml").read_bytes()
    r = (folder / "README.md").read_bytes() if (folder / "README.md").is_file() else b""
    return hashlib.sha256(y + b"\n" + r).hexdigest()


def _text(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate(data: Any, folder_name: str) -> list[str]:
    """Errors for one parsed plugin.yaml; [] when valid."""
    if not isinstance(data, dict):
        return ["plugin.yaml must be a mapping"]
    errs = []
    pid = data.get("id")
    if not isinstance(pid, str) or not ID_RE.fullmatch(pid):
        errs.append("id must be 2-40 chars of a-z, 0-9 and -")
    elif pid != folder_name:
        errs.append(f"id '{pid}' must match its folder name '{folder_name}'")
    for key, cap in LIMITS.items():
        v = data.get(key)
        if not _text(v):
            errs.append(f"{key} is required")
        elif len(v) > cap:
            errs.append(f"{key} is longer than {cap} characters")
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool) or data["version"] < 1:
        errs.append("version must be a whole number >= 1")
    if data.get("kind") not in KINDS:
        errs.append(f"kind must be one of {', '.join(KINDS)}")
    if data.get("runs_on") not in RUNS_ON:
        errs.append(f"runs_on must be one of {', '.join(RUNS_ON)}")
    trig = data.get("triggers", {}) or {}
    if not isinstance(trig, dict):
        errs.append("triggers must be a mapping")
    else:
        ph = trig.get("phrases", []) or []
        if not isinstance(ph, list) or not all(_text(p) and len(p) <= 60 for p in ph) or len(ph) > MAX_PHRASES:
            errs.append(f"triggers.phrases must be up to {MAX_PHRASES} short phrases")
        if not isinstance(trig.get("qr", False), bool):
            errs.append("triggers.qr must be true or false")
    tools = data.get("tools")
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) for t in tools):
        errs.append("tools must be a non-empty list")
    else:
        bad = sorted(set(tools) - TOOLS)
        if bad:
            errs.append(f"unknown tools: {', '.join(bad)} (allowed: {', '.join(sorted(TOOLS))})")
        if len(set(tools)) != len(tools):
            errs.append("tools must not repeat")
    return errs


def _verified_map(root: Path) -> dict:
    try:
        data = json.loads((root / "verified.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_plugins(root: Path | None = None) -> tuple[list[Plugin], dict[str, str]]:
    """(valid plugins sorted by id, {folder: why it was skipped})."""
    root = Path(root or PLUGINS_DIR)
    verified = _verified_map(root)
    plugins, skipped = [], {}
    if not root.is_dir():
        return plugins, skipped
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        y = d / "plugin.yaml"
        try:
            if not y.is_file():
                raise ValueError("no plugin.yaml")
            if y.stat().st_size > MAX_FILE_BYTES or ((d / "README.md").is_file()
                                                      and (d / "README.md").stat().st_size > MAX_FILE_BYTES):
                raise ValueError("plugin files are too large")
            data = yaml.safe_load(y.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError) as e:
            skipped[d.name] = f"couldn't read plugin.yaml: {str(e).splitlines()[0][:160]}"
            continue
        errs = validate(data, d.name)
        if errs:
            skipped[d.name] = "; ".join(errs)
            continue
        trig = data.get("triggers") or {}
        digest = content_hash(d)
        entry = verified.get(d.name)
        plugins.append(Plugin(
            id=data["id"], name=data["name"].strip(), summary=data["summary"].strip(),
            author=data["author"].strip(), version=data["version"], kind=data["kind"],
            runs_on=data["runs_on"], phrases=[p.strip() for p in trig.get("phrases") or []],
            qr=bool(trig.get("qr", False)), tools=list(data["tools"]),
            permissions=data["permissions"].strip(), instructions=data["instructions"].strip(),
            readme=(d / "README.md").read_text(encoding="utf-8") if (d / "README.md").is_file() else "",
            sha256=digest,
            verified=isinstance(entry, dict) and entry.get("sha256") == digest))
    return plugins, skipped


def effective_tools(p: Plugin) -> list[str]:
    """The tools this plugin really gets: money tools only once verified."""
    return [t for t in p.tools if p.verified or t not in MONEY_TOOLS]


def to_public(p: Plugin, installs: int = 0) -> dict:
    out = asdict(p)
    out["effective_tools"] = effective_tools(p)
    out["installs"] = int(installs)
    return out


def _main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        plugins, skipped = load_plugins()
        for p in plugins:
            print(f"ok   {p.id}{'  (verified)' if p.verified else '  (unverified)'}")
        for folder, why in skipped.items():
            print(f"FAIL {folder}: {why}")
        return 1 if skipped else 0
    if argv[:1] == ["--hash"] and len(argv) == 2 and ID_RE.fullmatch(argv[1]):
        print(content_hash(PLUGINS_DIR / argv[1]))
        return 0
    print(__doc__.split("CLI:")[1].strip())
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
