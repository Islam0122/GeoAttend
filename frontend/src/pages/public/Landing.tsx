import { BarChart3, Building2, CheckCircle2, Clock4, Fingerprint, GraduationCap, LockKeyhole, MapPinned, ShieldCheck, Smartphone, Store, WifiOff } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { msg, t } from "@/i18n";

const FEATURES = [
  { icon: <MapPinned />, title: msg("Server-verified geofencing"), text: msg("Browser GPS is re-checked on the server with a conservative accuracy rule. Distance is never trusted from the client.") },
  { icon: <Clock4 />, title: msg("Automatic calculations"), text: msg("Late minutes, early leave, breaks, overtime and multi-session days computed in each office's timezone.") },
  { icon: <Smartphone />, title: msg("Installable PWA"), text: msg("Employees check in from any phone browser. Offline check-ins queue safely and are validated once back online.") },
  { icon: <ShieldCheck />, title: msg("Approvals & corrections"), text: msg("Automatic, employee-confirmed or manager-approved attendance, with disputes and audit-logged corrections.") },
  { icon: <BarChart3 />, title: msg("Live analytics"), text: msg("Dashboards, trends, department performance, late arrivals, absences and overtime with CSV export.") },
  { icon: <Fingerprint />, title: msg("Multi-tenant & secure"), text: msg("Strict workspace isolation, role-based access, refresh-token rotation, Google sign-in and rate limiting.") },
];

export function Landing() {
  return (
    <main>
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(60%_50%_at_70%_0%,color-mix(in_oklab,var(--color-primary)_18%,transparent),transparent)]" />
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 md:grid-cols-[1.1fr_1fr] md:py-24">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs font-semibold text-muted-foreground"><span className="size-1.5 rounded-full bg-primary" />{t("GPS attendance for IT, schools and growing businesses")}</div>
            <h1 className="text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-5xl">{t("Attendance your team can trust —")} <span className="text-primary">{t("verified at the door.")}</span></h1>
            <p className="mt-5 max-w-xl text-lg text-muted-foreground">{t("Employees tap Check in on their phone. GeoAttend checks they're really inside the office geofence, records the time and does the payroll math. No hardware, no hidden tracking.")}</p>
            <div className="mt-8 flex flex-wrap gap-3"><Button size="lg" asChild><Link to="/register">{t("Create your workspace")}</Link></Button><Button size="lg" variant="outline" asChild><Link to="/pricing">{t("See pricing")}</Link></Button></div>
            <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">{[t("Free for 10 employees"), t("No Google Maps API key"), t("Works in any modern browser")].map((x) => <span key={x} className="flex items-center gap-1.5"><CheckCircle2 className="size-4 text-primary" />{x}</span>)}</div>
          </div>
          <Card className="mx-auto w-full max-w-sm p-5 shadow-xl">
            <div className="text-sm text-muted-foreground">{t("Good morning")}, Aigerim!</div>
            <div className="mt-1 text-lg font-bold">{t("Your shift starts at {time}", { time: "09:00" })}</div>
            <div className="mt-4 rounded-lg border border-primary/30 bg-primary/8 p-3 text-sm font-semibold text-accent-foreground dark:text-primary">✓ {t("You're inside the office zone")}</div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
              {[[t("GPS accuracy"), t("±{n} m", { n: 12 })], [t("Distance"), t("{n} m", { n: 35 })], [t("Radius"), t("{n} m", { n: 100 })]].map(([l, v]) => <div key={l} className="rounded-lg border bg-surface p-2"><div className="text-muted-foreground">{l}</div><div className="mt-0.5 text-sm font-bold">{v}</div></div>)}
            </div>
            <div className="mt-4 grid h-14 place-items-center rounded-xl bg-primary text-lg font-bold text-primary-foreground">{t("Check in")}</div>
            <div className="mt-3 text-center text-xs text-muted-foreground">{t("Office: {name} · verified by server", { name: "Bishkek HQ" })}</div>
          </Card>
        </div>
      </section>
      <section id="features" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-3xl font-bold tracking-tight">{t("Everything attendance needs. Nothing it doesn't.")}</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => <Card key={f.title} className="p-5"><div className="mb-3 inline-flex rounded-lg bg-primary/12 p-2 text-primary [&_svg]:size-5">{f.icon}</div><div className="font-semibold">{t(f.title)}</div><p className="mt-1 text-sm text-muted-foreground">{t(f.text)}</p></Card>)}
        </div>
      </section>
      <section className="border-y bg-card">
        <div className="mx-auto grid max-w-6xl gap-6 px-4 py-12 sm:grid-cols-3 sm:px-6">
          {[{ i: <Building2 />, t: t("IT & enterprises"), d: t("Multiple offices, departments, manager approvals.") }, { i: <GraduationCap />, t: t("Education"), d: t("Staff shifts across campuses with per-site timezones.") }, { i: <Store />, t: t("Small businesses"), d: t("Set up in minutes. Free up to 10 people.") }]
            .map((x) => <div key={x.t} className="flex gap-3"><div className="text-primary [&_svg]:size-6">{x.i}</div><div><div className="font-semibold">{x.t}</div><div className="text-sm text-muted-foreground">{x.d}</div></div></div>)}
        </div>
      </section>
      <section id="privacy" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="grid gap-8 md:grid-cols-2">
          <div><h2 className="text-3xl font-bold tracking-tight">{t("Honest about location.")}</h2>
            <p className="mt-3 text-muted-foreground">{t("GeoAttend is a web app. It reads location only when an employee presses Check in / Check out, or while they keep the attendance screen open during a work session — always with a visible indicator and recorded consent.")}</p></div>
          <ul className="space-y-3 text-sm">
            {[[<LockKeyhole key="a" />, t("No hidden or background tracking — browsers can't do it reliably and we don't try.")], [<ShieldCheck key="b" />, t("Managers see inside/outside and distance, never a movement trail.")], [<WifiOff key="c" />, t("Offline check-ins stay pending until the server validates them.")], [<Clock4 key="d" />, t("Raw coordinates are deleted automatically after your retention period.")]]
              .map(([i, t], k) => <li key={k} className="flex gap-3"><span className="text-primary [&_svg]:size-5">{i}</span>{t}</li>)}
          </ul>
        </div>
      </section>
    </main>
  );
}
