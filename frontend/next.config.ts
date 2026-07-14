import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow hot reloading when accessing via LAN
  allowedDevOrigins: ['172.16.0.2']
};

export default nextConfig;
