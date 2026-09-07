import { useCallback, useEffect, useRef, useState } from "react";
import { api, type CaseOut } from "../api";

const POLL_INTERVAL_MS = 2000;

const TIER_CLASS: Record<string, string> = {
  critical: "tier-critical",
  elevated: "tier-elevated",
  low: "tier-low",
};

export function Queue() {
  const [cases, setCases] = useState<CaseOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyCaseId, setBusyCaseId] = useState<string | null>(null);
  const approverName = useRef("analyst_demo");

  const refresh = useCallback(async () => {
    try {
      const next = await api.listPendingCases();
      setCases(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function handleApprove(caseId: string) {
    setBusyCaseId(caseId);
    try {
      await api.approveCase(caseId, approverName.current);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyCaseId(null);
    }
  }

  async function handleDeny(caseId: string) {
    setBusyCaseId(caseId);
    try {
      await api.denyCase(caseId, approverName.current);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyCaseId(null);
    }
  }

  return (
    <div className="page">
      <h1>Casework — Fraud-ops queue</h1>
      {error && <div className="banner error">{error}</div>}
      {cases.length === 0 && !error && <p>No cases awaiting review.</p>}

      <div className="queue">
        {cases.map((c) => (
          <div key={c.case_id} className={`card queue-item ${TIER_CLASS[c.route ?? ""] ?? ""}`}>
            <div className="queue-item-header">
              <span className={`badge ${TIER_CLASS[c.route ?? ""] ?? ""}`}>{c.route}</span>
              <span className="status">{c.status}</span>
            </div>
            <p>
              <strong>{c.pattern}</strong> — account {c.account_id}, ${c.payload.amount as number}
            </p>
            <p className="draft-note">{c.draft_note}</p>
            <dl>
              <dt>Risk score</dt>
              <dd>{c.risk_score?.toFixed(2)}</dd>
              <dt>Recommended action</dt>
              <dd>{c.recommended_action}</dd>
            </dl>
            <div className="actions">
              <button disabled={busyCaseId === c.case_id} onClick={() => handleApprove(c.case_id)}>
                Approve
              </button>
              <button
                disabled={busyCaseId === c.case_id}
                className="secondary"
                onClick={() => handleDeny(c.case_id)}
              >
                Deny
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
