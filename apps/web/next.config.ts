import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev overlay badge sits on top of the sidebar's account menu, which
  // makes design review of that corner impossible. It has no effect on builds.
  devIndicators: false,
  /* config options here */
};

export default nextConfig;
