const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export type TestCardKey = "elevated" | "highest_not_blocked" | "highest_blocked";
export type DeviceContext = "known_device" | "new_device";
export type GeoContext = "usual_location" | "new_or_foreign_location";

export interface CheckoutRequest {
  account_id: string;
  amount: number;
  merchant_id: string;
  device_context: DeviceContext;
  geo_context: GeoContext;
  recent_password_reset: boolean;
  mfa_completed: boolean;
  failed_logins_this_session: number;
  test_card: TestCardKey;
}

export interface CheckoutResponse {
  charge_succeeded: boolean;
  risk_level: string | null;
  payment_intent_id: string | null;
  signal_created: boolean;
  case_id: string | null;
  case_status: string | null;
  message: string;
}

export type CaseRoute = "critical" | "elevated" | "low";
export type CaseStatus = "auto_escalated" | "pending_review" | "closed" | "error";

export interface CaseOut {
  case_id: string;
  signal_id: string;
  account_id: string;
  signal_type: string;
  occurred_at: string;
  upstream_score: number;
  flag_reason: string;
  payload: Record<string, unknown>;
  pattern: string | null;
  triage_tier: string | null;
  confidence: number | null;
  entities: Record<string, unknown> | null;
  matched_rules: string[] | null;
  similar_cases: string[] | null;
  evidence: string[] | null;
  risk_score: number | null;
  recommended_action: string | null;
  draft_note: string | null;
  route: CaseRoute | null;
  status: CaseStatus;
  resolution: "approved" | "denied" | "none";
  approved_by: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  checkout: (body: CheckoutRequest) =>
    request<CheckoutResponse>("/checkout", { method: "POST", body: JSON.stringify(body) }),

  listPendingCases: () => request<CaseOut[]>("/cases?status=pending_review"),

  approveCase: (caseId: string, approvedBy: string) =>
    request<CaseOut>(`/cases/${caseId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: approvedBy }),
    }),

  denyCase: (caseId: string, deniedBy: string) =>
    request<CaseOut>(`/cases/${caseId}/deny`, {
      method: "POST",
      body: JSON.stringify({ denied_by: deniedBy }),
    }),
};
