import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, ShieldCheck, ShieldQuestion, ShieldX, X } from "lucide-react";
import { useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { date } from "@/lib/format";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { focusRing, StepUpNote } from "./shared";

interface AdminUser {
  id: string; username: string; email: string | null; name: string | null; enabled: boolean;
  roles: string[]; grants: string[]; mfa_configured: boolean; required_actions: string[] | null; created: string | number | null;
}
interface UsersOut { items: AdminUser[]; roles: Record<string, { mfa: boolean | string | null; description: string | null }>; mfa_enforced: boolean }

const MAX_ROLES = 6;

function created(v: AdminUser["created"]) {
  if (v == null) return "—";
  return typeof v === "number" ? date(new Date(v).toISOString()) : date(v);
}

function MfaStatus({ u, roles, enforced }: { u: AdminUser; roles: UsersOut["roles"]; enforced: boolean }) {
  if (u.mfa_configured) return <Badge tone="success"><ShieldCheck className="size-3" aria-hidden /> Configured</Badge>;
  const required = u.roles.some((r) => roles[r]?.mfa === true || roles[r]?.mfa === "required");
  return required
    ? <Badge tone="warning"><ShieldX className="size-3" aria-hidden /> Required by role{enforced ? ", not set up" : " (not enforced here)"}</Badge>
    : <Badge><ShieldQuestion className="size-3" aria-hidden /> Optional</Badge>;
}

function EditRoles({ user, roles, onClose }: { user: AdminUser; roles: UsersOut["roles"]; onClose: () => void }) {
  const qc = useQueryClient();
  const [sel, setSel] = useState<string[]>(user.roles.filter((r) => r in roles));
  const save = useMutation({
    mutationFn: () => api<{ added: string[]; removed: string[] }>("/v1/admin/users", { method: "PUT", body: JSON.stringify({ user_id: user.id, roles: sel }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["admin", "users"] }); },
  });
  const err = save.error instanceof ApiError ? save.error.problem : null;
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 space-y-4 rounded-lg border bg-card p-5 shadow-2xl">
          <div className="flex items-center gap-2">
            <Dialog.Title className="flex-1 text-sm font-semibold">Edit roles: {user.name ?? user.username}</Dialog.Title>
            <Dialog.Close className={cn("rounded p-1 hover:bg-accent", focusRing)} aria-label="Close"><X className="size-4" /></Dialog.Close>
          </div>
          <Dialog.Description className="text-xs text-muted-foreground">
            Platform roles are synced to Keycloak. Up to {MAX_ROLES} roles. Direct grants are unaffected.
          </Dialog.Description>
          <fieldset className="space-y-2">
            <legend className="sr-only">Roles</legend>
            {Object.entries(roles).map(([r, info]) => {
              const checked = sel.includes(r);
              return (
                <label key={r} className="flex items-start gap-2 rounded border p-2 text-sm">
                  <input type="checkbox" className={cn("mt-0.5", focusRing)} checked={checked}
                    disabled={!checked && sel.length >= MAX_ROLES}
                    onChange={() => setSel((s) => (checked ? s.filter((x) => x !== r) : [...s, r]))} />
                  <span className="flex-1">
                    <span className="font-medium">{r}</span>
                    {(info.mfa === true || info.mfa === "required") && <Badge tone="warning" className="ml-2">MFA required</Badge>}
                    {info.description && <span className="block text-xs text-muted-foreground">{info.description}</span>}
                  </span>
                </label>
              );
            })}
          </fieldset>
          <StepUpNote>Changing roles requires a fresh sign-in with MFA (step-up) and is written to the audit log.</StepUpNote>
          {save.isSuccess && (
            <p role="status" className="text-sm text-success">
              Roles updated. Added: {save.data.added.length ? save.data.added.join(", ") : "none"}. Removed: {save.data.removed.length ? save.data.removed.join(", ") : "none"}.
            </p>
          )}
          {save.isError && <p role="alert" className="text-sm text-destructive">{err?.step_up ? "Step-up sign-in required. Redirecting…" : err?.detail ?? (save.error as Error).message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>{save.isSuccess ? "Close" : "Cancel"}</Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending}>Save roles</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function UsersTab() {
  const canWrite = usePermission("admin:write");
  const q = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<UsersOut>("/v1/admin/users"), retry: false });
  const [editing, setEditing] = useState<AdminUser | null>(null);
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Users and roles</CardTitle>
        <p className="text-xs text-muted-foreground">
          Synced from Keycloak. MFA is {d.mfa_enforced ? "enforced for roles that require it" : "not enforced in this environment"}.
        </p>
      </CardHeader>
      <CardContent>
        {d.items.length === 0 ? (
          <EmptyState title="No users in the realm" next="Create users in Keycloak, then assign platform roles here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-2 py-1 text-left font-medium">User</th>
                  <th scope="col" className="px-2 py-1 text-left font-medium">Roles</th>
                  <th scope="col" className="px-2 py-1 text-left font-medium">MFA</th>
                  <th scope="col" className="px-2 py-1 text-left font-medium">Status</th>
                  <th scope="col" className="px-2 py-1 text-left font-medium">Created</th>
                  {canWrite && <th scope="col" className="px-2 py-1"><span className="sr-only">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {d.items.map((u) => (
                  <tr key={u.id} className="border-t align-top">
                    <td className="px-2 py-2">
                      <div className="font-medium">{u.name ?? u.username}</div>
                      <div className="text-xs text-muted-foreground">{u.username}{u.email ? ` · ${u.email}` : ""}</div>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex flex-wrap gap-1">
                        {u.roles.length ? u.roles.map((r) => <Badge key={r} tone="primary">{r}</Badge>) : <span className="text-xs text-muted-foreground">No roles</span>}
                        {u.grants.map((g) => <Badge key={g} className="font-mono" title="Direct grant">+{g}</Badge>)}
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <MfaStatus u={u} roles={d.roles} enforced={d.mfa_enforced} />
                      {u.required_actions && u.required_actions.length > 0 && (
                        <div className="mt-1 text-[11px] text-muted-foreground">Pending: {u.required_actions.join(", ")}</div>
                      )}
                    </td>
                    <td className="px-2 py-2">{u.enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="destructive">Disabled</Badge>}</td>
                    <td className="px-2 py-2 text-xs text-muted-foreground">{created(u.created)}</td>
                    {canWrite && (
                      <td className="px-2 py-2 text-right">
                        <Button size="sm" variant="outline" onClick={() => setEditing(u)} aria-label={`Edit roles for ${u.username}`}><Pencil /> Roles</Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {editing && <EditRoles user={editing} roles={d.roles} onClose={() => setEditing(null)} />}
      </CardContent>
    </Card>
  );
}
