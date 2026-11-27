import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { api } from "@/api/client";
import type { TokenPair } from "@/api/types";
import { Field, Spinner } from "@/components/common";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { acceptTokens, googleEnabled, readGoogleCallback, startGoogleSignIn } from "@/features/session";
import { homeFor } from "@/lib/roles";

function Shell({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-[radial-gradient(80%_60%_at_50%_0%,color-mix(in_oklab,var(--color-primary)_14%,transparent),transparent)] px-4 py-10">
      <Card className="w-full max-w-md p-7 shadow-lg">
        <Link to="/" className="mb-6 inline-block"><Logo /></Link>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        <p className="mb-6 mt-1 text-sm text-muted-foreground">{sub}</p>
        {children}
      </Card>
    </div>
  );
}

function GoogleButton({ intent, extra }: { intent: "login" | "register"; extra?: () => Record<string, string> | null }) {
  if (!googleEnabled) return null;
  return (
    <>
      <div className="my-4 flex items-center gap-3 text-xs text-muted-foreground"><div className="h-px flex-1 bg-border" />or<div className="h-px flex-1 bg-border" /></div>
      <Button type="button" variant="outline" className="w-full" onClick={() => { const x = extra ? extra() : {}; if (x) startGoogleSignIn(intent, x); }}>
        <svg viewBox="0 0 24 24" className="size-4" aria-hidden><path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.6 3.9-5.5 3.9-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.3 14.6 2.3 12 2.3 6.6 2.3 2.3 6.6 2.3 12s4.3 9.7 9.7 9.7c5.6 0 9.3-3.9 9.3-9.5 0-.6-.1-1.1-.2-1.6H12z" /></svg>
        Continue with Google
      </Button>
    </>
  );
}

const loginSchema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });

export function Login() {
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const [err, setErr] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });
  return (
    <Shell title="Sign in" sub="Welcome back to your workspace.">
      {err && <Alert tone="danger" className="mb-4">{err}</Alert>}
      <form className="space-y-4" onSubmit={handleSubmit(async (v) => {
        setErr(null);
        try { const me = await acceptTokens(await api<TokenPair>("/auth/login/", { body: v })); if (me) nav(from ?? homeFor(me), { replace: true }); }
        catch (e) { setErr((e as Error).message); }
      })}>
        <Field label="Work email" error={errors.email?.message}><Input type="email" autoComplete="username" {...register("email")} /></Field>
        <Field label="Password" error={errors.password?.message}><Input type="password" autoComplete="current-password" {...register("password")} /></Field>
        <Button type="submit" className="w-full" disabled={isSubmitting}>{isSubmitting && <Spinner />}Sign in</Button>
      </form>
      <GoogleButton intent="login" />
      <p className="mt-6 text-center text-sm text-muted-foreground">New company? <Link className="font-semibold text-primary" to="/register">Create a workspace</Link></p>
    </Shell>
  );
}

