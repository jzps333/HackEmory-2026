// Run: cd app && node --test tests/   (Node 22.18+ strips the TypeScript types in view.ts)
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickView, publicPath, DESKTOP_PATHS } from "../src/lib/view.ts";

const UA = {
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
  android: "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
};
const v = (ua, query = null, cookie = null) => pickView({ ua, query, cookie });

test("phones get the phone site", () => {
  assert.equal(v(UA.iphone), "phone");
  assert.equal(v(UA.android), "phone");
});

test("computers get the desktop site", () => {
  assert.equal(v(UA.mac), "desktop");
  assert.equal(v(UA.windows), "desktop");
});

test("unknown or missing user agent falls back to the phone site", () => {
  assert.equal(v(null), "phone");
  assert.equal(v(""), "phone");
});

test("?view= overrides the user agent", () => {
  assert.equal(v(UA.mac, "phone"), "phone");
  assert.equal(v(UA.iphone, "desktop"), "desktop");
});

test("the saved cookie overrides the user agent", () => {
  assert.equal(v(UA.iphone, null, "desktop"), "desktop");
  assert.equal(v(UA.mac, null, "phone"), "phone");
});

test("query beats cookie", () => {
  assert.equal(v(UA.mac, "phone", "desktop"), "phone");
});

test("junk query or cookie values are ignored", () => {
  assert.equal(v(UA.iphone, "tablet", "huge"), "phone");
  assert.equal(v(UA.mac, "", "x"), "desktop");
});

test("public paths map to desktop paths", () => {
  assert.deepEqual(DESKTOP_PATHS, { "/": "/desktop", "/map": "/desktop/map", "/dashboard": "/desktop/stats", "/about": "/desktop/about" });
});

test("publicPath turns desktop paths back into public ones", () => {
  assert.equal(publicPath("/desktop"), "/");
  assert.equal(publicPath("/desktop/map"), "/map");
  assert.equal(publicPath("/desktop/stats"), "/dashboard");
  assert.equal(publicPath("/desktop/about"), "/about");
  assert.equal(publicPath("/map"), "/map");
});
