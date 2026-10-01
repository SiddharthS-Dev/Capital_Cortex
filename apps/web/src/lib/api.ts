import { currentUser, login, stepUp } from "./auth";
import { config } from "./config";

/** RFC-7807 problem details, as returned by every Cortex API error. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  trace_id?: string;
  phase?: number | null;
  step_up?: boolean;
  mfa_required?: boolean;
  permission?: string;
  reasons?: string[];
}

export class ApiError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail ?? problem.title);
  }
  get status() {
    return this.problem.status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = await currentUser();
  if (!user) {
    await login();
    throw new ApiError({ type: "about:blank", title: "Redirecting to sign-in", status: 401 });
  }
  const res = await fetch(`${config.apiBase}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
      Authorization: `Bearer ${user.access_token}`,
    },
  });
  if (res.ok) return (await res.json()) as T;

  let problem: Problem;
  try {
    problem = (await res.json()) as Problem;
  } catch {
    problem = { type: "about:blank", title: res.statusText || "Request failed", status: res.status };
  }
  problem.trace_id ??= res.headers.get("X-Trace-Id") ?? undefined;
  if (res.status === 401) await login();
  if (res.status === 403 && problem.step_up) await stepUp();
  throw new ApiError(problem);
}
