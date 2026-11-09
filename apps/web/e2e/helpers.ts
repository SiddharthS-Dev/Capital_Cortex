import { createHmac } from "node:crypto";
import type { Page } from "@playwright/test";

/** Credentials come from the environment, never from this file (SEC-1): the dev user password and smoke-auditor's
 * TOTP seed. Read lazily, so importing helpers needs neither; a test that logs in fails with the missing name. */
function requiredEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`e2e: set ${name} in the environment (no credential is committed in the e2e helpers)`);
  return v;
}
export const devPassword = (): string => requiredEnv("SMOKE_USER_PASSWORD");
export const smokeTotpSecret = (): string => requiredEnv("SMOKE_TOTP_SECRET");

export function totp(secret: string, now = Date.now(), stepS = 30, digits = 6): string {
  const counter = Math.floor(now / 1000 / stepS);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const mac = createHmac("sha1", Buffer.from(secret, "utf8")).update(buf).digest();
  const o = mac[mac.length - 1] & 0x0f;
  const code = (mac.readUInt32BE(o) & 0x7fffffff) % 10 ** digits;
  return String(code).padStart(digits, "0");
}

/** Real Keycloak login through the browser: password, then TOTP when the user has it. */
export async function login(page: Page, username: string, otpSecret?: string, password?: string) {
  await page.goto("/");
  await page.waitForURL(/\/realms\/cortex\/protocol\/openid-connect\/auth|login-actions/);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password ?? devPassword());
  // Login is complete when the app has exchanged the code for a token and made its first authenticated call
  // (GET /v1/me → 200), not merely when the URL is back on the app: otherwise the token exchange and session
  // bootstrap count against the next assertion's timeout. Registered before submitting, so it can't be missed.
  const authenticated = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/v1/me" && r.request().method() === "GET" && r.status() === 200,
    { timeout: 30_000 },
  );
  await page.locator("#kc-login").click();
  if (otpSecret) {
    await page.locator("#otp").fill(totp(otpSecret));
    await page.locator("#kc-login").click();
  }
  const app = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3300");
  await page.waitForURL((u) => u.host === app.host && !u.pathname.startsWith("/auth/callback"), { timeout: 20_000 });
  await authenticated;
}
