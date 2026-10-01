import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import worldTopo from "world-atlas/countries-110m.json";
import { useMemo } from "react";
import { chartTheme, DataTable, EChart, echarts } from "./EChart";

let registered = false;
function ensureMap() {
  if (registered) return;
  const topo = worldTopo as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>;
  const geo = feature(topo, topo.objects.countries) as unknown as {
    type: "FeatureCollection";
    features: { id?: string | number; properties: { name: string } }[];
  };
  // world-atlas ids are ISO 3166-1 numeric; match on those, never on display names.
  geo.features.forEach((f) => {
    f.properties = { ...f.properties, name: String(f.id ?? f.properties.name).padStart(3, "0") };
  });
  echarts.registerMap("world", geo as never);
  registered = true;
}

export interface MapDatum {
  numeric: string | null;
  name: string;
  iso2: string;
  count: number;
}

export function WorldMap({ data, height = 320, onSelect }: { data: MapDatum[]; height?: number; onSelect?: (iso2: string) => void }) {
  ensureMap();
  const byNumeric = useMemo(() => new Map(data.filter((d) => d.numeric).map((d) => [d.numeric!.padStart(3, "0"), d])), [data]);
  const max = Math.max(1, ...data.map((d) => d.count));
  const t = chartTheme();
  const option = useMemo(
    () => ({
      tooltip: {
        trigger: "item",
        formatter: (p: { name: string }) => {
          const d = byNumeric.get(p.name);
          return d ? `${d.name}: ${d.count} opportunit${d.count === 1 ? "y" : "ies"}` : "No opportunities";
        },
      },
      visualMap: { min: 0, max, left: 8, bottom: 8, calculable: false, inRange: { color: ["#dbe7ff", "#2b5fd9"] },
                   textStyle: { color: t.muted }, itemWidth: 10, itemHeight: 80 },
      series: [{
        type: "map", map: "world", roam: true, zoom: 1.15, emphasis: { label: { show: false } },
        itemStyle: { areaColor: t.border, borderColor: t.card, borderWidth: 0.5 },
        data: data.filter((d) => d.numeric).map((d) => ({ name: d.numeric!.padStart(3, "0"), value: d.count })),
      }],
    }),
    [data, byNumeric, max, t.muted, t.border, t.card],
  );
  return (
    <EChart
      option={option}
      height={height}
      ariaLabel="Map of opportunities by eligible country"
      onClick={(p) => {
        const d = byNumeric.get(String(p.name));
        if (d && onSelect) onSelect(d.iso2);
      }}
      table={<DataTable head={["Country", "Opportunities"]} rows={data.map((d) => [d.name, d.count])} />}
    />
  );
}
