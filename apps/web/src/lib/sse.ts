/** Authenticated server-sent events over fetch() (EventSource can't send an Authorization header).
 * Calls onEvent for every frame until the stream ends or the signal aborts. Used by the live deliberation
 * view (/v1/agents/runs/{id}/stream); the global notification stream lives in live.ts. */
import { currentUser } from "./auth";
import { config } from "./config";

export interface SSEFrame<T = unknown> {
  event: string;
  id?: string;
  data: T;
}

export async function streamSSE<T = unknown>(
  path: string,
  onEvent: (f: SSEFrame<T>) => void,
  signal: AbortSignal,
): Promise<void> {
  const user = await currentUser();
  if (!user) throw new Error("not signed in");
  const res = await fetch(`${config.apiBase}${path}`, {
    headers: { Authorization: `Bearer ${user.access_token}`, Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
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
