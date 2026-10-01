import { useMutation } from "@tanstack/react-query";
import { FileSpreadsheet, Loader2 } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "@/components/approvals/shared";
import { downloadBinary } from "@/components/dataroom/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { usePermission } from "@/lib/queries";

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Compliance report export (xlsx): chain verification, approvals, releases, holds, retention and admin changes. */
export function ComplianceReportCard() {
  const allowed = usePermission("audit:read");
  const today = new Date();
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 30 * 86_400_000)));
  const [to, setTo] = useState(iso(today));
  const m = useMutation({
    mutationFn: () => downloadBinary(`/v1/audit/compliance-report?${new URLSearchParams({ from, to })}`, `compliance-report-${from}-to-${to}.xlsx`),
  });
  if (!allowed) return null;
  const invalid = !from || !to || from > to;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Compliance report export</CardTitle>
        <p className="text-xs text-muted-foreground">
          An Excel workbook for the period: hash-chain status, approvals, external releases, legal holds, retention runs and admin changes. The export itself is audited.
        </p>
      </CardHeader>
      <CardContent>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <label className="text-sm">From
            <Input className="mt-1 w-40" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} required />
          </label>
          <label className="text-sm">To
            <Input className="mt-1 w-40" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} required />
          </label>
          <Button type="submit" disabled={invalid || m.isPending}>{m.isPending ? <Loader2 className="animate-spin" /> : <FileSpreadsheet />} Download xlsx</Button>
        </form>
        {invalid && from && to && <p className="mt-2 text-sm text-destructive" role="alert">The start date must be on or before the end date.</p>}
        {m.isError && <p className="mt-2 text-sm text-destructive" role="alert">{errorMessage(m.error)}</p>}
        {m.data && <p className="mt-2 text-sm text-success" role="status">Saved {m.data.filename}.</p>}
      </CardContent>
    </Card>
  );
}
