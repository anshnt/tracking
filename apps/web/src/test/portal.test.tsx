import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SideNav } from "../App";
import { post } from "../api/client";
import type { Me, Role } from "../api/types";
import { MY_EXPORTS_URL, onlyMine } from "../pages/Exports";
import { needsHuman, needsRetry } from "../pages/Offboarding";
import { QUEUE_LIMIT, queueUrls } from "../pages/ExportQueue";
import { navFor } from "../lib/nav";
import { postureBadge } from "../lib/posture";

const user = (roles: Role[]): Me => ({
  id: "1",
  display_name: "Test",
  email: "t@example.test",
  roles,
  status: "active",
  timezone: "UTC",
  manager_id: null,
});

function links(roles: Role[]): string[] {
  render(
    <MemoryRouter>
      <SideNav me={user(roles)} />
    </MemoryRouter>,
  );
  return screen.getAllByRole("link").map((a) => a.textContent ?? "");
}

describe("role-based navigation", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows only employee pages to a plain employee", () => {
    const got = links(["employee"]);
    expect(got).toContain("My workspaces");
    expect(got).not.toContain("Security cases");
    expect(got).not.toContain("Offboarding");
    expect(got).not.toContain("Team overview");
    expect(got).not.toContain("People and assets");
  });

  it("adds team, security and admin pages by role", () => {
    const paths = (r: Role[]) => navFor(r).map((i) => i.to);
    expect(paths(["employee", "manager"])).toContain("/team");
    // GET /overview is manager-only: admins get no work-content access, so no link to a page that 403s
    expect(paths(["employee", "admin"])).not.toContain("/team");
    expect(paths(["employee", "security"])).toContain("/cases");
    expect(paths(["employee", "security"])).not.toContain("/export-queue");
    expect(paths(["employee", "approver"])).toContain("/export-queue");
    expect(paths(["employee", "it"])).toContain("/offboarding");
    expect(paths(["employee", "admin"])).toEqual(expect.arrayContaining(["/policies", "/admin", "/connectors"]));
    // admin does not imply security
    expect(paths(["employee", "admin"])).not.toContain("/cases");
  });
});

describe("posture badges", () => {
  it("maps each state and never turns unknown input green", () => {
    expect(postureBadge("compliant").tone).toBe("ok");
    expect(postureBadge("noncompliant").tone).toBe("bad");
    expect(postureBadge("unknown").tone).toBe("warn");
    expect(postureBadge("not_applicable").label).toBe("Not applicable");
    expect(postureBadge("something_new").label).toBe("Unknown");
    expect(postureBadge("something_new").tone).not.toBe("ok");
  });
});

describe("api client", () => {
  function mockFetch() {
    const fn = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fn);
    return fn;
  }

  it("sends the CSRF header and same-origin cookies on unsafe methods", async () => {
    const fn = mockFetch();
    await post("/work-updates", { summary: "x" });
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/work-updates");
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["X-Requested-With"]).toBe("portal");
  });

  it("does not add the header to GET and surfaces the server message on errors", async () => {
    const fn = mockFetch();
    const { get } = await import("../api/client");
    await get("/me");
    expect((fn.mock.calls[0] as unknown as [string, RequestInit])[1].headers).not.toHaveProperty("X-Requested-With");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 409 })));
    await expect(get("/me")).rejects.toMatchObject({ status: 409, message: "nope" });
  });
});

describe("offboarding manual steps", () => {
  it("offers Mark done only for steps a person can complete", () => {
    expect(needsHuman({ subsystem: "verify", status: "failed" })).toBe(false);
    expect(needsHuman({ subsystem: "revoke_export_grants", status: "failed" })).toBe(false);
    expect(needsRetry({ subsystem: "verify", status: "failed" })).toBe(true);
    expect(needsHuman({ subsystem: "google_workspace", status: "manual_required" })).toBe(true);
    expect(needsHuman({ subsystem: "google_workspace", status: "succeeded" })).toBe(false);
  });
});

describe("my exports", () => {
  it("asks for own requests with the max page and still filters by requester", () => {
    expect(MY_EXPORTS_URL).toContain("mine=true");
    expect(MY_EXPORTS_URL).toContain("limit=500");
    const rows = [{ requester_id: "a" }, { requester_id: "b" }] as never[];
    expect(onlyMine(rows, "a")).toHaveLength(1);
  });
});

describe("export queue", () => {
  it("defaults to the actionable statuses with the max page, and warns by limit", () => {
    const urls = queueUrls("");
    expect(urls).toHaveLength(3);
    expect(urls.every((u) => u.includes(`limit=${QUEUE_LIMIT}`))).toBe(true);
    expect(urls.some((u) => u.includes("status=staged"))).toBe(true);
    expect(queueUrls("all")).toEqual([`/export-requests?limit=${QUEUE_LIMIT}`]);
  });
});
