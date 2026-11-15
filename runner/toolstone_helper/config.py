"""Local files in ~/.toolstone/ (or $TOOLSTONE_HOME): pairing, profile, keys.

All files are written 0600 and the folder 0700. Nothing here ever prints a value.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_API = "https://api.scansafe.nyc"

PROFILE_KEYS = [
    "name", "first_name", "last_name", "email", "phone", "street_address", "city", "state",
    "zip", "license_plate", "vehicle_make", "vehicle_model", "vehicle_color",
]

# Placeholder demo values (fictional: 555-01xx numbers, example.com). The "_" keys mark them as
# demo data; the helper never fills "_" keys into forms.
PROFILE_TEMPLATE: Dict[str, object] = {
    "_note": "PLACEHOLDER DEMO VALUES. Replace each value with your own info. "
             "This file stays on this computer (chmod 600) and is never sent anywhere.",
    "_demo": True,
    "name": "Alex Demo",
    "first_name": "Alex",
    "last_name": "Demo",
    "email": "alex.demo@example.com",
    "phone": "+14045550123",
    "street_address": "123 Demo Street",
    "city": "Atlanta",
    "state": "GA",
    "zip": "30303",
    "license_plate": "DEMO123",
    "vehicle_make": "Toyota",
    "vehicle_model": "Corolla",
    "vehicle_color": "Blue",
}

ENV_TEMPLATE = """\
# Toolstone helper keys. This file stays on this computer (chmod 600); keys are never sent
# to the relay, never shown in results, logs or video frames.
#
# Vercel: create a token at https://vercel.com/account/tokens, then uncomment and fill in:
# VERCEL_TOKEN=
# VERCEL_TEAM_ID=
"""

# Supported connections: name -> the key that must be present in .env
CONNECTION_KEYS = {"vercel": "VERCEL_TOKEN"}


def home() -> Path:
    raw = os.environ.get("TOOLSTONE_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".toolstone"


def api_base(saved: Optional[str] = None) -> str:
    raw = os.environ.get("TOOLSTONE_API") or saved or DEFAULT_API
    return raw.rstrip("/")


def runner_path() -> Path:
    return home() / "runner.json"


def profile_path() -> Path:
    return home() / "profile.json"


def env_path() -> Path:
    return home() / ".env"


def ensure_home() -> Path:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(h, 0o700)
    except OSError:
        pass
    return h


def write_private(path: Path, text: str) -> None:
    """Write a file readable only by this user (0600), atomically."""
    ensure_home()
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def _tighten(path: Path) -> None:
    """Our private files should never be group/world readable; fix it quietly if they are."""
    try:
        if path.stat().st_mode & 0o077:
            os.chmod(path, 0o600)
    except OSError:
        pass


# --- pairing -------------------------------------------------------------------------------

def load_runner() -> Optional[dict]:
    p = runner_path()
    if not p.exists():
        return None
    _tighten(p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("runner_token"):
        return None
    return data


def save_runner(runner_token: str, runner_id: str, name: str, api: str) -> Path:
    data = {"runner_token": runner_token, "runner_id": runner_id, "name": name, "api": api,
            "paired_at": int(time.time())}
    write_private(runner_path(), json.dumps(data, indent=2) + "\n")
    return runner_path()


# --- profile --------------------------------------------------------------------------------

def ensure_profile() -> bool:
    """Create profile.json from the template if missing. True if it was created."""
    p = profile_path()
    if p.exists():
        _tighten(p)
        return False
    write_private(p, json.dumps(PROFILE_TEMPLATE, indent=2) + "\n")
    return True


def ensure_env() -> bool:
    """Create .env with commented key lines if missing. True if it was created."""
    p = env_path()
    if p.exists():
        _tighten(p)
        return False
    write_private(p, ENV_TEMPLATE)
    return True


def load_profile() -> Optional[Dict[str, str]]:
    """The fillable profile: string values only, "_" keys dropped, names derived both ways."""
    p = profile_path()
    if not p.exists():
        return None
    _tighten(p)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    prof: Dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if isinstance(v, str) and v.strip():
            prof[k] = v.strip()
    if "name" not in prof and (prof.get("first_name") or prof.get("last_name")):
        prof["name"] = " ".join(x for x in (prof.get("first_name"), prof.get("last_name")) if x)
    if prof.get("name") and "first_name" not in prof and "last_name" not in prof:
        parts = prof["name"].split()
        if len(parts) >= 2:
            prof["first_name"], prof["last_name"] = parts[0], " ".join(parts[1:])
    return prof


def profile_is_demo() -> bool:
    try:
        raw = json.loads(profile_path().read_text(encoding="utf-8"))
        return bool(isinstance(raw, dict) and raw.get("_demo"))
    except (OSError, ValueError):
        return False


# --- keys (.env) ----------------------------------------------------------------------------

_ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def parse_env(text: str) -> Dict[str, str]:
    """Simple KEY=VALUE parser: blank lines and # comments ignored, optional `export `,
    optional matching quotes, ` # comment` after an unquoted value dropped."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        else:
            hash_at = val.find(" #")
            if hash_at >= 0:
                val = val[:hash_at].rstrip()
        out[key] = val
    return out


def load_env() -> Dict[str, str]:
    p = env_path()
    if not p.exists():
        return {}
    _tighten(p)
    try:
        return parse_env(p.read_text(encoding="utf-8"))
    except OSError:
        return {}


def connections(env: Optional[Dict[str, str]] = None) -> List[str]:
    """Names (never values) of supported connections whose key is set."""
    env = load_env() if env is None else env
    return [name for name, key in CONNECTION_KEYS.items() if (env.get(key) or "").strip()]


def secret_values(env: Optional[Dict[str, str]] = None, runner: Optional[dict] = None) -> List[str]:
    """Every secret the helper holds, for scrubbing error text before it leaves the process."""
    env = load_env() if env is None else env
    vals = [v for v in env.values() if v and len(v) >= 4]
    if runner and runner.get("runner_token"):
        vals.append(str(runner["runner_token"]))
    return vals


def redact(text: str, secrets: List[str]) -> str:
    text = str(text)
    for s in sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True):
        text = text.replace(s, "[redacted]")
    text = re.sub(r"(?i)\b(Bearer|Runner)\s+[A-Za-z0-9._~+/=-]{8,}", r"\1 [redacted]", text)
    return text
