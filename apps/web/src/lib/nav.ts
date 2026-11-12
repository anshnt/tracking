import type { Role } from "../api/types";

export interface NavItem {
  to: string;
  label: string;
  /** Empty means every signed-in user. The server enforces the same rules; this only hides links. */
  roles: Role[];
  group: "Me" | "Team" | "Security" | "Operations" | "Admin";
}

export const NAV: NavItem[] = [
  { to: "/", label: "Home", roles: [], group: "Me" },
  { to: "/workspaces", label: "My workspaces", roles: [], group: "Me" },
  { to: "/tasks", label: "My tasks", roles: [], group: "Me" },
  { to: "/updates", label: "Daily update", roles: [], group: "Me" },
  { to: "/exports", label: "My exports", roles: [], group: "Me" },
  { to: "/records", label: "My records", roles: [], group: "Me" },
  { to: "/team", label: "Team overview", roles: ["manager"], group: "Team" },
  { to: "/devices", label: "Devices and workspaces", roles: ["manager", "it", "security", "admin"], group: "Team" },
  { to: "/cases", label: "Security cases", roles: ["security"], group: "Security" },
  { to: "/export-queue", label: "Export queue", roles: ["approver", "it", "admin"], group: "Security" },
  { to: "/offboarding", label: "Offboarding", roles: ["it", "admin"], group: "Operations" },
  { to: "/connectors", label: "Connector health", roles: ["it", "admin"], group: "Operations" },
  { to: "/policies", label: "Policy versions", roles: ["admin"], group: "Admin" },
  { to: "/admin", label: "People and assets", roles: ["admin"], group: "Admin" },
];

export function hasRole(userRoles: readonly Role[], ...wanted: Role[]): boolean {
  return wanted.length === 0 || wanted.some((r) => userRoles.includes(r));
}

export function navFor(userRoles: readonly Role[]): NavItem[] {
  return NAV.filter((i) => hasRole(userRoles, ...i.roles));
}
