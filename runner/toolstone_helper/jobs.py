"""The job dispatcher: only the fixed job kinds run; everything else is refused.

Each job posts progress notes (and frames when relevant) and exactly one result. Nothing here
raises out to the run loop.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from . import config
from .forms import FormRunner, JobError
from .vercel import VercelClient, VercelError

KINDS = ("form_fill", "form_submit", "vercel_status", "vercel_redeploy", "connections_list")


class Context:
    """State shared across jobs: the browser/pages, plus test hooks."""

    def __init__(self, forms: Optional[FormRunner] = None, vercel_transport: Any = None):
        self.forms = forms if forms is not None else FormRunner()
        self.vercel_transport = vercel_transport

    def close(self) -> None:
        self.forms.close()


def _vercel(ctx: Context) -> VercelClient:
    env = config.load_env()
    token = (env.get("VERCEL_TOKEN") or "").strip()
    if not token:
        raise JobError("missing_connection:vercel")
    return VercelClient(token, (env.get("VERCEL_TEAM_ID") or "").strip() or None,
                        transport=ctx.vercel_transport)


def _form_fill(job_id: str, args: dict, reporter: Any, ctx: Context) -> dict:
    if str(args.get("profile") or "default") != "default":
        raise JobError("unknown_profile")
    profile = config.load_profile()
    if not profile:
        raise JobError("missing_profile: run `python3 runner/toolstone_runner.py profile`")
    return ctx.forms.fill(job_id, args, profile, reporter)


def _form_submit(job_id: str, args: dict, reporter: Any, ctx: Context) -> dict:
    return ctx.forms.submit(args, reporter)


def _vercel_status(job_id: str, args: dict, reporter: Any, ctx: Context) -> dict:
    client = _vercel(ctx)
    try:
        reporter.progress("Checking your Vercel projects")
        return client.status(str(args.get("project") or ""))
    finally:
        client.close()


def _vercel_redeploy(job_id: str, args: dict, reporter: Any, ctx: Context) -> dict:
    project = str(args.get("project") or "").strip()
    if not project:
        raise JobError("project_required")
    client = _vercel(ctx)
    try:
        reporter.progress(f"Redeploying {project[:60]} to production")
        return client.redeploy(project)
    finally:
        client.close()


def _connections_list(job_id: str, args: dict, reporter: Any, ctx: Context) -> dict:
    return {"connections": config.connections()}


HANDLERS: Dict[str, Callable[[str, dict, Any, Context], dict]] = {
    "form_fill": _form_fill,
    "form_submit": _form_submit,
    "vercel_status": _vercel_status,
    "vercel_redeploy": _vercel_redeploy,
    "connections_list": _connections_list,
}
assert set(HANDLERS) == set(KINDS)


def dispatch(job: dict, reporter: Any, ctx: Context) -> Tuple[str, str]:
    """Run one job; returns (status, error). Posts exactly one result via the reporter."""
    job_id = str(job.get("job_id") or "")
    kind = job.get("kind")
    args = job.get("args")
    if not isinstance(kind, str) or kind not in HANDLERS:
        reporter.result("failed", {}, "unknown_kind")
        return "failed", "unknown_kind"
    if args is None:
        args = {}
    if not isinstance(args, dict):
        reporter.result("failed", {}, "bad_args")
        return "failed", "bad_args"
    try:
        result = HANDLERS[kind](job_id, args, reporter, ctx)
    except (JobError, VercelError) as e:
        error = e.code
    except KeyboardInterrupt:
        reporter.result("failed", {}, "runner_stopped")
        raise
    except Exception as e:  # never let a job crash the loop; no message (could hold page data)
        error = f"internal_error:{type(e).__name__}"
    else:
        reporter.result("done", result)
        return "done", ""
    reporter.result("failed", {}, error)
    return "failed", error
