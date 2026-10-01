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

export const usd = (n: number, digits = 2) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: digits }).format(n);
