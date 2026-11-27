import {
  BarChart3, Bell, Building2, CalendarClock, CalendarDays, CheckSquare, ClipboardCheck, ClipboardList, CreditCard, FileClock, FileWarning,
  Gauge, LayoutDashboard, LogOut, MapPin, Menu, Monitor, Moon, Network, Plane, Settings, ShieldCheck, Sun, User, Users, WifiOff, X,
} from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useGet } from "@/api/hooks";
import type { AppNotification } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown";
import { logout } from "@/features/session";
import { canSeeReports, isAdmin, isHR, isStaff, ROLE_LABEL } from "@/lib/roles";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { useQueueStore } from "@/stores/queue";
import { useUiStore } from "@/stores/ui";
import { Logo } from "./Logo";

interface Item { to: string; label: string; icon: ReactNode; end?: boolean }

function useNav(): { title: string; items: Item[] }[] {
  const me = useAuthStore((s) => s.me);
  const sections: { title: string; items: Item[] }[] = [];
  if (me?.employee_id) {
    sections.push({ title: "Me", items: [
      { to: "/app", label: "My dashboard", icon: <Gauge />, end: true },
      { to: "/app/attendance", label: "My attendance", icon: <ClipboardList /> },
      { to: "/app/schedule", label: "My schedule", icon: <CalendarDays /> },
      { to: "/app/reports", label: "My reports", icon: <BarChart3 /> },
      { to: "/app/leave", label: "Leave requests", icon: <Plane /> },
    ] });
  }
  if (me?.role === "MANAGER") {
    sections.push({ title: "Team", items: [
      { to: "/app/team", label: "Team dashboard", icon: <LayoutDashboard />, end: true },
      { to: "/app/team/attendance", label: "Team attendance", icon: <ClipboardCheck /> },
      { to: "/app/team/monitoring", label: "Monitoring", icon: <Monitor /> },
      { to: "/app/team/approvals", label: "Approvals", icon: <CheckSquare /> },
      { to: "/app/team/corrections", label: "Corrections", icon: <FileClock /> },
      { to: "/app/team/leave", label: "Leave requests", icon: <Plane /> },
      { to: "/app/team/reports", label: "Team reports", icon: <BarChart3 /> },
    ] });
  }
  if (isHR(me) || me?.role === "ACCOUNTANT") {
    const items: Item[] = [
      { to: "/app/admin", label: "Dashboard", icon: <LayoutDashboard />, end: true },
      { to: "/app/admin/attendance", label: "Attendance", icon: <ClipboardCheck /> },
    ];
    if (isStaff(me)) items.push({ to: "/app/admin/monitoring", label: "Monitoring", icon: <Monitor /> }, { to: "/app/admin/approvals", label: "Approvals", icon: <CheckSquare /> },
      { to: "/app/admin/corrections", label: "Corrections", icon: <FileClock /> }, { to: "/app/admin/anomalies", label: "Anomalies", icon: <FileWarning /> },
      { to: "/app/admin/leave", label: "Leave management", icon: <Plane /> });
    if (canSeeReports(me)) items.push({ to: "/app/admin/reports", label: "Reports", icon: <BarChart3 /> });
    sections.push({ title: "Organization", items });
    if (isHR(me)) {
      const ws: Item[] = [
        { to: "/app/admin/employees", label: "Employees", icon: <Users /> },
        { to: "/app/admin/departments", label: "Departments", icon: <Network /> },
        { to: "/app/admin/schedules", label: "Work schedules", icon: <CalendarClock /> },
      ];
      if (isAdmin(me)) ws.splice(2, 0, { to: "/app/admin/offices", label: "Offices & geofences", icon: <MapPin /> });
      if (isAdmin(me)) ws.push({ to: "/app/admin/settings", label: "Settings", icon: <Settings /> }, { to: "/app/admin/billing", label: "Billing", icon: <CreditCard /> },
        { to: "/app/admin/audit", label: "Audit log", icon: <ShieldCheck /> });
      sections.push({ title: "Workspace", items: ws });
    }
  }
  return sections;
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const sections = useNav();
  return (
    <nav className="space-y-5" aria-label="Main">
      {sections.map((s) => (
        <div key={s.title}>
          <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{s.title}</div>
          <div className="space-y-0.5">
            {s.items.map((i) => (
              <NavLink key={i.to} to={i.to} end={i.end} onClick={onNavigate}
                className={({ isActive }) => cn("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-4",
                  isActive && "bg-primary/10 text-accent-foreground dark:text-primary hover:bg-primary/15")}>
                {i.icon}{i.label}
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useUiStore();
  const next = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
  return (
    <Button variant="ghost" size="icon" aria-label={`Theme: ${theme}. Switch to ${next}`} title={`Theme: ${theme}`} onClick={() => setTheme(next)}>
      {theme === "dark" ? <Moon /> : theme === "light" ? <Sun /> : <Monitor />}
    </Button>
  );
}

export function NetworkIndicator() {
  const online = useUiStore((s) => s.online);
  const pending = useQueueStore((s) => s.pending.length);
  if (online && !pending) return null;
  return (
    <Badge tone={online ? "info" : "warning"} className="gap-1.5" aria-live="polite">
      {!online && <WifiOff />}
      {online ? `Syncing ${pending} pending` : pending ? `Offline · ${pending} pending` : "Offline"}
    </Badge>
  );
}

function Bellbutton() {
  const nav = useNavigate();
  const { data } = useGet<AppNotification[]>("/notifications/", { unread: true }, { refetchInterval: 60_000 });
  const n = data?.length ?? 0;
  return (
    <Button variant="ghost" size="icon" aria-label={`Notifications (${n} unread)`} onClick={() => nav("/app/notifications")} className="relative">
      <Bell />
      {n > 0 && <span className="absolute right-1 top-1 grid size-4 place-items-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">{n > 9 ? "9+" : n}</span>}
    </Button>
  );
}

function BottomNav() {
  const me = useAuthStore((s) => s.me);
  if (!me?.employee_id) return null;
  const items = [
    { to: "/app", label: "Home", icon: <Gauge />, end: true },
    { to: "/app/attendance", label: "History", icon: <ClipboardList /> },
    { to: "/app/schedule", label: "Schedule", icon: <CalendarDays /> },
    { to: "/app/profile", label: "Profile", icon: <User /> },
  ];
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label="Quick">
      {items.map((i) => (
        <NavLink key={i.to} to={i.to} end={i.end} className={({ isActive }) => cn("flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-muted-foreground [&_svg]:size-5", isActive && "text-primary")}>
          {i.icon}{i.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const me = useAuthStore((s) => s.me);
  const { sidebarOpen, setSidebarOpen } = useUiStore();
  const nav = useNavigate();
  const loc = useLocation();
  useEffect(() => setSidebarOpen(false), [loc.pathname, setSidebarOpen]);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[260px_1fr]">
      <aside className="hidden border-r bg-card lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col">
        <div className="flex h-16 items-center px-5"><Link to="/app"><Logo /></Link></div>
        <div className="flex-1 overflow-y-auto px-3 pb-6"><NavList /></div>
        <div className="border-t p-4 text-xs text-muted-foreground">
          <div className="truncate font-semibold text-foreground">{me?.organization_name}</div>
          <div>{me?.subscription_plan} plan · {me?.organization_timezone}</div>
        </div>
      </aside>

      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/40" onClick={() => setSidebarOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-card shadow-xl">
            <div className="flex h-16 items-center justify-between px-5"><Logo /><Button variant="ghost" size="icon" aria-label="Close menu" onClick={() => setSidebarOpen(false)}><X /></Button></div>
            <div className="flex-1 overflow-y-auto px-3 pb-6"><NavList onNavigate={() => setSidebarOpen(false)} /></div>
          </div>
        </div>
      )}

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b bg-card/85 px-4 backdrop-blur sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" onClick={() => setSidebarOpen(true)}><Menu /></Button>
          <div className="lg:hidden"><Logo compact /></div>
          <div className="ml-auto flex items-center gap-1.5">
            <NetworkIndicator />
            <ThemeToggle />
            <Bellbutton />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="ml-1 flex items-center gap-2 rounded-full p-0.5 pr-2 hover:bg-muted cursor-pointer" aria-label="Account menu">
                  <span className="grid size-8 place-items-center rounded-full bg-primary/15 text-sm font-bold text-primary">{me?.full_name.slice(0, 1)}</span>
                  <span className="hidden text-sm font-medium sm:block">{me?.full_name.split(" ")[0]}</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{me?.email}<br />{me && ROLE_LABEL[me.role]} · {me?.organization_name}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {me?.employee_id && <DropdownMenuItem onSelect={() => nav("/app/profile")}><User />Profile & location</DropdownMenuItem>}
                <DropdownMenuItem onSelect={() => nav("/app/notifications")}><Bell />Notifications</DropdownMenuItem>
                {isAdmin(me) && <DropdownMenuItem onSelect={() => nav("/app/admin/settings")}><Building2 />Organization settings</DropdownMenuItem>}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={async () => { await logout(); nav("/login"); }}><LogOut />Sign out</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl px-4 py-6 pb-24 sm:px-6 lg:pb-10"><Outlet /></main>
      </div>
      <BottomNav />
    </div>
  );
}
