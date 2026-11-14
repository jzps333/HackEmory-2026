import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The city showcase source is shared from the repo-level websites/ directory.
  turbopack: { root: path.join(__dirname, "..") },
};

export default nextConfig;
