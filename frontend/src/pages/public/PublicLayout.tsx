import { Link, Outlet } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { LanguageSwitcher } from "@/components/layout/LanguageSwitcher";
import { t } from "@/i18n";

export function PublicLayout() {
  const me = useAuthStore((s) => s.me);
  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link to="/"><Logo /></Link>
          <nav className="hidden gap-5 text-sm font-medium text-muted-foreground sm:flex">
            <a href="/#features" className="hover:text-foreground">{t("Features")}</a><Link to="/pricing" className="hover:text-foreground">{t("Pricing")}</Link><a href="/#privacy" className="hover:text-foreground">{t("Privacy")}</a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <LanguageSwitcher />
            {me ? <Button asChild><Link to="/app">{t("Open app")}</Link></Button> : <><Button variant="ghost" asChild><Link to="/login">{t("Sign in")}</Link></Button><Button asChild><Link to="/register">{t("Start free")}</Link></Button></>}
          </div>
        </div>
      </header>
      <Outlet />
      <footer className="border-t py-8 text-center text-sm text-muted-foreground">© {new Date().getFullYear()} GeoAttend · {t("Maps © OpenStreetMap contributors")}</footer>
    </div>
  );
}