const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
// Chrome's list omits "UTC"; always include it and the browser's own zone so the default is selectable.
const ZONES: string[] = (() => {
  let list: string[] = [];
  try { list = (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone"); } catch { /* old browser */ }
  return Array.from(new Set(["UTC", BROWSER_TZ, ...list]));
})();
const regSchema = z.object({
  company_name: z.string().min(2, "Company name is required"),
  company_type: z.enum(["IT", "EDUCATION", "SMALL_BUSINESS", "MEDIUM_BUSINESS", "ENTERPRISE", "OTHER"]),
  timezone: z.string().min(1),
  full_name: z.string().min(2, "Your name is required"),
  email: z.string().email("Enter a valid email"),
  password: z.string().min(10, "At least 10 characters"),
});
type Reg = z.infer<typeof regSchema>;

export function Register() {
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const { register, handleSubmit, getValues, trigger, formState: { errors, isSubmitting } } = useForm<Reg>({
    resolver: zodResolver(regSchema), defaultValues: { company_type: "IT", timezone: BROWSER_TZ },
  });
  return (
    <Shell title="Create your workspace" sub="You'll be the owner. Invite your team next.">
      {err && <Alert tone="danger" className="mb-4">{err}</Alert>}
      <form className="space-y-3" onSubmit={handleSubmit(async (v) => {
        setErr(null);
        try { const me = await acceptTokens(await api<TokenPair>("/auth/register/", { body: v })); if (me) nav("/app/admin/offices", { replace: true }); }
        catch (e) { setErr((e as Error).message); }
      })}>
        <Field label="Company name" error={errors.company_name?.message}><Input {...register("company_name")} /></Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Company type"><NativeSelect {...register("company_type")}>
            <option value="IT">IT company</option><option value="EDUCATION">Educational institution</option><option value="SMALL_BUSINESS">Small business</option><option value="MEDIUM_BUSINESS">Medium business</option><option value="ENTERPRISE">Large enterprise</option><option value="OTHER">Other</option>
          </NativeSelect></Field>
          <Field label="Timezone"><NativeSelect {...register("timezone")}>{ZONES.map((z) => <option key={z}>{z}</option>)}</NativeSelect></Field>
        </div>
        <Field label="Your name" error={errors.full_name?.message}><Input autoComplete="name" {...register("full_name")} /></Field>
        <Field label="Work email" error={errors.email?.message}><Input type="email" autoComplete="email" {...register("email")} /></Field>
        <Field label="Password" error={errors.password?.message}><Input type="password" autoComplete="new-password" {...register("password")} /></Field>
        <Button type="submit" className="w-full" disabled={isSubmitting}>{isSubmitting && <Spinner />}Create workspace</Button>
      </form>
      <GoogleButton intent="register" extra={() => {
        void trigger(["company_name"]);
        const v = getValues();
        if (!v.company_name || v.company_name.length < 2) { setErr("Enter your company name first, then continue with Google."); return null; }
        return { company_name: v.company_name, company_type: v.company_type, timezone: v.timezone };
      }} />
      <p className="mt-6 text-center text-sm text-muted-foreground">Already have an account? <Link className="font-semibold text-primary" to="/login">Sign in</Link></p>
    </Shell>
  );
}

export function GoogleCallback() {
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const [needsCompany, setNeedsCompany] = useState<{ idToken: string; nonce: string } | null>(null);
  const [company, setCompany] = useState("");
  const finish = async (body: object) => {
    const me = await acceptTokens(await api<TokenPair>("/auth/google/", { body }));
    if (me) nav(homeFor(me), { replace: true });
  };
  useEffect(() => {
    (async () => {
      try {
        const cb = readGoogleCallback(window.location.hash);
        history.replaceState(null, "", window.location.pathname); // drop the token from the URL
        try { await finish({ id_token: cb.idToken, nonce: cb.nonce, ...cb.extra }); }
        catch (e) {
          const code = (e as { code?: string }).code;
          if (code === "GOOGLE_ACCOUNT_NOT_FOUND") setNeedsCompany({ idToken: cb.idToken, nonce: cb.nonce });
          else throw e;
        }
      } catch (e) { setErr((e as Error).message); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <Shell title="Signing in with Google" sub="Verifying your Google account on the server…">
      {err ? <><Alert tone="danger">{err}</Alert><Button className="mt-4" variant="outline" asChild><Link to="/login">Back to sign in</Link></Button></> : needsCompany ? (
        <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); try { await finish({ id_token: needsCompany.idToken, nonce: needsCompany.nonce, company_name: company, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" }); } catch (x) { setErr((x as Error).message); } }}>
          <Alert tone="info">No workspace exists for this Google account yet. Create one:</Alert>
          <Field label="Company name"><Input value={company} onChange={(e) => setCompany(e.target.value)} minLength={2} required /></Field>
          <Button type="submit" className="w-full">Create workspace</Button>
        </form>
      ) : <div className="flex justify-center py-6"><Spinner className="size-6" /></div>}
    </Shell>
  );
}

export function AcceptInvite() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [err, setErr] = useState<string | null>(null);
  const schema = z.object({ password: z.string().min(10, "At least 10 characters"), confirm: z.string() }).refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  return (
    <Shell title="Join your team" sub="Choose a password to activate your account, or continue with Google using the invited email.">
      {err && <Alert tone="danger" className="mb-4">{err}</Alert>}
      <form className="space-y-4" onSubmit={handleSubmit(async (v) => {
        try { const me = await acceptTokens(await api<TokenPair>("/auth/accept-invite/", { body: { token: params.get("token"), password: v.password } })); if (me) nav(homeFor(me), { replace: true }); }
        catch (e) { setErr((e as Error).message); }
      })}>
        <Field label="New password" error={errors.password?.message}><Input type="password" autoComplete="new-password" {...register("password")} /></Field>
        <Field label="Confirm password" error={errors.confirm?.message}><Input type="password" autoComplete="new-password" {...register("confirm")} /></Field>
        <Button type="submit" className="w-full" disabled={isSubmitting}>Activate account</Button>
      </form>
      <GoogleButton intent="login" />
    </Shell>
  );
}
