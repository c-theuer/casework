import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

function mockFetchOnce(body: unknown, init?: { ok?: boolean; status?: number; statusText?: string }) {
  const ok = init?.ok ?? true;
  const status = init?.status ?? (ok ? 200 : 500);
  const statusText = init?.statusText ?? (ok ? "OK" : "Internal Server Error");
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api.checkout", () => {
  it("posts the request body to /checkout with JSON headers", async () => {
    const fetchMock = mockFetchOnce({ authorized: true });

    await api.checkout({
      account_id: "acct_1",
      amount: 10,
      merchant_id: "merch_1",
      device_context: "known_device",
      geo_context: "usual_location",
      recent_password_reset: false,
      mfa_completed: true,
      failed_logins_this_session: 0,
      test_card: "elevated",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/checkout");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({
      account_id: "acct_1",
      amount: 10,
      merchant_id: "merch_1",
      device_context: "known_device",
      geo_context: "usual_location",
      recent_password_reset: false,
      mfa_completed: true,
      failed_logins_this_session: 0,
      test_card: "elevated",
    });
  });

  it("resolves with the parsed JSON response", async () => {
    mockFetchOnce({ authorized: true, risk_level: "elevated" });

    const result = await api.checkout({
      account_id: "acct_1",
      amount: 10,
      merchant_id: "merch_1",
      device_context: "known_device",
      geo_context: "usual_location",
      recent_password_reset: false,
      mfa_completed: true,
      failed_logins_this_session: 0,
      test_card: "elevated",
    });

    expect(result).toEqual({ authorized: true, risk_level: "elevated" });
  });
});

describe("api.listPendingCases", () => {
  it("sends a GET to /cases?status=pending_review", async () => {
    const fetchMock = mockFetchOnce([]);

    await api.listPendingCases();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/cases?status=pending_review");
    expect(init.method).toBeUndefined();
  });
});

describe("api.approveCase", () => {
  it("posts {approved_by} to /cases/{id}/approve", async () => {
    const fetchMock = mockFetchOnce({ case_id: "c1" });

    await api.approveCase("c1", "analyst_demo");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/cases/c1/approve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ approved_by: "analyst_demo" });
  });
});

describe("api.denyCase", () => {
  it("posts {denied_by} to /cases/{id}/deny", async () => {
    const fetchMock = mockFetchOnce({ case_id: "c1" });

    await api.denyCase("c1", "analyst_demo");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/cases/c1/deny");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ denied_by: "analyst_demo" });
  });
});

describe("request() error handling", () => {
  it("throws an Error with status, statusText, and body text on a non-ok response", async () => {
    mockFetchOnce("case not found", { ok: false, status: 404, statusText: "Not Found" });

    await expect(api.approveCase("missing", "analyst_demo")).rejects.toThrow(
      "404 Not Found: case not found",
    );
  });
});
