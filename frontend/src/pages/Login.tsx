import { useState, type FormEvent } from "react";
import { api, errorText, type User } from "../api";
import { Button, Field, inputClass, Note } from "../ui";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { onLogin(await api.login(email, password)); }
    catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4 rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">FinSight <span className="text-teal-700 dark:text-teal-400">AI</span></h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to review transactions, policies and investigation reports.</p>
        </div>
        <Field label="Email"><input id="email" className={inputClass} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input id="password" className={inputClass} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {error && <Note>{error}</Note>}
        <Button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
      </form>
    </main>
  );
}
