import { useState } from "react";
import { api, type CheckoutResponse, type DeviceContext, type GeoContext, type TestCardKey } from "../api";

// Fixed seeded personas (spec §8: a persona picker beats freeform fields for
// a repeatable demo). These account_ids must match backend/app/synthetic/personas_seed.py.
const PERSONAS = [
  { account_id: "acct_longtenured_1", label: "Long-tenured, low risk" },
  { account_id: "acct_newaccount_1", label: "Brand-new account" },
  { account_id: "acct_thinhistory_1", label: "Thin history, one cleared case" },
  { account_id: "acct_thinhistory_2", label: "Thin history, two cleared cases" },
];

const TEST_CARDS: { key: TestCardKey; label: string; number: string }[] = [
  { key: "elevated", label: "Elevated risk (flagged for review)", number: "4000000000009235" },
  { key: "highest_not_blocked", label: "Highest risk, not auto-blocked", number: "4000000000004954" },
  { key: "highest_blocked", label: "Highest risk, always blocked by Stripe", number: "4100000000000019" },
];

export function Checkout() {
  const [accountId, setAccountId] = useState(PERSONAS[0].account_id);
  const [amount, setAmount] = useState(120);
  const [merchantId, setMerchantId] = useState("merch_demo_electronics");
  const [deviceContext, setDeviceContext] = useState<DeviceContext>("known_device");
  const [geoContext, setGeoContext] = useState<GeoContext>("usual_location");
  const [recentPasswordReset, setRecentPasswordReset] = useState(false);
  const [mfaCompleted, setMfaCompleted] = useState(true);
  const [failedLogins, setFailedLogins] = useState(0);
  const [testCard, setTestCard] = useState<TestCardKey>("elevated");

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CheckoutResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.checkout({
        account_id: accountId,
        amount,
        merchant_id: merchantId,
        device_context: deviceContext,
        geo_context: geoContext,
        recent_password_reset: recentPasswordReset,
        mfa_completed: mfaCompleted,
        failed_logins_this_session: failedLogins,
        test_card: testCard,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <h1>Casework — Checkout</h1>
      <form onSubmit={handleSubmit} className="card">
        <label>
          Persona
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {PERSONAS.map((p) => (
              <option key={p.account_id} value={p.account_id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Amount (USD)
          <input
            type="number"
            min={0.01}
            step={0.01}
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
        </label>

        <label>
          Merchant
          <input value={merchantId} onChange={(e) => setMerchantId(e.target.value)} />
        </label>

        <label>
          Device
          <select
            value={deviceContext}
            onChange={(e) => setDeviceContext(e.target.value as DeviceContext)}
          >
            <option value="known_device">Known device</option>
            <option value="new_device">New device</option>
          </select>
        </label>

        <label>
          Location
          <select value={geoContext} onChange={(e) => setGeoContext(e.target.value as GeoContext)}>
            <option value="usual_location">Usual location</option>
            <option value="new_or_foreign_location">New or foreign location</option>
          </select>
        </label>

        <fieldset>
          <legend>Session flags</legend>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={recentPasswordReset}
              onChange={(e) => setRecentPasswordReset(e.target.checked)}
            />
            Recent password reset
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={mfaCompleted}
              onChange={(e) => setMfaCompleted(e.target.checked)}
            />
            MFA completed
          </label>
          <label>
            Failed logins this session
            <input
              type="number"
              min={0}
              value={failedLogins}
              onChange={(e) => setFailedLogins(Number(e.target.value))}
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>Stripe test card (Radar, test mode)</legend>
          {TEST_CARDS.map((card) => (
            <label className="checkbox" key={card.key}>
              <input
                type="radio"
                name="test_card"
                value={card.key}
                checked={testCard === card.key}
                onChange={() => setTestCard(card.key)}
              />
              {card.label} ({card.number})
            </label>
          ))}
        </fieldset>

        <button type="submit" disabled={submitting}>
          {submitting ? "Authorizing…" : "Submit order"}
        </button>
      </form>

      {error && <div className="banner error">{error}</div>}

      {result && (
        <div className={`banner ${result.authorized ? "success" : "declined"}`}>
          <p>{result.message}</p>
          <dl>
            {result.risk_level && (
              <>
                <dt>Risk level</dt>
                <dd>{result.risk_level}</dd>
              </>
            )}
            {result.case_id && (
              <>
                <dt>Case</dt>
                <dd>
                  {result.case_id} ({result.case_status})
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}
