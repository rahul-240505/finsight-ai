import { useCallback, useEffect, useState } from "react";
import { api, type User } from "./api";
import Datasets from "./pages/Datasets";
import Investigations from "./pages/Investigations";
import Login from "./pages/Login";
import Policies from "./pages/Policies";
import Transactions from "./pages/Transactions";
import { Button } from "./ui";

const PAGES = [
  { id: "datasets", label: "Datasets" },
  { id: "transactions", label: "Transactions" },
  { id: "policies", label: "Policy Q&A" },
  { id: "investigations", label: "Investigations" },
] as const;
type PageId = (typeof PAGES)[number]["id"];

function readHash(): { page: PageId; param: string } {
  const [page, param = ""] = location.hash.slice(1).split("/");
  return { page: (PAGES.some((p) => p.id === page) ? page : "datasets") as PageId, param };
}

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [route, setRoute] = useState(readHash);

  useEffect(() => {
    api.me().then(setUser, () => setUser(null));
    const onHash = () => setRoute(readHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((page: PageId, param = "") => { location.hash = param ? `${page}/${param}` : page; }, []);

  if (user === undefined) return <p className="p-8 text-sm text-slate-500">Loading…</p>;
  if (user === null) return <Login onLogin={setUser} />;

  const signOut = async () => { await api.logout().catch(() => undefined); setUser(null); };

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="font-semibold tracking-tight">FinSight <span className="text-teal-700 dark:text-teal-400">AI</span></span>
          <nav className="flex flex-wrap gap-1" aria-label="Main">
            {PAGES.map((p) => (
              <a key={p.id} href={`#${p.id}`} aria-current={route.page === p.id ? "page" : undefined}
                className={`rounded-md px-3 py-1.5 text-sm ${route.page === p.id ? "bg-teal-50 font-medium text-teal-800 dark:bg-teal-950 dark:text-teal-300" : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}>
                {p.label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-slate-500">{user.email} · <span className="font-mono text-xs uppercase">{user.role}</span></span>
            <Button kind="secondary" onClick={signOut}>Sign out</Button>
          </div>
        </div>
      </header>
      <p className="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-center text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
        Scores and reports flag unusual activity for human review. They are not a finding of fraud.
      </p>
      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
        {route.page === "datasets" && <Datasets user={user} onOpen={(id) => go("transactions", id)} />}
        {route.page === "transactions" && <Transactions datasetId={route.param} onPick={(id) => go("transactions", id)} />}
        {route.page === "policies" && <Policies user={user} />}
        {route.page === "investigations" && <Investigations user={user} reportId={route.param} onOpen={(id) => go("investigations", id)} />}
      </main>
    </div>
  );
}
