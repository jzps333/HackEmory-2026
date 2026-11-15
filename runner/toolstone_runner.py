#!/usr/bin/env python3
"""Toolstone helper app: lets your FaceTime agent fill forms and check Vercel on THIS computer.

    python3 runner/toolstone_runner.py pair      # link this computer to your phone number
    python3 runner/toolstone_runner.py profile   # create ~/.toolstone/profile.json and .env
    python3 runner/toolstone_runner.py run       # wait for jobs (Ctrl-C to stop)
    python3 runner/toolstone_runner.py status    # paired? which connections?

Env: TOOLSTONE_API (default https://api.scansafe.nyc), TOOLSTONE_HOME (default ~/.toolstone),
TOOLSTONE_HEADLESS=1 (no visible browser window; for tests).
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toolstone_helper import config  # noqa: E402


def default_name() -> str:
    host = socket.gethostname() or "My computer"
    if host.endswith(".local"):
        host = host[: -len(".local")]
    return host[:60]


def cmd_pair(args: argparse.Namespace) -> int:
    from toolstone_helper.pairing import normalize_phone, pair_flow
    from toolstone_helper.relay import Relay

    raw = args.phone
    if not raw:
        try:
            raw = input("Your phone number (US numbers can skip the +1): ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 1
    phone = normalize_phone(raw)
    if not phone:
        print("That doesn't look like a phone number. Try e.g. 404 555 0123 or +44 20 7946 0958.")
        return 1
    name = (args.name or default_name()).strip()[:60] or "My computer"
    config.ensure_home()
    relay = Relay(config.api_base())
    try:
        return pair_flow(relay, phone, name)
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was paired.")
        return 1
    finally:
        relay.close()


def cmd_profile(args: argparse.Namespace) -> int:
    made_profile = config.ensure_profile()
    made_env = config.ensure_env()
    p, e = config.profile_path(), config.env_path()
    print(f"Profile: {p}" + (" (created with placeholder demo values: edit them)" if made_profile
                             else " (already exists)"))
    print(f"Keys:    {e}" + (" (created; uncomment VERCEL_TOKEN= to connect Vercel)" if made_env
                             else " (already exists)"))
    print("Both files are readable only by you and never leave this computer.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    runner = config.load_runner()
    if not runner:
        print("This computer isn't paired yet. Run: python3 runner/toolstone_runner.py pair")
        return 1
    from toolstone_helper.jobs import Context
    from toolstone_helper.loop import run_loop
    from toolstone_helper.relay import Relay

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Tip: form filling needs Playwright: python3 -m pip install -r runner/requirements.txt "
              "&& python3 -m playwright install chromium")
    if not config.profile_path().exists():
        print("Tip: no saved info yet. Run `python3 runner/toolstone_runner.py profile` "
              "so form filling has something to use.")
    relay = Relay(config.api_base(runner.get("api")), runner["runner_token"])
    ctx = Context()
    print(f'Toolstone helper running as "{runner.get("name") or "this computer"}".')
    try:
        return run_loop(relay, ctx, secrets_fn=lambda: config.secret_values(None, runner))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        try:
            ctx.close()
        except BaseException:
            pass
        relay.close()


def cmd_status(args: argparse.Namespace) -> int:
    runner = config.load_runner()
    if runner:
        print(f'Paired: yes, as "{runner.get("name") or "this computer"}"')
    else:
        print("Paired: no (run: python3 runner/toolstone_runner.py pair)")
    conns = config.connections()
    print("Connections: " + (", ".join(conns) if conns else
                             f"none (add VERCEL_TOKEN=... to {config.env_path()})"))
    p = config.profile_path()
    if p.exists():
        print(f"Profile: {p}" + (" (placeholder demo values)" if config.profile_is_demo() else ""))
    else:
        print("Profile: none (run: python3 runner/toolstone_runner.py profile)")
    print(f"API: {config.api_base(runner.get('api') if runner else None)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="toolstone_runner.py",
                                 description="Toolstone helper app (runs on your own computer).")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pair", help="link this computer to your phone number")
    p.add_argument("--phone", help="your phone number (asked if omitted)")
    p.add_argument("--name", help="a name for this computer (default: its hostname)")
    sub.add_parser("profile", help="create ~/.toolstone/profile.json and .env if missing")
    sub.add_parser("run", help="wait for jobs and run them (Ctrl-C to stop)")
    sub.add_parser("status", help="show pairing and connections")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return {"pair": cmd_pair, "profile": cmd_profile, "run": cmd_run,
            "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
