/** Capital Copilot (screen 18): grounded, cited Q&A streamed over SSE. The server refuses to answer without
 * sourced evidence; the UI shows the refusal and what's missing rather than filling anything in (I1). */
import { useQuery } from "@tanstack/react-query";
import { Bot, Loader2, Send, ShieldCheck, Square, Trash2, User } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { matchPath, useLocation } from "react-router-dom";
import { ClaimItem, GapList, type Claim } from "@/components/council/shared";
import { ErrorState, PermissionDenied } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useMe, usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { postSSE } from "./postSSE";

export const REFUSAL = "I don't have sourced evidence for that.";

export interface Turn {
  id: number;
  question: string;
  status: "streaming" | "done" | "error" | "aborted";
  runId?: string;
  intents?: string[];
  matches?: { id: string; title: string }[];
  target?: unknown;
  claims: Claim[];
  answer?: string;
  grounded?: boolean;
  gaps?: string[];
  mode?: "llm" | "deterministic";
  error?: unknown;
}

interface Ctx { page: string | null; opportunityId: string | null }

/** Page context from the current route. */
export function useCopilotContext(): Ctx {
  const { pathname } = useLocation();
  return useMemo(() => {
    const opp = matchPath("/opportunities/:id", pathname);
    if (opp?.params.id) return { page: "opportunity", opportunityId: opp.params.id };
    const map: [string, string][] = [["/forecast", "forecast"], ["/radar", "radar"], ["/relationships", "relationships"]];
    const hit = map.find(([p]) => pathname === p || pathname.startsWith(`${p}/`));
    return { page: hit ? hit[1] : null, opportunityId: null };
  }, [pathname]);
}

type Frame =
  | { event: "start"; data: { run_id: string; intents: string[] } }
  | { event: "retrieval"; data: { matches: { id: string; title: string }[]; target: unknown } }
  | { event: "claim"; data: { claim: Claim } }
  | { event: "done"; data: { run_id: string; answer: string; grounded: boolean; gaps: string[]; mode: "llm" | "deterministic" } }
  | { event: "error"; data: { detail: string; trace_id?: string | null } };

/** Conversation state. Lives in the always-mounted drawer so history survives closing it (component state only). */
export function useCopilotSession() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const ctrl = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const patch = (id: number, f: (t: Turn) => Partial<Turn>) => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...f(t) } : t)));

  const ask = useCallback(async (question: string, ctx: Ctx) => {
    ctrl.current?.abort();
    const ac = new AbortController();
    ctrl.current = ac;
    const id = ++seq.current;
    setTurns((ts) => [...ts, { id, question, status: "streaming", claims: [] }]);
    try {
      await postSSE("/v1/copilot/ask", {
        question, page: ctx.page ?? undefined, opportunity_id: ctx.opportunityId ?? undefined, include_demo: true,
      }, (f) => {
        const fr = f as Frame;
        if (fr.event === "start") patch(id, () => ({ runId: fr.data.run_id, intents: fr.data.intents }));
        else if (fr.event === "retrieval") patch(id, () => ({ matches: fr.data.matches ?? [], target: fr.data.target }));
        else if (fr.event === "claim") patch(id, (t) => ({ claims: [...t.claims, fr.data.claim] }));
        else if (fr.event === "done") patch(id, () => ({
          status: "done", runId: fr.data.run_id, answer: fr.data.answer, grounded: fr.data.grounded, gaps: fr.data.gaps ?? [], mode: fr.data.mode,
        }));
        else if (fr.event === "error") patch(id, () => ({
          status: "error", error: new Error(`${fr.data.detail}${fr.data.trace_id ? ` (trace ${fr.data.trace_id})` : ""}`),
        }));
      }, ac.signal);
      patch(id, (t) => (t.status === "streaming" ? { status: "error", error: new Error("The stream ended before the answer was complete.") } : {}));
    } catch (e) {
      if (ac.signal.aborted) patch(id, () => ({ status: "aborted" }));
      else patch(id, () => ({ status: "error", error: e }));
    } finally {
      if (ctrl.current === ac) ctrl.current = null;
    }
  }, []);

  const stop = useCallback(() => ctrl.current?.abort(), []);
  const clear = useCallback(() => { ctrl.current?.abort(); setTurns([]); }, []);
  useEffect(() => () => ctrl.current?.abort(), []);
  return { turns, ask, stop, clear, busy: turns.some((t) => t.status === "streaming") };
}

