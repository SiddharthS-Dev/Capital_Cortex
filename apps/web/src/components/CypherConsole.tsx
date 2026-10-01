/** Admin-only, read-only Cypher console (Monaco bundled locally; the CSP forbids CDN scripts). Lazy-loaded. */
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { useState } from "react";
import { api } from "@/lib/api";
import type { GraphData } from "@/lib/types";
import { useUI } from "@/store/ui";
import { ErrorState } from "./states";
import { Button } from "./ui/button";

self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

export default function CypherConsole({ onResult }: { onResult: (g: GraphData) => void }) {
  const theme = useUI((s) => s.theme);
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [q, setQ] = useState("MATCH (o:Organization)-[r:OFFERS]->(p:Opportunity)\nRETURN [o, r, p] LIMIT 50");
  const [err, setErr] = useState<unknown>(null);
  const [rows, setRows] = useState<number | null>(null);
  const run = async () => {
    setErr(null);
    try {
      const g = await api<GraphData>(`/v1/graph/query?template=cypher&limit=500&cypher=${encodeURIComponent(q)}`);
      setRows(g.rows?.length ?? 0);
      onResult(g);
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-md border">
        <Editor height="140px" defaultLanguage="cypher" value={q} onChange={(v) => setQ(v ?? "")} theme={dark ? "vs-dark" : "light"}
          options={{ minimap: { enabled: false }, fontSize: 13, lineNumbers: "off", scrollBeyondLastLine: false }} />
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={run}>Run (read-only)</Button>
        <span className="text-xs text-muted-foreground">Write clauses are rejected, and the query runs in a READ ONLY transaction. Every query is audited.</span>
        {rows !== null && <span className="text-xs">{rows} rows</span>}
      </div>
      {err !== null && <ErrorState error={err} />}
    </div>
  );
}
