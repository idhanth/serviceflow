import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev overlay badge sits on top of the sidebar's account menu, which
  // makes design review of that corner impossible. It has no effect on builds.
  devIndicators: false,
  // A self-contained server bundle for the Docker image (apps/web/Dockerfile).
  output: "standalone",
};

export default nextConfig;
