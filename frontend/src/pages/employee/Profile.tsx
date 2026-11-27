import { zodResolver } from "@hookform/resolvers/zod";
import { Download, MapPin, ShieldCheck, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useGet, useSend } from "@/api/hooks";
import type { Consent } from "@/api/types";
import { Field, PageHeader } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { browserLabel, deviceId } from "@/lib/device";
import { fmtDateTime } from "@/lib/format";
import { queryPermission, type PermissionState } from "@/lib/geo";
import { ROLE_LABEL } from "@/lib/roles";
import { useAuthStore } from "@/stores/auth";
import { useInstallPrompt } from "@/features/pwa";

const pw = z.object({ current_password: z.string(), new_password: z.string().min(10, "At least 10 characters"), confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });

interface Device { id: number; device_id: string; platform: string; model: string | null; location_permission: string; last_seen_at: string | null; is_active: boolean }

export function Profile() {
  const me = useAuthStore((s) => s.me)!;
  const [perm, setPerm] = useState<PermissionState>("unknown");
  const consent = useGet<Consent>(me.employee_id ? "/consent/me/" : null);
  const devices = useGet<Device[]>(me.employee_id ? "/devices/me/" : null);
  const setConsent = useSend<{ granted: boolean; consent_version: string }>("POST", "/consent/", ["/consent", "/attendance/today"], "Consent updated");
  const changePw = useSend<object>("POST", "/auth/change-password/", [], "Password changed — please sign in again");
  const form = useForm<z.infer<typeof pw>>({ resolver: zodResolver(pw) });
  const install = useInstallPrompt();
  useEffect(() => void queryPermission().then(setPerm), []);

  return (
    <>
      <PageHeader title="Profile" description={`${me.full_name} · ${me.email} · ${ROLE_LABEL[me.role]} at ${me.organization_name}`} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><MapPin className="size-5 text-primary" />Location permission status</CardTitle>
            <CardDescription>What this browser allows, and what you agreed to.</CardDescription></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between"><span>Browser permission</span>
              <Badge tone={perm === "granted" ? "success" : perm === "denied" ? "danger" : "neutral"}>{perm === "prompt" ? "Will ask" : perm}</Badge></div>
            <div className="flex justify-between"><span>Secure context (HTTPS)</span><Badge tone={window.isSecureContext ? "success" : "danger"}>{window.isSecureContext ? "Yes" : "No"}</Badge></div>
            <div className="flex justify-between"><span>Attendance consent</span>
              <Badge tone={consent.data?.granted ? "success" : "warning"}>{consent.data?.granted ? `Given ${fmtDateTime(consent.data.updated_at)}` : "Not given"}</Badge></div>
            <div className="flex justify-between"><span>Background tracking</span><Badge tone="neutral">Never (web app)</Badge></div>
            {perm === "denied" && <Alert tone="warning" title="Location is blocked">Open your browser's site settings for this page and allow Location, then reload.</Alert>}
            <p className="text-muted-foreground">{consent.data?.policy_text}</p>
            {consent.data && (consent.data.granted
              ? <Button variant="outline" onClick={() => setConsent.mutate({ granted: false, consent_version: consent.data!.required_version })}>Withdraw consent</Button>
              : <Button onClick={() => setConsent.mutate({ granted: true, consent_version: consent.data!.required_version })}>Give consent</Button>)}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Smartphone className="size-5 text-primary" />Install the app</CardTitle>
            <CardDescription>GeoAttend works as an installable web app (PWA).</CardDescription></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {install.installed ? <Alert tone="success" title="Installed">You're using the installed app.</Alert> : install.canPrompt ? (
              <Button onClick={install.prompt}><Download />Install GeoAttend</Button>
            ) : (
              <ul className="space-y-1.5 text-muted-foreground">
                <li><b className="text-foreground">Android / Chrome:</b> menu ⋮ → <i>Install app</i> or <i>Add to Home screen</i>.</li>
                <li><b className="text-foreground">iPhone / Safari:</b> Share → <i>Add to Home Screen</i>.</li>
                <li><b className="text-foreground">Desktop Chrome / Edge:</b> install icon in the address bar.</li>
              </ul>
            )}
            <Alert tone="info" title="What the app can and cannot do">Installing adds an icon and offline check-in queueing. It does <b>not</b> enable background GPS: location is read only while the app is open.</Alert>
            <div className="text-xs text-muted-foreground">This device: {browserLabel()} · {deviceId().slice(0, 18)}…</div>
            {devices.data && devices.data.length > 0 && (
              <div className="space-y-1">{devices.data.map((d) => <div key={d.id} className="flex justify-between text-xs"><span>{d.model ?? d.platform}</span><span className="text-muted-foreground">{d.is_active ? "active" : "inactive"} · last seen {fmtDateTime(d.last_seen_at)}</span></div>)}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-5 text-primary" />Password</CardTitle>
            <CardDescription>{me.google_linked ? "Your account is linked with Google." : "Changing your password signs you out everywhere."}</CardDescription></CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={form.handleSubmit((v) => changePw.mutate({ current_password: v.current_password, new_password: v.new_password }))}>
              {me.has_password && <Field label="Current password"><Input type="password" autoComplete="current-password" {...form.register("current_password")} /></Field>}
              <Field label="New password" error={form.formState.errors.new_password?.message}><Input type="password" autoComplete="new-password" {...form.register("new_password")} /></Field>
              <Field label="Confirm new password" error={form.formState.errors.confirm?.message}><Input type="password" autoComplete="new-password" {...form.register("confirm")} /></Field>
              <Button type="submit" disabled={changePw.isPending}>{me.has_password ? "Change password" : "Set password"}</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
