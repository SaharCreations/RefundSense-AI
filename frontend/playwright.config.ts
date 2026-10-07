import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: process.env.REFUNDGUARD_BROWSER_REPORT || "../reports/frontend_latest/browser-results.json" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:3008",
    headless: true,
    launchOptions: process.env.REFUNDGUARD_TEST_BROWSER
      ? {
          executablePath: process.env.REFUNDGUARD_TEST_BROWSER,
          args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        }
      : {},
  },
  webServer: [
    {
      command: "node tests/mock-api.mjs",
      url: "http://127.0.0.1:8108/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 3008",
      url: "http://127.0.0.1:3008",
      env: {
        NEXT_TELEMETRY_DISABLED: "1",
        REFUNDGUARD_API_URL: "http://127.0.0.1:8108",
      },
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
