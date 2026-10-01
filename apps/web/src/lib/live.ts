/** Real-time updates: one authenticated SSE stream (/v1/events/stream) per tab.
 *
 * EventSource can't send an Authorization header, so this uses fetch() and parses the stream itself.
 * Events are notifications only: on each one the relevant queries are invalidated and refetched through
 * the normal authorised endpoints. It reconnects with backoff. */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { create } from "zustand";
import { currentUser } from "./auth";
import { config } from "./config";

export interface LiveEvent {
  type: string;
  opportunity_id?: string;
  title?: string;
  class?: string | null;
  score?: number | null;
  band?: string;
  is_demo?: boolean;
  source_id?: string;
  status?: string;
  new?: number;
  fetched?: number;
  count?: number;
  run_id?: string;
  ids?: string[];
  at?: string;
}

interface LiveState {
  connected: boolean;
  events: LiveEvent[];
  newSinceView: number;
  setConnected: (c: boolean) => void;
  push: (e: LiveEvent) => void;
  clearNew: () => void;
}

export const useLive = create<LiveState>((set) => ({
  connected: false,
  events: [],
  newSinceView: 0,
  setConnected: (connected) => set({ connected }),
  push: (e) =>
    set((s) => ({
      events: [e, ...s.events].slice(0, 50),
      newSinceView: s.newSinceView + (e.type === "opportunity.created" ? 1 : 0),
    })),
  clearNew: () => set({ newSinceView: 0 }),
}));

function invalidate(qc: QueryClient, e: LiveEvent) {
  if (e.type.startsWith("opportunity") || e.type === "scoring.rescored") {
    void qc.invalidateQueries({ queryKey: ["opportunities"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
    void qc.invalidateQueries({ queryKey: ["preview"] });
    if (e.opportunity_id) void qc.invalidateQueries({ queryKey: ["opportunity", e.opportunity_id] });
    if (e.type === "scoring.rescored") void qc.invalidateQueries({ queryKey: ["opportunity"] });
  }
  if (e.type.startsWith("agent_run")) {
    void qc.invalidateQueries({ queryKey: ["agents"] });
    void qc.invalidateQueries({ queryKey: ["agent-runs"] });
  }
  if (e.type.startsWith("approval") || e.type === "outbox.updated") {
    void qc.invalidateQueries({ queryKey: ["approvals"] });
    void qc.invalidateQueries({ queryKey: ["outbox"] });
    void qc.invalidateQueries({ queryKey: ["recommendations"] });
  }
  if (e.type.startsWith("alert")) void qc.invalidateQueries({ queryKey: ["alerts"] });
  if (e.type === "relationship.updated") {
    for (const k of ["contacts", "contact-timeline", "milestones", "meetings", "calendar", "recall"])
      void qc.invalidateQueries({ queryKey: [k] });
  }
  if (e.type === "recommendation.updated") void qc.invalidateQueries({ queryKey: ["recommendations"] });
  if (e.type === "proposal.updated") {
    void qc.invalidateQueries({ queryKey: ["proposals"] });
    for (const id of e.ids ?? []) void qc.invalidateQueries({ queryKey: ["proposal", id] });
  }
  if (e.type === "dataroom.updated") void qc.invalidateQueries({ queryKey: ["dataroom"] });
  if (e.type === "board_report.updated") void qc.invalidateQueries({ queryKey: ["board-reports"] });
  if (e.type === "source.run") {
    void qc.invalidateQueries({ queryKey: ["sources"] });
    void qc.invalidateQueries({ queryKey: ["source-runs"] });
  }
}

export function useLiveEvents() {
  const qc = useQueryClient();
  useEffect(() => {
    let stopped = false;
    let ctrl: AbortController | null = null;
    let attempt = 0;
    // Invalidations are batched: a 150-item ingest run shouldn't cause 150 refetch waves.
    const pending = new Map<string, LiveEvent>();
    let flush: ReturnType<typeof setTimeout> | null = null;
    const schedule = (e: LiveEvent) => {
      pending.set(`${e.type}:${e.opportunity_id ?? e.source_id ?? e.run_id ?? ""}`, e);
      if (!flush)
        flush = setTimeout(() => {
          pending.forEach((ev) => invalidate(qc, ev));
          pending.clear();
          flush = null;
        }, 1200);
    };

    const run = async () => {
      while (!stopped) {
        const user = await currentUser();
        if (!user) {
          await new Promise((r) => setTimeout(r, 3000));
          continue;
        }
        ctrl = new AbortController();
        try {
          const res = await fetch(`${config.apiBase}/v1/events/stream`, {
            headers: { Authorization: `Bearer ${user.access_token}`, Accept: "text/event-stream" },
            signal: ctrl.signal,
          });
          if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
          useLive.getState().setConnected(true);
          attempt = 0;
          const reader = res.body.getReader();
          const dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            let idx;
            while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
              const chunk = buf.slice(0, idx);
              buf = buf.slice(idx).replace(/^\r?\n\r?\n/, "");
              const data = chunk
                .split(/\r?\n/)
                .filter((l) => l.startsWith("data:"))
                .map((l) => l.slice(5).trim())
                .join("\n");
              if (!data) continue;
              try {
                const ev = JSON.parse(data) as LiveEvent;
                if (ev.type) {
                  useLive.getState().push(ev);
                  schedule(ev);
                }
              } catch {
                /* keep-alive or malformed frame */
              }
            }
          }
        } catch {
          /* network drop or token expiry: reconnect below */
        }
        useLive.getState().setConnected(false);
        if (stopped) break;
        attempt += 1;
        await new Promise((r) => setTimeout(r, Math.min(30_000, 1000 * 2 ** attempt)));
      }
    };
    void run();
    return () => {
      stopped = true;
      ctrl?.abort();
      if (flush) clearTimeout(flush);
    };
  }, [qc]);
}
