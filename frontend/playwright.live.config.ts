import { defineConfig } from "@playwright/test";
if (
  !process.env.REFUNDGUARD_LIVE_FIXTURE ||
  !process.env.REFUNDGUARD_LIVE_ORIGIN
)
  throw Error(
    "Run through scripts/verify_local_stack.py with a disposable test database.",
  );
export default defineConfig({
  testDir: "./tests/live",
  workers: 1,
  retries: 0,
  timeout: 60000,
  reporter: [
    ["list"],
    ["json", { outputFile: process.env.REFUNDGUARD_LIVE_REPORT }],
  ],
  use: {
    baseURL: process.env.REFUNDGUARD_LIVE_ORIGIN,
    headless: true,
    launchOptions: process.env.REFUNDGUARD_TEST_BROWSER
      ? {
          executablePath: process.env.REFUNDGUARD_TEST_BROWSER,
          args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        }
      : {},
  },
});
