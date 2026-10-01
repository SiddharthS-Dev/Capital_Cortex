/** Generate a board pack for a period (default: last full quarter). */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileBarChart, Loader2 } from "lucide-react";
import { useState } from "react";
import { MutationError } from "@/components/proposals/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { RecipientsInput } from "./RecipientsInput";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function lastQuarter(now = new Date()): { start: string; end: string } {
  const q = Math.floor(now.getMonth() / 3);
  return { start: iso(new Date(now.getFullYear(), (q - 1) * 3, 1)), end: iso(new Date(now.getFullYear(), q * 3, 0)) };
}

export function GenerateForm({ onCreated }: { onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const lq = lastQuarter();
  const [start, setStart] = useState(lq.start);
  const [end, setEnd] = useState(lq.end);
  const [recipients, setRecipients] = useState<string[]>([]);
  const [includeDemo, setIncludeDemo] = useState(false);
  const m = useMutation({
    mutationFn: () => api<{ id: string; sections: number; gaps: number; compliance: string }>("/v1/board-reports", {
      method: "POST", body: JSON.stringify({ period_start: start, period_end: end, recipients, include_demo: includeDemo }),
    }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["board-reports"] });
      onCreated(r.id);
    },
  });
  const badPeriod = !start || !end || start > end;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Generate a board pack</CardTitle>
        <p className="text-xs text-muted-foreground">
          Built deterministically from the period's records. Every statement is cited; anything without evidence is listed as a gap rather than filled in.
        </p>
      </CardHeader>
      <CardContent>
        <form className="grid gap-3 md:grid-cols-[auto_auto_1fr_auto] md:items-end" onSubmit={(e) => { e.preventDefault(); if (!badPeriod) m.mutate(); }}>
          <div>
            <label htmlFor="br-start" className="block text-xs font-medium">Period start</label>
            <Input id="br-start" type="date" value={start} max={end || undefined} onChange={(e) => setStart(e.target.value)} className="mt-1 w-44" required />
          </div>
          <div>
            <label htmlFor="br-end" className="block text-xs font-medium">Period end</label>
            <Input id="br-end" type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} className="mt-1 w-44" required />
          </div>
          <div>
            <label htmlFor="br-recipients" className="block text-xs font-medium">Recipients <span className="font-normal text-muted-foreground">(can be set later)</span></label>
            <div className="mt-1"><RecipientsInput id="br-recipients" value={recipients} onChange={setRecipients} /></div>
          </div>
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} />
              Include demo (synthetic) data
            </label>
            <Button type="submit" disabled={m.isPending || badPeriod}>
              {m.isPending ? <Loader2 className="animate-spin" /> : <FileBarChart />} Generate pack
            </Button>
          </div>
          {badPeriod && <p className="text-xs text-destructive md:col-span-4" role="alert">The period start must be on or before its end.</p>}
          <div className="md:col-span-4"><MutationError error={m.error} /></div>
        </form>
      </CardContent>
    </Card>
  );
}
