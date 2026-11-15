# Factory web workspace

Run `npm ci` then `npm run dev`. The server-only `FACTORY_API_URL` points to the Python backend (default `http://127.0.0.1:8000`). All browser calls use the same-origin `/api/factory/*` proxy. No demo results replace failed calls.

The single workspace supports template builds, JSON trial runs, public releases, pinned installs, bundle download and improvement proposals/revisions. Publishing requires confirmation. Private workspace ownership uses an HttpOnly cookie, not localStorage.

Checks: `npm run typecheck` and `npm run build`.
