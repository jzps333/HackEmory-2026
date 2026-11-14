import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The repo root has other projects; keep Turbopack scoped to app/.
  turbopack: { root: path.join(__dirname) },
};

export default nextConfig;