function Answer({ t }: { t: Turn }) {
  if (t.status === "error") return <ErrorState error={t.error} />;
  const refused = t.status === "done" && t.grounded === false;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        {t.status === "streaming" && <span className="inline-flex items-center gap-1"><Loader2 className="size-3 animate-spin" aria-hidden /> Retrieving evidence…</span>}
        {t.status === "aborted" && <Badge>Stopped</Badge>}
        {t.mode && <Badge tone={t.mode === "llm" ? "primary" : "neutral"}>{t.mode === "llm" ? "LLM (cited)" : "Deterministic"}</Badge>}
        {t.status === "done" && (t.grounded
          ? <Badge tone="success"><ShieldCheck className="size-3" aria-hidden /> Grounded</Badge>
          : <Badge tone="warning">Refused: ungrounded</Badge>)}
        {t.intents && t.intents.length > 0 && <span>intents: {t.intents.join(", ")}</span>}
      </div>
      {t.matches && t.matches.length > 0 && (
        <div className="text-[11px] text-muted-foreground">Retrieved: {t.matches.slice(0, 5).map((m) => m.title).join(" · ")}{t.matches.length > 5 ? ` +${t.matches.length - 5}` : ""}</div>
      )}
      {t.claims.length > 0 && <ul className="space-y-1.5" aria-label="Cited claims">{t.claims.map((c, i) => <ClaimItem key={i} claim={c} />)}</ul>}
      {t.status === "streaming" && t.claims.length === 0 && <Skeleton className="h-10 w-full" />}
      {refused && (
        <>
          <p className="rounded border bg-background p-2 text-sm">{t.answer || REFUSAL}</p>
          <GapList gaps={t.gaps ?? []} title="What's missing" />
        </>
      )}
      {t.status === "done" && t.grounded && (t.gaps?.length ?? 0) > 0 && <GapList gaps={t.gaps!} title="Not covered by evidence" />}
      {t.runId && (
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground">run id
          <button type="button" title="Copy run id" aria-label={`Copy run id ${t.runId}`} onClick={() => void navigator.clipboard?.writeText(t.runId!)}
            className="max-w-[14rem] truncate rounded font-mono hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t.runId}</button></div>
      )}
    </div>
  );
}

export function CopilotChat({ session }: { session: ReturnType<typeof useCopilotSession> }) {
  const me = useMe();
  const canAsk = usePermission("copilot:ask");
  const ctx = useCopilotContext();
  const [q, setQ] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sugg = useQuery({
    queryKey: ["copilot", "suggestions", ctx.page, ctx.opportunityId],
    queryFn: () => {
      const p = new URLSearchParams();
      if (ctx.page) p.set("page", ctx.page);
      if (ctx.opportunityId) p.set("opportunity_id", ctx.opportunityId);
      return api<{ suggestions: string[] }>(`/v1/copilot/suggestions?${p.toString()}`);
    },
    enabled: canAsk,
    staleTime: 5 * 60_000,
  });
  const last = session.turns[session.turns.length - 1];
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [session.turns.length, last?.claims.length, last?.status]);

  if (me.isLoading) return <div className="space-y-2 p-4"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-2/3" /></div>;
  if (!canAsk) return <div className="p-4"><PermissionDenied detail="Asking the Copilot needs copilot:ask." /></div>;

  const send = (text: string) => {
    const v = text.trim();
    if (v.length < 2 || session.busy) return;
    setQ("");
    void session.ask(v.slice(0, 2000), ctx);
    inputRef.current?.focus();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite" aria-busy={session.busy}>
        {session.turns.length === 0 && (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>Ask about opportunities, rankings, warm intros, deadlines or runway. Every answer is built from cited records in the Capital Knowledge Graph.</p>
            {ctx.page && <p className="text-xs">Context: <Badge>{ctx.page}</Badge></p>}
          </div>
        )}
        {session.turns.map((t) => (
          <div key={t.id} className="space-y-2">
            <div className="flex items-start gap-2">
              <User className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
              <p className="flex-1 whitespace-pre-wrap rounded-md bg-primary/10 px-2 py-1.5 text-sm"><span className="sr-only">You: </span>{t.question}</p>
            </div>
            <div className="flex items-start gap-2">
              <Bot className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <div className="min-w-0 flex-1"><span className="sr-only">Copilot: </span><Answer t={t} /></div>
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="space-y-2 border-t p-3">
        {sugg.data && sugg.data.suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1" role="group" aria-label="Suggested questions">
            {sugg.data.suggestions.map((s) => (
              <button key={s} type="button" disabled={session.busy} onClick={() => send(s)}
                className="rounded-full border px-2 py-0.5 text-left text-xs text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
        )}
        {sugg.isError && <p className="text-[11px] text-muted-foreground">Suggestions unavailable.</p>}
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); send(q); }}>
          <label htmlFor="copilot-q" className="sr-only">Ask the Copilot</label>
          <textarea id="copilot-q" ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} rows={2} maxLength={2000}
            placeholder="Ask a question… (Enter to send, Shift+Enter for a new line)"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(q); } }}
            className={cn("min-h-[2.5rem] flex-1 resize-none rounded-md border border-input bg-background p-2 text-sm",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")} />
          {session.busy
            ? <Button type="button" size="icon" variant="outline" onClick={session.stop} aria-label="Stop answering"><Square /></Button>
            : <Button type="submit" size="icon" disabled={q.trim().length < 2} aria-label="Send question"><Send /></Button>}
        </form>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <ShieldCheck className="size-3" aria-hidden />
          <span className="flex-1">Refuses ungrounded answers. Every claim carries a citation; each answer has a run id for audit.</span>
          {session.turns.length > 0 && (
            <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={session.clear}><Trash2 /> Clear</Button>
          )}
        </div>
      </div>
    </div>
  );
}
