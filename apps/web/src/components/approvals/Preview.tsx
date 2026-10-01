/** Renders an approval/outbox preview: an email as a letter, an export or recommendation as title + text + claims. */
import { Badge } from "@/components/ui/primitives";
import { label, pct } from "@/lib/format";
import { pretty, type Claim, type Preview } from "./shared";

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : Array.isArray(v) ? v.map(String).join(", ") || null : null);
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

function claimText(c: unknown): { text: string; kind?: string; evidence: number } {
  if (typeof c === "string") return { text: c, evidence: 0 };
  const o = obj(c) as Partial<Claim> | null;
  return { text: String(o?.text ?? pretty(c)), kind: o?.kind, evidence: Array.isArray(o?.evidence) ? o!.evidence!.length : 0 };
}

function Claims({ claims }: { claims: unknown[] }) {
  if (claims.length === 0) return null;
  return (
    <div>
      <h4 className="mb-1 text-xs font-medium text-muted-foreground">Claims ({claims.length})</h4>
      <ul className="space-y-1">
        {claims.map((c, i) => {
          const t = claimText(c);
          return (
            <li key={i} className="rounded bg-muted/40 p-2 text-sm">
              {t.text}
              <span className="ml-2 text-[11px] text-muted-foreground">
                {t.kind ? `${label(t.kind)} · ` : ""}{t.evidence} evidence item{t.evidence === 1 ? "" : "s"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Recommendation({ rec, confidence }: { rec: Record<string, unknown>; confidence?: unknown }) {
  const gaps = Array.isArray(rec.gaps) ? rec.gaps : [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {str(rec.stance) && <Badge tone="primary">Stance: {label(String(rec.stance))}</Badge>}
        {typeof confidence === "number" && <Badge>Confidence {pct(confidence)}</Badge>}
      </div>
      {str(rec.text) && <p className="whitespace-pre-line text-sm leading-relaxed">{String(rec.text)}</p>}
      <Claims claims={Array.isArray(rec.claims) ? rec.claims : []} />
      {gaps.length > 0 && (
        <ul className="space-y-1">
          {gaps.map((g, i) => (
            <li key={i} className="rounded border border-dashed border-band-insufficient/60 bg-band-insufficient/10 p-2 text-xs text-band-insufficient">
              [EVIDENCE REQUIRED] {typeof g === "string" ? g : pretty(g)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PreviewView({ preview }: { preview: Preview | null | undefined }) {
  if (!preview) return <p className="text-sm text-muted-foreground">No preview was captured for this item.</p>;
  const rec = obj(preview.recommendation);
  if (rec) return <Recommendation rec={rec} confidence={preview.confidence} />;

  const payload = obj(preview.payload) ?? preview;
  const channel = str(preview.channel);
  const to = str(payload.to) ?? str(preview.recipient);
  const subject = str(payload.subject);
  const body = str(payload.body) ?? str(payload.text);

  if (channel === "email" || subject || (body && to)) {
    return (
      <article className="rounded-md border bg-background shadow-sm" aria-label="Email preview">
        <dl className="grid grid-cols-[4.5rem_1fr] gap-x-2 gap-y-1 border-b p-3 text-sm">
          <dt className="text-muted-foreground">To</dt><dd className="break-all">{to ?? "—"}</dd>
          {str(payload.cc) && <><dt className="text-muted-foreground">Cc</dt><dd className="break-all">{str(payload.cc)}</dd></>}
          <dt className="text-muted-foreground">Subject</dt><dd className="font-medium">{subject ?? "(no subject)"}</dd>
        </dl>
        <div className="whitespace-pre-wrap p-4 font-serif text-sm leading-relaxed">{body ?? "(empty body)"}</div>
      </article>
    );
  }

  const inner = obj(payload.recommendation);
  const title = str(payload.title);
  if (title || inner || Array.isArray(payload.claims)) {
    return (
      <article className="space-y-3 rounded-md border bg-background p-4" aria-label="Export preview">
        <div className="flex flex-wrap items-center gap-2">
          {channel && <Badge>{label(channel)}</Badge>}
          {str(preview.kind) && <Badge>{label(String(preview.kind))}</Badge>}
        </div>
        {title && <h4 className="text-base font-semibold">{title}</h4>}
        {inner ? <Recommendation rec={inner} confidence={payload.confidence} /> : (
          <>
            {str(payload.recommendation) && <p className="whitespace-pre-line text-sm">{String(payload.recommendation)}</p>}
            <Claims claims={Array.isArray(payload.claims) ? payload.claims : []} />
          </>
        )}
      </article>
    );
  }

  return <pre className="max-h-80 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs">{pretty(payload)}</pre>;
}
