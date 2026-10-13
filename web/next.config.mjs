// The browser only ever calls /api/*; Next proxies it to the Python query API (`make api`).
const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // A package-lock.json above the repo would otherwise be taken as the workspace root.
  turbopack: { root: import.meta.dirname },
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
