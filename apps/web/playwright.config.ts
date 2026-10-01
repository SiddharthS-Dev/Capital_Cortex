import { defineConfig } from "@playwright/test";

// E2E against the running Compose stack (`make up`). Override with E2E_BASE_URL.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // One worker: the suites log the same realm users in through the real Keycloak, whose brute-force protection
  // treats two logins of one user within a second as an attack (quick-login check) and locks the user for a
  // minute. The suites also share live state (council run → approval inbox).
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3300",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
});
