import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Spinner } from "@/components/common";
import { AppShell } from "@/components/layout/AppShell";
import { canSeeReports, homeFor, isAdmin, isHR, isStaff } from "@/lib/roles";
import { useAuthStore } from "@/stores/auth";
import type { Me } from "@/api/types";
import { PublicLayout } from "@/pages/public/PublicLayout";
import { Landing } from "@/pages/public/Landing";
import { Pricing } from "@/pages/public/Pricing";
import { AcceptInvite, GoogleCallback, Login, Register } from "@/pages/public/Auth";
import { MyDashboard } from "@/pages/employee/MyDashboard";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const lazyNamed = <M, K extends keyof M>(load: () => Promise<M>, name: K) => lazy(async () => ({ default: (await load())[name] as React.ComponentType<any> }));

const MyAttendance = lazyNamed(() => import("@/pages/employee/MyAttendance"), "MyAttendance");
const MySchedule = lazyNamed(() => import("@/pages/employee/MySchedule"), "MySchedule");
const MyReports = lazyNamed(() => import("@/pages/employee/MyReports"), "MyReports");
const Profile = lazyNamed(() => import("@/pages/employee/Profile"), "Profile");
const Notifications = lazyNamed(() => import("@/pages/Notifications"), "Notifications");
const Dashboard = lazy(async () => ({ default: (await import("@/pages/staff/Dashboard")).Dashboard }));
const AttendancePage = lazy(async () => ({ default: (await import("@/pages/staff/AttendancePage")).AttendancePage }));
const Reports = lazy(async () => ({ default: (await import("@/pages/staff/Reports")).Reports }));
const Monitoring = lazyNamed(() => import("@/pages/staff/Monitoring"), "Monitoring");
const Approvals = lazyNamed(() => import("@/pages/staff/Review"), "Approvals");
const Corrections = lazyNamed(() => import("@/pages/staff/Review"), "Corrections");
const Anomalies = lazyNamed(() => import("@/pages/staff/Review"), "Anomalies");
const LeaveRequests = lazy(async () => ({ default: (await import("@/features/LeaveRequests")).LeaveRequests }));
const Employees = lazyNamed(() => import("@/pages/admin/Employees"), "Employees");
const Departments = lazyNamed(() => import("@/pages/admin/Departments"), "Departments");
const Offices = lazyNamed(() => import("@/pages/admin/Offices"), "Offices");
const Schedules = lazyNamed(() => import("@/pages/admin/Schedules"), "Schedules");
const Settings = lazyNamed(() => import("@/pages/admin/Settings"), "Settings");
const Billing = lazyNamed(() => import("@/pages/admin/Billing"), "Billing");
const Audit = lazyNamed(() => import("@/pages/admin/Audit"), "Audit");

function Loading() {
  return <div className="grid min-h-[40vh] place-items-center"><Spinner className="size-6 text-primary" /></div>;
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, bootstrapped } = useAuthStore();
  const loc = useLocation();
  if (!bootstrapped) return <Loading />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

/** Client-side guard for UX only — the API enforces every permission. */
function Guard({ allow, children }: { allow: (me: Me) => boolean; children: ReactNode }) {
  const me = useAuthStore((s) => s.me)!;
  return allow(me) ? <>{children}</> : <Navigate to={homeFor(me)} replace />;
}

function AppHome() {
  const me = useAuthStore((s) => s.me)!;
  return me.employee_id ? <MyDashboard /> : <Navigate to={homeFor(me)} replace />;
}

const hasEmployee = (me: Me) => !!me.employee_id;
const orgViewer = (me: Me) => isHR(me) || me.role === "ACCOUNTANT";

export function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<PublicLayout />}>
          <Route index element={<Landing />} />
          <Route path="pricing" element={<Pricing />} />
        </Route>
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="accept-invite" element={<AcceptInvite />} />
        <Route path="auth/google/callback" element={<GoogleCallback />} />

        <Route path="app" element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<AppHome />} />
          <Route path="attendance" element={<Guard allow={hasEmployee}><MyAttendance /></Guard>} />
          <Route path="schedule" element={<Guard allow={hasEmployee}><MySchedule /></Guard>} />
          <Route path="reports" element={<Guard allow={hasEmployee}><MyReports /></Guard>} />
          <Route path="leave" element={<Guard allow={hasEmployee}><LeaveRequests mode="mine" /></Guard>} />
          <Route path="profile" element={<Profile />} />
          <Route path="notifications" element={<Notifications />} />

          <Route path="team" element={<Guard allow={isStaff}><Dashboard scope="team" /></Guard>} />
          <Route path="team/attendance" element={<Guard allow={isStaff}><AttendancePage scope="team" /></Guard>} />
          <Route path="team/monitoring" element={<Guard allow={isStaff}><Monitoring /></Guard>} />
          <Route path="team/approvals" element={<Guard allow={isStaff}><Approvals /></Guard>} />
          <Route path="team/corrections" element={<Guard allow={isStaff}><Corrections /></Guard>} />
          <Route path="team/leave" element={<Guard allow={isStaff}><LeaveRequests mode="review" /></Guard>} />
          <Route path="team/reports" element={<Guard allow={canSeeReports}><Reports scope="team" /></Guard>} />

          <Route path="admin" element={<Guard allow={orgViewer}><Dashboard scope="org" /></Guard>} />
          <Route path="admin/attendance" element={<Guard allow={orgViewer}><AttendancePage scope="org" /></Guard>} />
          <Route path="admin/reports" element={<Guard allow={canSeeReports}><Reports scope="org" /></Guard>} />
          <Route path="admin/monitoring" element={<Guard allow={isStaff}><Monitoring /></Guard>} />
          <Route path="admin/approvals" element={<Guard allow={isStaff}><Approvals /></Guard>} />
          <Route path="admin/corrections" element={<Guard allow={isStaff}><Corrections /></Guard>} />
          <Route path="admin/anomalies" element={<Guard allow={isStaff}><Anomalies /></Guard>} />
          <Route path="admin/leave" element={<Guard allow={isStaff}><LeaveRequests mode="review" /></Guard>} />
          <Route path="admin/employees" element={<Guard allow={isHR}><Employees /></Guard>} />
          <Route path="admin/departments" element={<Guard allow={isHR}><Departments /></Guard>} />
          <Route path="admin/schedules" element={<Guard allow={isHR}><Schedules /></Guard>} />
          <Route path="admin/offices" element={<Guard allow={isAdmin}><Offices /></Guard>} />
          <Route path="admin/settings" element={<Guard allow={isAdmin}><Settings /></Guard>} />
          <Route path="admin/billing" element={<Guard allow={isAdmin}><Billing /></Guard>} />
          <Route path="admin/audit" element={<Guard allow={isAdmin}><Audit /></Guard>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
