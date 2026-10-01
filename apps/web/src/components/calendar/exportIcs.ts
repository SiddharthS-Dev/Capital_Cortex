import { ApiError, type Problem } from "@/lib/api";
import { currentUser, login } from "@/lib/auth";
import { config } from "@/lib/config";

/** Authenticated download of the iCal feed (demo data excluded). */
export async function exportIcs(days = 365): Promise<void> {
  const user = await currentUser();
  if (!user) {
    await login();
    return;
  }
  const res = await fetch(`${config.apiBase}/v1/calendar/export.ics?include_demo=false&days=${days}`, {
    headers: { Authorization: `Bearer ${user.access_token}`, Accept: "text/calendar" },
  });
  if (!res.ok) {
    let problem: Problem;
    try {
      problem = (await res.json()) as Problem;
    } catch {
      problem = { type: "about:blank", title: res.statusText || "Export failed", status: res.status };
    }
    problem.trace_id ??= res.headers.get("X-Trace-Id") ?? undefined;
    throw new ApiError(problem);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "capital-cortex.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
