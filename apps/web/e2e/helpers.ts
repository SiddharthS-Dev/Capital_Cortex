import { createHmac } from "node:crypto";
import type { Page } from "@playwright/test";

export const DEV_PASSWORD = "Cortex!dev-2026";
/** Dev realm only; see infra/keycloak/generate_realm.py. */
export const SMOKE_TOTP_SECRET = "cortex-dev-smoke-totp-secret";

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
export async function login(page: Page, username: string, otpSecret?: string, password = DEV_PASSWORD) {
  await page.goto("/");
  await page.waitForURL(/\/realms\/cortex\/protocol\/openid-connect\/auth|login-actions/);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  if (otpSecret) {
    await page.locator("#otp").fill(totp(otpSecret));
    await page.locator("#kc-login").click();
  }
  const app = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3300");
  await page.waitForURL((u) => u.host === app.host && !u.pathname.startsWith("/auth/callback"), { timeout: 20_000 });
}
