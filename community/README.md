# Chert community plugins (dashboard clone)

A look-alike of the Chert developer console where only **Community plugins** works. Every other
sidebar item is a static page. Built for EmoryHacks 2026 with Chert's permission; it is not the
official Chert console and shows demo data only ("ScanSafe demo", a 555 line, no real people).

Plugins come from the ScanSafe API (`api/routes_plugins.py`), which reads this repo's `plugins/`
folder. All plugin text is rendered as plain React text (no `dangerouslySetInnerHTML`).

## Run

```bash
cd community
npm install
cp .env.example .env.local   # optional: point at a local API
npm run dev                  # http://localhost:3000/plugins
npm run build                # production build check
```

Use `localhost:3000` against the real API: it is on the API's CORS list, so enable/disable work.
Other origins can read plugins but get `403 origin_not_allowed` on enable/disable.

## Environment

| Variable | Default | What it does |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://api.scansafe.nyc` | Base URL of the plugins API (no trailing slash). |
| `NEXT_PUBLIC_CODER_URL` | `https://coder.com` | Where "Open in Coder" goes. |

Both are read at build time (`NEXT_PUBLIC_*`), so redeploy after changing them.

## API it uses

- `GET /plugins` (list, skipped folders, enabled ids), `GET /plugins/{id}` (detail with README),
  `GET /plugins/search?q=` (Typesense, substring fallback)
- `POST /plugins/{id}/enable` and `/disable`. Enabling an unverified plugin returns
  `403 needs_verification`; the UI shows those plugins as "Needs verification" and rolls back any
  optimistic toggle on error.

## Deploy (Vercel)

1. New Vercel project from this repo, **Root Directory = `community`**, framework Next.js.
2. Set `NEXT_PUBLIC_API_URL` (and optionally `NEXT_PUBLIC_CODER_URL`).
3. Deploy, then add the `*.vercel.app` URL to `CORS_EXTRA_ORIGINS` on the API server and restart
   `scansafe-api`, or enable/disable will be refused.
