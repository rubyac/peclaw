import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: {
    baseURL: process.env.WEB_BASE_URL || "http://localhost:3000",
    launchOptions: { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1100 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
