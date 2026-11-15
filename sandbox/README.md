# Reusable browser worker

This retains the existing Playwright/Docker scanner for the factory's QR capability. Deploy it on a separate worker host with no model/payment credentials. Build `scansafe-sandbox` from this directory, set `SANDBOX_TOKEN` and start `uvicorn server:app --host 0.0.0.0 --port 8080` from this directory.

Active routes: `/health`, token-protected `/run`, and `/run/stream`. The former `/operate/stream` route is not registered. Parking helpers remain source dependencies of the existing browser runner but are not exposed by the service.

The factory backend needs `SANDBOX_URL` pointing at this host and the same `SANDBOX_TOKEN`. Keep host-level network egress restrictions: request validation alone does not eliminate DNS rebinding. The original firewall and Chromium isolation instructions are preserved in [the archived worker guide](../archive/legacy-scansafe/sandbox-README.md). Its operator/payment instructions are retired. Chromium's internal sandbox configuration and external firewall protections still require explicit deployment verification.
