import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** "*" = all; "res:*" = every action on res; otherwise an exact match (mirrors platform_core RBAC). */
export function hasPermission(granted: readonly string[] | undefined, wanted: string): boolean {
  if (!granted) return false;
  const [res] = wanted.split(":");
  return granted.some((g) => g === "*" || g === wanted || (g.endsWith(":*") && g.slice(0, -2) === res));
}

/** An absolute http(s) URL from ingested or API data, else undefined: never render `javascript:`, `data:` or relative
 *  links that came from outside the app (defence in depth behind the CSP). */
export function safeHttpUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  try {
    const u = new URL(value.trim());
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : undefined;
  } catch {
    return undefined;
  }
}

export const usd = (n: number, digits = 2) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: digits }).format(n);
