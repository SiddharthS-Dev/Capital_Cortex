import * as echarts from "echarts/core";
import { BarChart, GaugeChart, LineChart, MapChart, PieChart, RadarChart, FunnelChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  MarkLineComponent,
  RadarComponent,
  DatasetComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, type ReactNode } from "react";
import { useUI } from "@/store/ui";

echarts.use([
  BarChart, GaugeChart, LineChart, MapChart, PieChart, RadarChart, FunnelChart,
  GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, MarkLineComponent, RadarComponent,
  DatasetComponent, CanvasRenderer,
]);

export { echarts };

/** Theme-aware colours pulled from the CSS tokens, so charts follow light/dark mode. */
export function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string) => `hsl(${css.getPropertyValue(n).trim()})`;
  return { fg: v("--foreground"), muted: v("--muted-foreground"), border: v("--border"), card: v("--card"),
           primary: v("--primary"), success: v("--success"), warning: v("--warning"), destructive: v("--destructive") };
}

interface Props {
  option: echarts.EChartsCoreOption;
  height?: number | string;
  ariaLabel: string;
  /** Accessible fallback (WCAG): the same data as a table, in a collapsible disclosure. */
  table?: ReactNode;
  onClick?: (params: Record<string, unknown>) => void;
}

export function EChart({ option, height = 280, ariaLabel, table, onClick }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const theme = useUI((s) => s.theme);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const t = chartTheme();
    chart.current?.setOption(
      {
        textStyle: { color: t.fg, fontFamily: "Inter, system-ui, sans-serif" },
        tooltip: { backgroundColor: t.card, borderColor: t.border, textStyle: { color: t.fg } },
        ...option,
      },
      { notMerge: true },
    );
  }, [option, theme]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onClick) return;
    const h = (p: unknown) => onClick(p as Record<string, unknown>);
    c.on("click", h);
    return () => {
      c.off("click", h);
    };
  }, [onClick]);

  return (
    <div>
      <div ref={ref} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />
      {table && (
        <details className="mt-1 text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none">Data table</summary>
          <div className="mt-1 overflow-x-auto">{table}</div>
        </details>
      )}
    </div>
  );
}

export function DataTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr>{head.map((h) => <th key={h} scope="col" className="px-2 py-1 text-left font-medium">{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t">{r.map((c, j) => <td key={j} className="px-2 py-1 tabular-nums">{c}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}
