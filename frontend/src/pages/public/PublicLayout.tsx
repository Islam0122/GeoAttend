import { Link, Outlet } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";

export function PublicLayout() {
  const me = useAuthStore((s) => s.me);
  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link to="/"><Logo /></Link>
          <nav className="hidden gap-5 text-sm font-medium text-muted-foreground sm:flex">
            <a href="/#features" className="hover:text-foreground">Features</a><Link to="/pricing" className="hover:text-foreground">Pricing</Link><a href="/#privacy" className="hover:text-foreground">Privacy</a>
          </nav>
          <div className="ml-auto flex gap-2">
            {me ? <Button asChild><Link to="/app">Open app</Link></Button> : <><Button variant="ghost" asChild><Link to="/login">Sign in</Link></Button><Button asChild><Link to="/register">Start free</Link></Button></>}
          </div>
        </div>
      </header>
      <Outlet />
      <footer className="border-t py-8 text-center text-sm text-muted-foreground">© {new Date().getFullYear()} GeoAttend · Maps © OpenStreetMap contributors</footer>
    </div>
  );
}
