import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { hasPermission } from "./utils";

export interface Me {
  sub: string;
  username: string;
  name: string | null;
  email: string | null;
  roles: string[];
  permissions: string[];
  mfa: boolean;
  mfa_required: boolean;
  clearance: string;
  is_service: boolean;
}

export interface Meta {
  version: string;
  env: string;
  current_phase: number;
  feature_phases: Record<string, number>;
  demo_mode: boolean;
  demo_data_present: boolean;
}

export interface BudgetSummary {
  day: string;
  spent_usd: number;
  cap_usd: number;
  remaining_usd: number;
  features: { feature: string; spent_usd: number; cap_usd: number | null; tokens_in: number; tokens_out: number }[];
}

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/v1/me"), staleTime: 60_000 });

export const useMeta = () =>
  useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/v1/meta"), staleTime: 5 * 60_000 });

export function usePermission(permission: string): boolean {
  const { data } = useMe();
  return hasPermission(data?.permissions, permission);
}

export function useBudget(enabled: boolean) {
  return useQuery({
    queryKey: ["budget"],
    queryFn: () => api<BudgetSummary>("/v1/admin/budgets"),
    enabled,
    refetchInterval: 60_000,
  });
}

export function usePendingApprovals(enabled: boolean) {
  return useQuery({
    queryKey: ["approvals", "pending", "count"],
    queryFn: () => api<{ total: number }>("/v1/approvals?status=pending&limit=1"),
    enabled,
    refetchInterval: 30_000,
  });
}

export function useOpenAlerts(enabled: boolean) {
  return useQuery({
    queryKey: ["alerts", "bell"],
    queryFn: () => api<{ open: number; open_by_severity: Record<string, number> }>("/v1/alerts?status=open&limit=1"),
    enabled,
    refetchInterval: 60_000,
  });
}
