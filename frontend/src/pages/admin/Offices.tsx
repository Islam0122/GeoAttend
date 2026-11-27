import { zodResolver } from "@hookform/resolvers/zod";
import { Crosshair, MapPin, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { useGet, useSend } from "@/api/hooks";
import type { Office } from "@/api/types";
import { GeoMap } from "@/components/GeoMap";
import { EmptyState, Field, PageHeader, QueryState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/misc";
import { fmtMeters } from "@/lib/format";
import { getPosition } from "@/lib/geo";
import { useAuthStore } from "@/stores/auth";
import { msg, t } from "@/i18n";

const schema = z.object({
  name: z.string().min(1, msg("Required")).max(160),
  address: z.string().max(300).optional(),
  latitude: z.coerce.number().min(-90).max(90),
  longitude: z.coerce.number().min(-180).max(180),
  timezone: z.string().min(1),
  radius: z.coerce.number().min(10, msg("Minimum 10 m")).max(5000, msg("Maximum 5000 m")),
  max_accuracy: z.coerce.number().gt(0).max(1000),
  enabled: z.boolean(),
  is_active: z.boolean(),
});
type Form = z.input<typeof schema>;
type Out = z.output<typeof schema>;

function OfficeDialog({ office, onClose }: { office: Office | null; onClose(): void }) {
  const tz = useAuthStore((s) => s.me!.organization_timezone);
  const { register, handleSubmit, control, setValue, watch, formState: { errors } } = useForm<Form, unknown, Out>({
    resolver: zodResolver(schema),
    defaultValues: office ? { name: office.name, address: office.address ?? "", latitude: office.latitude, longitude: office.longitude, timezone: office.timezone, radius: office.radius, max_accuracy: office.max_accuracy, enabled: office.geofence.enabled, is_active: office.is_active }
      : { name: "", address: "", latitude: 42.8746, longitude: 74.5698, timezone: tz, radius: 100, max_accuracy: 50, enabled: true, is_active: true },
  });
  const save = useSend<object>(office ? "PATCH" : "POST", office ? `/offices/${office.id}/` : "/offices/", ["/offices"], office ? t("Office updated") : t("Office created"));
  const fence = useSend<object>("PATCH", `/offices/${office?.id}/geofence/`, ["/offices"]);
  const [lat, lng, radius] = [Number(watch("latitude")), Number(watch("longitude")), Number(watch("radius"))];

  const submit = (v: Out) => {
    const { enabled, ...rest } = v;
    save.mutate(office ? rest : { ...rest, geofence: { enabled } }, {
      onSuccess: () => {
        if (office && enabled !== office.geofence.enabled) fence.mutate({ enabled });
        onClose();
      },
    });
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader><DialogTitle>{office ? t("Edit {name}", { name: office.name }) : t("New office")}</DialogTitle>
          <DialogDescription>{t("Click the map to place the office. The green circle is the geofence employees must be inside to check in.")}</DialogDescription></DialogHeader>
        <form className="grid gap-4 md:grid-cols-[1.2fr_1fr]" onSubmit={handleSubmit(submit)}>
          <div className="space-y-2">
            <GeoMap className="h-80" fences={Number.isFinite(lat) && Number.isFinite(lng) ? [{ id: "edit", name: watch("name") || t("Office"), lat, lng, radius: Number.isFinite(radius) ? radius : 100 }] : []}
              onPick={(la, lo) => { setValue("latitude", la, { shouldValidate: true }); setValue("longitude", lo, { shouldValidate: true }); }} />
            <Button type="button" variant="outline" size="sm" onClick={async () => {
              try { const f = await getPosition(); setValue("latitude", Number(f.latitude.toFixed(6))); setValue("longitude", Number(f.longitude.toFixed(6))); toast.success(t("Using your location (±{n} m)", { n: Math.round(f.accuracy) })); }
              catch (e) { toast.error((e as Error).message); }
            }}><Crosshair />{t("Use my current location")}</Button>
          </div>
          <div className="space-y-3">
            <Field label={t("Office name")} error={errors.name?.message}><Input {...register("name")} /></Field>
            <Field label={t("Address")}><Input {...register("address")} /></Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label={t("Latitude")} error={errors.latitude?.message}><Input type="number" step="0.000001" {...register("latitude")} /></Field>
              <Field label={t("Longitude")} error={errors.longitude?.message}><Input type="number" step="0.000001" {...register("longitude")} /></Field>
            </div>
            <Field label={t("Geofence radius: {n} m", { n: Number.isFinite(radius) ? radius : "—" })} error={errors.radius?.message}>
              <input type="range" min={20} max={1000} step={5} {...register("radius")} className="w-full accent-[var(--color-primary)]" />
            </Field>
            <Field label={t("Max acceptable GPS accuracy (m)")} error={errors.max_accuracy?.message} hint={t("Readings less precise than this are rejected with a retry prompt.")}><Input type="number" {...register("max_accuracy")} /></Field>
            <Field label={t("Timezone")}><Input {...register("timezone")} /></Field>
            <div className="flex items-center justify-between rounded-lg border p-3"><span className="text-sm">{t("Geofence enabled")}</span><Controller control={control} name="enabled" render={({ field }) => <Switch checked={field.value} onCheckedChange={field.onChange} />} /></div>
            <div className="flex items-center justify-between rounded-lg border p-3"><span className="text-sm">{t("Office active")}</span><Controller control={control} name="is_active" render={({ field }) => <Switch checked={field.value} onCheckedChange={field.onChange} />} /></div>
          </div>
          <DialogFooter className="md:col-span-2"><Button type="button" variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending}>{t("Save office")}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function GeofenceAdvanced({ office }: { office: Office }) {
  const g = office.geofence;
  const [v, setV] = useState({ required_consecutive: g.required_consecutive, stability_window_seconds: g.stability_window_seconds, entry_buffer_m: g.entry_buffer_m, exit_buffer_m: g.exit_buffer_m });
  const save = useSend<object>("PATCH", `/offices/${office.id}/geofence/`, ["/offices"], t("Geofence settings saved"));
  return (
    <div className="grid gap-2 sm:grid-cols-4">
      {([["required_consecutive", msg("Consecutive fixes")], ["stability_window_seconds", msg("Stability window (s)")], ["entry_buffer_m", msg("Entry buffer (m)")], ["exit_buffer_m", msg("Exit buffer (m)")]] as const).map(([k, l]) => (
        <Field key={k} label={t(l)}><Input type="number" value={v[k]} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} /></Field>
      ))}
      <div className="sm:col-span-4"><Button size="sm" variant="outline" onClick={() => save.mutate(v)}>{t("Save geofence settings")}</Button>
        <span className="ml-2 text-xs text-muted-foreground">{t("Used for passive presence checks while the attendance screen is open (hysteresis).")}</span></div>
    </div>
  );
}

export function Offices() {
  const q = useGet<Office[]>("/offices/");
  const [edit, setEdit] = useState<Office | null | "new">(null);
  const del = useSend<{ id: number }>("DELETE", (b) => `/offices/${b.id}/`, ["/offices"], t("Office deactivated"));
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <>
      <PageHeader title={t("Offices & geofences")} description={t("Each office has coordinates, a radius and a minimum GPS accuracy. Maps use OpenStreetMap (no Google Maps).")} actions={<Button onClick={() => setEdit("new")}><Plus />{t("New office")}</Button>} />
      <QueryState isLoading={q.isLoading} error={q.error}>
        {q.data?.length ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {q.data.map((o) => (
              <Card key={o.id}>
                <CardHeader className="flex-row items-start justify-between">
                  <div><CardTitle className="flex items-center gap-2"><MapPin className="size-4 text-primary" />{o.name}</CardTitle>
                    <div className="mt-1 text-xs text-muted-foreground">{o.address || `${o.latitude.toFixed(5)}, ${o.longitude.toFixed(5)}`} · {o.timezone}</div></div>
                  <div className="flex gap-1">
                    {!o.is_active ? <Badge>{t("Inactive")}</Badge> : o.geofence.enabled ? <Badge tone="success">{t("Geofence on")}</Badge> : <Badge tone="warning">{t("Geofence off")}</Badge>}
                    <Button size="icon" variant="ghost" aria-label={t("Edit {name}", { name: o.name })} onClick={() => setEdit(o)}><Pencil /></Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <GeoMap className="h-48" fences={[{ id: o.id, name: o.name, lat: o.latitude, lng: o.longitude, radius: o.radius, active: o.is_active && o.geofence.enabled }]} />
                  <div className="flex flex-wrap gap-4 text-sm"><span>{t("Radius")} <b>{fmtMeters(o.radius)}</b></span><span>{t("Max accuracy")} <b>{fmtMeters(o.max_accuracy, true)}</b></span><span>{t("Employees")} <b>{o.employee_ids.length}</b></span></div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => setExpanded(expanded === o.id ? null : o.id)}>{t("Geofence settings")}</Button>
                    {o.is_active && <Button size="sm" variant="ghost" onClick={() => confirm(t("Deactivate {name}?", { name: o.name })) && del.mutate({ id: o.id })}>{t("Deactivate")}</Button>}
                  </div>
                  {expanded === o.id && <GeofenceAdvanced office={o} />}
                </CardContent>
              </Card>
            ))}
          </div>
        ) : <Card><EmptyState title={t("No offices yet")}>{t("Create an office and draw its geofence to enable GPS check-in.")}</EmptyState></Card>}
      </QueryState>
      {edit && <OfficeDialog office={edit === "new" ? null : edit} onClose={() => setEdit(null)} />}
    </>
  );
}
