import { Outlet, NavLink, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { fetchHealthz } from "../../lib/api";
import { cn } from "./ui/utils";
import { PlaneTakeoff, ListChecks, PlusCircle, WifiOff } from "lucide-react";

function ModeBadge({ mode, isError }: { mode?: "live" | "mock"; isError: boolean }) {
  if (isError) {
    return (
      <span className="eyebrow inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-steel">
        <WifiOff size={11} aria-hidden="true" />
        Offline
      </span>
    );
  }
  if (!mode) return null;
  const live = mode === "live";
  return (
    <span
      className="eyebrow inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-ink"
      title={live ? "Connected to the live approval service" : "Connected backend is serving mock data"}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          live ? "bg-amber board-pulse" : "bg-steel"
        )}
        aria-hidden="true"
      />
      {live ? "Live" : "Mock"}
    </span>
  );
}

export function AppShell() {
  const { data: healthz, isError } = useQuery({
    queryKey: ["healthz"],
    queryFn: fetchHealthz,
    refetchInterval: 30_000,
    retry: 2,
  });

  const navigate = useNavigate();

  const tabClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      "eyebrow inline-flex h-14 -mb-px items-center gap-2 border-b-2 px-1 whitespace-nowrap transition-colors",
      isActive
        ? "border-amber text-ink"
        : "border-transparent text-steel hover:text-ink"
    );

  return (
    <div className="min-h-screen bg-paper text-ink flex flex-col">
      {/* Terminal header */}
      <header className="bg-white border-b border-line sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-4 sm:gap-7">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2.5 shrink-0 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber"
            aria-label="TravelDesk home"
          >
            <span className="flex items-center justify-center w-7 h-7 rounded-md bg-board">
              <PlaneTakeoff size={15} className="text-amber" aria-hidden="true" />
            </span>
            <span
              className="font-display text-ink tracking-tight"
              style={{ fontWeight: 600, fontSize: "1.05rem" }}
            >
              TravelDesk
            </span>
          </button>

          <nav className="flex items-center gap-5 sm:gap-6 flex-1" aria-label="Main navigation">
            <NavLink to="/" end className={tabClass}>
              <ListChecks size={14} aria-hidden="true" />
              <span className="hidden sm:inline">Claims Queue</span>
            </NavLink>
            <NavLink to="/submit" className={tabClass}>
              <PlusCircle size={14} aria-hidden="true" />
              <span className="hidden sm:inline">New Claim</span>
            </NavLink>
          </nav>

          <div className="shrink-0">
            <ModeBadge mode={healthz?.mode} isError={isError} />
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 sm:px-6 py-8">
        <Outlet />
      </main>

      <footer className="border-t border-line bg-white py-4">
        <p className="eyebrow text-center text-steel">
          TravelDesk · Travel Reimbursement Approval System
        </p>
      </footer>
    </div>
  );
}
