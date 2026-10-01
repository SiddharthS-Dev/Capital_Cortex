import { useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleSlash } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { label } from "@/lib/format";

interface ExtensionsOut { extensions: Record<string, string>; note: string }

export function ExtensionsTab() {
  const q = useQuery({ queryKey: ["admin", "extensions"], queryFn: () => api<ExtensionsOut>("/v1/admin/extensions") });
  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const entries = Object.entries(q.data!.extensions);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Extension points (read-only)</CardTitle>
        <p className="text-xs text-muted-foreground">{q.data!.note} Flags are set in config/extensions.yaml.</p>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? <EmptyState title="No extension points declared" /> : (
          <ul className="divide-y text-sm">
            {entries.map(([name, status]) => (
              <li key={name} className="flex items-center gap-2 py-2">
                <span className="flex-1 font-medium">{label(name)} <code className="ml-1 text-xs text-muted-foreground">{name}</code></span>
                {status === "enabled"
                  ? <Badge tone="success"><CircleCheck className="size-3" aria-hidden /> Enabled</Badge>
                  : <Badge><CircleSlash className="size-3" aria-hidden /> {status}</Badge>}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
