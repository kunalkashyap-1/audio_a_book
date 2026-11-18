import type { NextConfig } from "next";

const apiUrl = process.env.AAB_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The contracts package ships TypeScript source with type-only imports from the web app.
  transpilePackages: ["@aab/contracts"],
  // Keep browser calls same-origin so cookies (auth refresh) and media tokens behave in dev.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      { source: "/media/:path*", destination: `${apiUrl}/media/:path*` },
    ];
  },
};

export default nextConfig;
