import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export for Tauri desktop builds (set STATIC_EXPORT=true)
  ...(process.env.STATIC_EXPORT === "true"
    ? { output: "export", trailingSlash: true }
    : {}),
  transpilePackages: ["@finance-tracker/ui"],
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts", "framer-motion"],
  },
};

export default nextConfig;
