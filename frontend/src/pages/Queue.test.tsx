import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type CaseOut } from "../api";
import { Queue } from "./Queue";

vi.mock("../api", () => ({
  api: {
    listPendingCases: vi.fn(),
    approveCase: vi.fn(),
    denyCase: vi.fn(),
  },
}));

const mockedList = vi.mocked(api.listPendingCases);
const mockedApprove = vi.mocked(api.approveCase);
const mockedDeny = vi.mocked(api.denyCase);

function makeCase(overrides: Partial<CaseOut> = {}): CaseOut {
  return {
    case_id: "case_1",
    signal_id: "sig_1",
    account_id: "acct_1",
    signal_type: "transaction",
    occurred_at: "2026-09-10T00:00:00Z",
    upstream_score: 0.6,
    flag_reason: "stripe_radar_elevated",
    payload: { amount: 42 },
    pattern: "merchant_fraud",
    triage_tier: "elevated",
    confidence: 0.6,
    entities: {},
    matched_rules: [],
    similar_cases: [],
    evidence: [],
    risk_score: 0.55,
    recommended_action: "flag_for_review",
    draft_note: "Review recommended.",
    route: "elevated",
    status: "pending_review",
    resolution: "none",
    approved_by: null,
    source: "live_stripe",
    created_at: "2026-09-10T00:00:00Z",
    updated_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mockedList.mockReset();
  mockedApprove.mockReset();
  mockedDeny.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Queue", () => {
  it("loads and renders cases on mount", async () => {
    mockedList.mockResolvedValue([
      makeCase({ case_id: "case_1", account_id: "acct_1", pattern: "merchant_fraud", payload: { amount: 42 } }),
    ]);

    render(<Queue />);

    expect(await screen.findByText(/merchant_fraud/)).toBeInTheDocument();
    expect(screen.getByText(/account acct_1, \$42/)).toBeInTheDocument();
    expect(screen.getByText("Review recommended.")).toBeInTheDocument();
    expect(screen.getByText("0.55")).toBeInTheDocument();
    expect(screen.getByText("flag_for_review")).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledTimes(1);
  });

  it("shows the empty-queue message when there are no cases and no error", async () => {
    mockedList.mockResolvedValue([]);

    render(<Queue />);

    expect(await screen.findByText("No cases awaiting review.")).toBeInTheDocument();
  });

  it("shows an error banner instead when the initial load fails", async () => {
    mockedList.mockRejectedValue(new Error("500 Internal Server Error: db down"));

    render(<Queue />);

    const banner = await screen.findByText("500 Internal Server Error: db down");
    expect(banner).toHaveClass("banner", "error");
    expect(screen.queryByText("No cases awaiting review.")).not.toBeInTheDocument();
  });

  it("polls again after the interval and stops polling after unmount", async () => {
    vi.useFakeTimers();
    mockedList.mockResolvedValue([]);

    const { unmount } = render(<Queue />);
    await vi.waitFor(() => expect(mockedList).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(2000);
    expect(mockedList).toHaveBeenCalledTimes(2);

    unmount();
    await vi.advanceTimersByTimeAsync(2000);
    expect(mockedList).toHaveBeenCalledTimes(2);
  });

  it("disables only the busy row's buttons while approving, then refreshes", async () => {
    const user = userEvent.setup();
    mockedList.mockResolvedValue([
      makeCase({ case_id: "case_1", account_id: "acct_1" }),
      makeCase({ case_id: "case_2", account_id: "acct_2" }),
    ]);
    const { promise, resolve } = deferred<CaseOut>();
    mockedApprove.mockReturnValue(promise);

    render(<Queue />);
    await screen.findByText(/acct_1/);

    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    const denyButtons = screen.getAllByRole("button", { name: "Deny" });
    await user.click(approveButtons[0]);

    expect(approveButtons[0]).toBeDisabled();
    expect(denyButtons[0]).toBeDisabled();
    expect(approveButtons[1]).toBeEnabled();
    expect(denyButtons[1]).toBeEnabled();
    expect(mockedApprove).toHaveBeenCalledWith("case_1", "analyst_demo");

    mockedList.mockResolvedValue([makeCase({ case_id: "case_2", account_id: "acct_2" })]);
    resolve(makeCase({ case_id: "case_1" }));

    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Approve" })[0]).toBeEnabled());
  });

  it("deny calls denyCase and refreshes", async () => {
    const user = userEvent.setup();
    mockedList.mockResolvedValue([makeCase({ case_id: "case_1", account_id: "acct_1" })]);
    mockedDeny.mockResolvedValue(makeCase({ case_id: "case_1" }));

    render(<Queue />);
    await screen.findByText(/acct_1/);

    await user.click(screen.getByRole("button", { name: "Deny" }));

    await waitFor(() => expect(mockedDeny).toHaveBeenCalledWith("case_1", "analyst_demo"));
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
  });

  it("surfaces an approve failure in the error banner and re-enables the row", async () => {
    const user = userEvent.setup();
    mockedList.mockResolvedValue([makeCase({ case_id: "case_1", account_id: "acct_1" })]);
    mockedApprove.mockRejectedValue(new Error("409 Conflict: already resolved"));

    render(<Queue />);
    await screen.findByText(/acct_1/);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("409 Conflict: already resolved")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled());
  });

  it("applies the tier class for a known route and falls back gracefully for a null route", async () => {
    mockedList.mockResolvedValue([
      makeCase({ case_id: "case_1", account_id: "acct_critical", route: "critical" }),
      makeCase({ case_id: "case_2", account_id: "acct_none", route: null }),
    ]);

    render(<Queue />);
    await screen.findByText(/acct_critical/);

    const criticalCard = screen.getByText(/acct_critical/).closest(".queue-item");
    const noRouteCard = screen.getByText(/acct_none/).closest(".queue-item");
    expect(criticalCard).toHaveClass("tier-critical");
    expect(noRouteCard).not.toHaveClass("tier-critical", "tier-elevated", "tier-low");
    expect(noRouteCard?.querySelector("span.badge")?.textContent).toBe("");
  });
});
