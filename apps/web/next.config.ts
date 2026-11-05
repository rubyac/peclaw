import type { NextConfig } from "next";
const config: NextConfig = {
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  poweredByHeader: false,
};
export default config;
