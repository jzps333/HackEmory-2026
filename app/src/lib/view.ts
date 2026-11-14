// Which version of the site a request gets: the phone site (the existing pages) or the desktop site
// (app/desktop/*). Used by proxy.ts. No imports, so `node --test tests/` can run it directly.

export type View = "desktop" | "phone";

/** Public URL -> the desktop page that serves it. */
export const DESKTOP_PATHS: Record<string, string> = {
  "/": "/desktop",
  "/map": "/desktop/map",
  "/dashboard": "/desktop/stats",
  "/about": "/desktop/about",
};

const MOBILE_UA = /Mobi|Android|iPhone|iPod|iPad|Silk|Kindle|Opera Mini/i;

function asView(value: string | null): View | null {
  return value === "desktop" || value === "phone" ? value : null;
}

/** `?view=` wins, then the saved `ss_view` cookie, then the user agent. Unknown agents get the phone site. */
export function pickView(input: { ua: string | null; query: string | null; cookie: string | null }): View {
  const forced = asView(input.query) ?? asView(input.cookie);
  if (forced) return forced;
  if (!input.ua) return "phone";
  return MOBILE_UA.test(input.ua) ? "phone" : "desktop";
}

/** The public URL for a desktop page (what the browser shows), or the path unchanged. */
export function publicPath(pathname: string): string {
  for (const [pub, desk] of Object.entries(DESKTOP_PATHS)) {
    if (pathname === desk) return pub;
  }
  return pathname;
}
