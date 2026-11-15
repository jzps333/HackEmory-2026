"""`run`: long-poll the relay for jobs and run them, reconnecting with backoff.

Prints one short line per job (kind + status), never personal data or keys.
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional

from .jobs import KINDS, Context, dispatch
from .relay import AuthError, JobReporter, Relay, RelayError, valid_job_id

MAX_BACKOFF = 60.0


def run_loop(relay: Relay, ctx: Context, secrets_fn: Callable[[], List[str]],
             out: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
             wait: int = 25, max_polls: Optional[int] = None) -> int:
    """Runs until Ctrl-C (KeyboardInterrupt propagates to the caller) or unpairing."""
    backoff = 1.0
    online: Optional[bool] = None
    polls = 0
    while max_polls is None or polls < max_polls:
        polls += 1
        try:
            job = relay.next_job(wait)
        except AuthError:
            out("This computer is no longer paired (another computer may have been paired). "
                "Run: python3 runner/toolstone_runner.py pair")
            return 2
        except RelayError as e:
            if online is not False:
                out(f"Lost connection to Toolstone ({e.message}); retrying...")
            online = False
            sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue
        if online is not True:
            out("Connected. Waiting for jobs (Ctrl-C to stop).")
            online = True
        backoff = 1.0
        ctx.forms.expire()
        if not job:
            continue
        job_id = job.get("job_id")
        if not valid_job_id(job_id):
            out("Skipped a job with an invalid id.")
            continue
        kind = job.get("kind")
        status, error = dispatch(job, JobReporter(relay, job_id, secrets_fn()), ctx)
        shown = kind if kind in KINDS else "unknown kind (refused)"
        line = f"{time.strftime('%H:%M:%S')}  {shown}: {status}"
        if error and kind in KINDS:
            line += f" ({error.split(' ')[0][:60]})"
        out(line)
    return 0
