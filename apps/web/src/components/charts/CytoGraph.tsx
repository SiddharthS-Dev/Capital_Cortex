import cytoscape, { type Core, type ElementDefinition, type NodeSingular } from "cytoscape";
import fcose from "cytoscape-fcose";
import { Maximize, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { GraphData } from "@/lib/types";
import { chartTheme } from "./EChart";

cytoscape.use(fcose);

export const NODE_COLORS: Record<string, string> = {
  Organization: "#4f7cff", Investor: "#7b61ff", Fund: "#b05ce6", GrantProgram: "#12a37f", Opportunity: "#e8830c",
  Contact: "#0ca5b0", Meeting: "#6cbf3b", Signal: "#8a94a6", Proposal: "#e64980", Document: "#c2963b",
  Outcome: "#2f9e44", Recommendation: "#d9480f",
};

/** Entity types that anchor a cluster: drawn larger, with their label always on. Everything else is a leaf. */
const HUBS = new Set(["Organization", "Investor", "Fund", "GrantProgram"]);
const LEAF_SIZE: Record<string, number> = { Opportunity: 16, Signal: 11 };

export type Layout = "fcose" | "cose" | "concentric" | "breadthfirst" | "circle";
export const LAYOUTS: Layout[] = ["fcose", "cose", "concentric", "breadthfirst", "circle"];

export function nodeTitle(n: { label: string; properties: Record<string, unknown> }) {
  return String(n.properties.title ?? n.properties.name ?? n.label);
}

/** Cytoscape's colour parser rejects CSS4 space-separated hsl(), so resolve theme colours to rgb() via the browser. */
function cytoTheme() {
  const probe = document.createElement("span");
  document.body.appendChild(probe);
  const rgb = (c: string) => { probe.style.color = ""; probe.style.color = c; return getComputedStyle(probe).color || c; };
  const t = Object.fromEntries(Object.entries(chartTheme()).map(([k, v]) => [k, rgb(v)])) as ReturnType<typeof chartTheme>;
  probe.remove();
  return t;
}

const shorten = (s: string, max = 34) => (s.length > max ? `${s.slice(0, max - 1)}…` : s);
const ZOOM_STEP = 1.6;

function layoutOptions(name: Layout): cytoscape.LayoutOptions {
  const base = { name, animate: false, padding: 30, fit: true, nodeDimensionsIncludeLabels: true };
  switch (name) {
    case "fcose":
      // packComponents tiles the many small org-centred clusters instead of letting them collide
      return { ...base, quality: "proof", randomize: true, idealEdgeLength: 70, nodeRepulsion: 7000, nodeSeparation: 70,
        gravity: 0.3, packComponents: true, tile: true, tilingPaddingVertical: 20, tilingPaddingHorizontal: 20 } as cytoscape.LayoutOptions;
    case "cose":
      return { ...base, idealEdgeLength: 80, nodeRepulsion: 9000, componentSpacing: 90, nodeOverlap: 20 } as cytoscape.LayoutOptions;
    case "concentric":
      return { ...base, minNodeSpacing: 24, concentric: (n: NodeSingular) => n.degree(false), levelWidth: () => 2 } as cytoscape.LayoutOptions;
    case "breadthfirst":
      return { ...base, spacingFactor: 1.1, directed: false } as cytoscape.LayoutOptions;
    default:
      return { ...base, spacingFactor: 0.9 } as cytoscape.LayoutOptions;
  }
}

/** Cytoscape canvas. Nodes are keyed by their domain id; clicking one calls onSelect. */
export function CytoGraph({ data, layout = "fcose", height = 520, selected, onSelect, onExpand }: {
  data: GraphData; layout?: Layout; height?: number; selected?: string | null;
  onSelect?: (id: string) => void; onExpand?: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    if (!ref.current) return;
    const t = cytoTheme();
    const labelBg = { "text-background-color": t.card, "text-background-opacity": 0.85, "text-background-padding": "1px",
      "text-background-shape": "roundrectangle" } as const;
    cy.current = cytoscape({
      container: ref.current,
      // ~27% per mouse-wheel notch (the default is ~5%, so reaching readable labels took ~25 notches)
      wheelSensitivity: 5,
      minZoom: 0.1,
      maxZoom: 4,
      style: [
        // Leaf labels only appear once zoomed in far enough to read them (min-zoomed-font-size).
        { selector: "node", style: { "background-color": "data(color)", label: "data(title)", color: t.fg, "font-size": 8,
          "min-zoomed-font-size": 8, "text-wrap": "ellipsis", "text-max-width": "120px", "text-valign": "bottom",
          "text-margin-y": 3, width: "data(size)", height: "data(size)", "border-width": 1, "border-color": t.card, ...labelBg } },
        { selector: "node[?hub]", style: { "font-size": 11, "font-weight": "bold", "min-zoomed-font-size": 5, "border-width": 2 } },
        { selector: "node[?demo]", style: { "border-width": 2, "border-color": "#f5a623", "border-style": "dashed" } },
        { selector: "edge", style: { width: 1, "line-color": t.border, "target-arrow-color": t.border, "target-arrow-shape": "triangle",
          "arrow-scale": 0.6, "curve-style": "bezier", label: "data(type)", "font-size": 7, "min-zoomed-font-size": 10,
          color: t.muted, "text-rotation": "autorotate", ...labelBg } },
        { selector: 'edge[type = "DERIVED_FROM"]', style: { "line-style": "dashed" } },
        // Hover / selection: light up the neighbourhood, fade the rest.
        { selector: ".faded", style: { opacity: 0.15, "text-opacity": 0 } },
        { selector: "node.hl", style: { "min-zoomed-font-size": 0, "z-index": 10 } },
        { selector: "edge.hl", style: { width: 2, "line-color": t.primary, "target-arrow-color": t.primary, "min-zoomed-font-size": 0, "z-index": 10 } },
        { selector: "node:selected", style: { "border-width": 3, "border-color": t.primary } },
      ],
    });
    const c = cy.current;
    const focus = (n: NodeSingular) => {
      const hood = n.closedNeighborhood();
      c.elements().removeClass("hl").addClass("faded");
      hood.removeClass("faded").addClass("hl");
    };
    const unfocus = () => {
      const sel = c.nodes(":selected");
      if (sel.nonempty()) focus(sel.first());
      else c.elements().removeClass("faded hl");
    };
    c.on("tap", "node", (e) => onSelect?.(e.target.id()));
    c.on("dbltap", "node", (e) => onExpand?.(e.target.id()));
    c.on("mouseover", "node", (e) => focus(e.target));
    c.on("mouseout", "node", unfocus);
    c.on("select unselect", "node", unfocus);
    // double-click on empty canvas zooms in on that point (double-click on a node still expands it)
    c.on("dbltap", (e) => {
      if (e.target === c) c.animate({ zoom: { level: c.zoom() * 2, renderedPosition: e.renderedPosition } }, { duration: 200 });
    });
    c.on("zoom", () => setZoom(c.zoom()));
    return () => c.destroy();
    // handlers are stable enough for a graph view; re-binding would reset the canvas
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const els: ElementDefinition[] = [
      ...data.nodes.map((n) => {
        const hub = HUBS.has(n.label);
        return { data: { id: n.id, title: shorten(nodeTitle(n)), color: NODE_COLORS[n.label] ?? "#888", label: n.label, hub,
          size: hub ? 28 : LEAF_SIZE[n.label] ?? 14, demo: Boolean(n.properties.is_demo) } };
      }),
      ...data.edges.map((e) => ({ data: { id: `e${e.id}`, source: e.source, target: e.target, type: e.type } })),
    ];
    c.elements().remove();
    c.add(els);
    c.layout(layoutOptions(layout)).run();
    setZoom(c.zoom());
  }, [data, layout]);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.nodes().unselect();
    if (selected) c.getElementById(selected).select();
  }, [selected, data]);

  /** Zoom around the centre of the canvas, animated. */
  const zoomBy = (factor: number) => {
    const c = cy.current;
    if (!c) return;
    const level = Math.min(c.maxZoom(), Math.max(c.minZoom(), c.zoom() * factor));
    c.stop().animate({ zoom: { level, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } } }, { duration: 200 });
  };
  const fit = () => cy.current?.stop().animate({ fit: { eles: cy.current.elements(), padding: 30 } }, { duration: 250 });
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "+" || e.key === "=") zoomBy(ZOOM_STEP);
    else if (e.key === "-" || e.key === "_") zoomBy(1 / ZOOM_STEP);
    else if (e.key === "0") fit();
    else return;
    e.preventDefault();
  };
  const ctl = "flex size-8 items-center justify-center hover:bg-accent disabled:opacity-40";

  return (
    <div className="relative">
      <div ref={ref} style={{ height }} tabIndex={0} onKeyDown={onKey} role="img"
        className="w-full rounded-md border bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Knowledge graph with ${data.nodes.length} nodes and ${data.edges.length} edges. Plus and minus keys zoom, 0 fits.`} />
      <div className="absolute right-2 top-2 flex flex-col overflow-hidden rounded-md border bg-card text-muted-foreground shadow-sm"
        role="group" aria-label="Zoom">
        <button type="button" className={ctl} onClick={() => zoomBy(ZOOM_STEP)} disabled={zoom >= 4} title="Zoom in (+)" aria-label="Zoom in"><ZoomIn className="size-4" /></button>
        <button type="button" className={`${ctl} border-t`} onClick={() => zoomBy(1 / ZOOM_STEP)} disabled={zoom <= 0.1} title="Zoom out (−)" aria-label="Zoom out"><ZoomOut className="size-4" /></button>
        <button type="button" className={`${ctl} border-t`} onClick={fit} title="Fit to screen (0)" aria-label="Fit to screen"><Maximize className="size-4" /></button>
        <span className="border-t py-1 text-center text-[10px] tabular-nums" aria-live="polite">{Math.round(zoom * 100)}%</span>
      </div>
    </div>
  );
}
