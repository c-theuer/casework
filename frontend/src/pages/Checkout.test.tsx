import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type CheckoutResponse } from "../api";
import { Checkout } from "./Checkout";

vi.mock("../api", () => ({
  api: {
    checkout: vi.fn(),
  },
}));

const mockedCheckout = vi.mocked(api.checkout);

beforeEach(() => {
  mockedCheckout.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("Checkout", () => {
  it("renders all personas and all Stripe test cards with the expected defaults selected", () => {
    render(<Checkout />);

    expect(screen.getByRole("option", { name: "Long-tenured, low risk" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Brand-new account" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Thin history, one cleared case" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Thin history, two cleared cases" })).toBeInTheDocument();

    const elevatedCard = screen.getByRole("radio", { name: /Elevated risk/ });
    const highestNotBlocked = screen.getByRole("radio", { name: /Highest risk, not auto-blocked/ });
    const highestBlocked = screen.getByRole("radio", { name: /always blocked/ });
    expect(elevatedCard).toBeChecked();
    expect(highestNotBlocked).not.toBeChecked();
    expect(highestBlocked).not.toBeChecked();

    expect(screen.getByRole("combobox", { name: "Device" })).toHaveValue("known_device");
    expect(screen.getByRole("combobox", { name: "Location" })).toHaveValue("usual_location");
    expect(screen.getByRole("checkbox", { name: "MFA completed" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Recent password reset" })).not.toBeChecked();
  });

  it("submits the exact request shape built from the current form state", async () => {
    const user = userEvent.setup();
    mockedCheckout.mockResolvedValue({
      authorized: true,
      risk_level: "elevated",
      payment_intent_id: "pi_1",
      signal_created: true,
      case_id: null,
      case_status: null,
      message: "ok",
    });
    render(<Checkout />);

    await user.selectOptions(screen.getByRole("combobox", { name: "Persona" }), "acct_newaccount_1");
    await user.click(screen.getByRole("checkbox", { name: "Recent password reset" }));
    await user.click(screen.getByRole("radio", { name: /Highest risk, not auto-blocked/ }));
    await user.click(screen.getByRole("button", { name: "Submit order" }));

    await waitFor(() => expect(mockedCheckout).toHaveBeenCalledTimes(1));
    expect(mockedCheckout).toHaveBeenCalledWith({
      account_id: "acct_newaccount_1",
      amount: 120,
      merchant_id: "merch_demo_electronics",
      device_context: "known_device",
      geo_context: "usual_location",
      recent_password_reset: true,
      mfa_completed: true,
      failed_logins_this_session: 0,
      test_card: "highest_not_blocked",
    });
  });

  it("disables the submit button and shows 'Authorizing…' while the request is in flight", async () => {
    const user = userEvent.setup();
    const { promise, resolve } = deferred<CheckoutResponse>();
    mockedCheckout.mockReturnValue(promise);
    render(<Checkout />);

    const button = screen.getByRole("button", { name: "Submit order" });
    await user.click(button);

    expect(await screen.findByRole("button", { name: "Authorizing…" })).toBeDisabled();

    resolve({
      authorized: true,
      risk_level: "elevated",
      payment_intent_id: "pi_1",
      signal_created: true,
      case_id: null,
      case_status: null,
      message: "ok",
    });

    expect(await screen.findByRole("button", { name: "Submit order" })).toBeEnabled();
  });

  it("renders a success banner and only the fields present on the response", async () => {
    const user = userEvent.setup();
    mockedCheckout.mockResolvedValue({
      authorized: true,
      risk_level: "elevated",
      payment_intent_id: "pi_1",
      signal_created: true,
      case_id: "case_123",
      case_status: "pending_review",
      message: "Authorization succeeded and a case was created.",
    });
    render(<Checkout />);

    await user.click(screen.getByRole("button", { name: "Submit order" }));

    const banner = await screen.findByText("Authorization succeeded and a case was created.");
    expect(banner.closest(".banner")).toHaveClass("success");
    expect(screen.getByText("Risk level")).toBeInTheDocument();
    expect(screen.getByText("elevated")).toBeInTheDocument();
    expect(screen.getByText("Case")).toBeInTheDocument();
    expect(screen.getByText("case_123 (pending_review)")).toBeInTheDocument();
  });

  it("renders a declined banner without the optional fields when the response omits them", async () => {
    const user = userEvent.setup();
    mockedCheckout.mockResolvedValue({
      authorized: false,
      risk_level: null,
      payment_intent_id: null,
      signal_created: false,
      case_id: null,
      case_status: null,
      message: "Authorization declined by Stripe Radar. Casework never saw this transaction.",
    });
    render(<Checkout />);

    await user.click(screen.getByRole("button", { name: "Submit order" }));

    const banner = await screen.findByText(
      "Authorization declined by Stripe Radar. Casework never saw this transaction.",
    );
    expect(banner.closest(".banner")).toHaveClass("declined");
    expect(screen.queryByText("Risk level")).not.toBeInTheDocument();
    expect(screen.queryByText("Case")).not.toBeInTheDocument();
  });

  it("renders an error banner with the thrown error's message on rejection", async () => {
    const user = userEvent.setup();
    mockedCheckout.mockRejectedValue(new Error("500 Internal Server Error: boom"));
    render(<Checkout />);

    await user.click(screen.getByRole("button", { name: "Submit order" }));

    const banner = await screen.findByText("500 Internal Server Error: boom");
    expect(banner).toHaveClass("banner", "error");
  });
});
