/** POST variant of lib/sse.ts streamSSE: authenticated server-sent events over fetch() with a JSON body.
 * Non-2xx responses are turned into ApiError (RFC 7807 problem) so ErrorState can render them. */
import { ApiError, type Problem } from "@/lib/api";
import { currentUser, login } from "@/lib/auth";
import { config } from "@/lib/config";

export interface SSEFrame<T = unknown> { event: string; id?: string; data: T }

export async function postSSE<T = unknown>(path: string, body: unknown, onEvent: (f: SSEFrame<T>) => void, signal: AbortSignal): Promise<void> {
  const user = await currentUser();
  if (!user) {
    await login();
    throw new ApiError({ type: "about:blank", title: "Redirecting to sign-in", status: 401 });
  }
  const res = await fetch(`${config.apiBase}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${user.access_token}`, Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let problem: Problem;
    try {
      problem = (await res.json()) as Problem;
    } catch {
      problem = { type: "about:blank", title: res.statusText || "Request failed", status: res.status };
    }
    problem.trace_id ??= res.headers.get("X-Trace-Id") ?? undefined;
    if (res.status === 401) await login();
    throw new ApiError(problem);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx).replace(/^\r?\n\r?\n/, "");
      let event = "message";
      let id: string | undefined;
      const data: string[] = [];
      for (const line of chunk.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("id:")) id = line.slice(3).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (!data.length) continue;
      try {
        onEvent({ event, id, data: JSON.parse(data.join("\n")) as T });
      } catch {
        /* keep-alive or malformed frame */
      }
    }
  }
}
