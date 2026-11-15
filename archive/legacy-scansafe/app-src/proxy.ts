import { NextResponse, type NextRequest } from "next/server";
import { DESKTOP_PATHS, pickView } from "@/lib/view";

// Computers get the black desktop site (app/desktop/*) at the same public URLs; phones keep the existing
// pages. `?view=phone` or `?view=desktop` switches and is remembered for 30 days in the ss_view cookie.
export function proxy(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const query = req.nextUrl.searchParams.get("view");
  const view = pickView({
    ua: req.headers.get("user-agent"),
    query,
    cookie: req.cookies.get("ss_view")?.value ?? null,
  });

  const desktopPath = DESKTOP_PATHS[path];
  const res = view === "desktop" && desktopPath
    ? NextResponse.rewrite(new URL(desktopPath + req.nextUrl.search, req.url))
    : NextResponse.next();

  if (query === "desktop" || query === "phone") {
    res.cookies.set("ss_view", query, { maxAge: 60 * 60 * 24 * 30, path: "/", sameSite: "lax" });
  }
  res.headers.set("Vary", "User-Agent, Cookie");
  return res;
}

export const config = {
  matcher: ["/", "/map", "/dashboard", "/about"],
};
