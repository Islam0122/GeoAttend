import type { Me, Role } from "@/api/types";

export const isAdmin = (me: Me | null) => !!me && (me.role === "OWNER" || me.role === "ADMIN");
export const isHR = (me: Me | null) => !!me && ["OWNER", "ADMIN", "HR"].includes(me.role);
export const isStaff = (me: Me | null) => !!me && ["OWNER", "ADMIN", "HR", "MANAGER"].includes(me.role);
export const canSeeReports = (me: Me | null) => isStaff(me) || me?.role === "ACCOUNTANT";
export const isManager = (me: Me | null) => me?.role === "MANAGER";
export const ROLE_LABEL: Record<Role, string> = { OWNER: "Owner", ADMIN: "Admin", HR: "HR", MANAGER: "Manager", EMPLOYEE: "Employee", ACCOUNTANT: "Accountant" };

/** Landing route after sign-in. */
export function homeFor(me: Me): string {
  if (isHR(me) || me.role === "ACCOUNTANT") return "/app/admin";
  if (isManager(me)) return "/app/team";
  return "/app";
}
