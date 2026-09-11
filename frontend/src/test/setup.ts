import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without vitest's `globals: true` (deliberately not set, to keep explicit
// imports everywhere), @testing-library/react's own auto-cleanup can't
// detect a global afterEach to hook into, so it's wired up explicitly here.
afterEach(cleanup);
