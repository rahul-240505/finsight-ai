import type { ButtonHTMLAttributes, ReactNode } from "react";

export const money = (amount: string, currency: string) =>
  `${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
export const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export function Button({ kind = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary: "bg-teal-700 text-white hover:bg-teal-800 dark:bg-teal-600 dark:hover:bg-teal-500",
    secondary: "border border-slate-300 bg-white text-slate-800 hover:border-teal-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
    danger: "border border-amber-600 bg-white text-amber-800 hover:bg-amber-50 dark:bg-slate-900 dark:text-amber-300",
  }[kind];
  return <button className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`} {...props} />;
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold">{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-700 dark:text-slate-300">{label}</span>
      {children}
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const fileClass =
  "text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-200 dark:file:bg-slate-800 dark:file:text-slate-100";

export const inputClass =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100";

const pill: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  ready: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  answered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  rejected: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  flagged: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  submitted: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-300",
  running: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-300",
};

export function Status({ value }: { value: string }) {
  return <span className={`rounded px-2 py-0.5 font-mono text-xs uppercase tracking-wide ${pill[value] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"}`}>{value}</span>;
}

export function Note({ kind = "error", children }: { kind?: "error" | "info"; children: ReactNode }) {
  const style = kind === "error"
    ? "border-amber-500 bg-amber-50 text-amber-950 dark:bg-amber-950/40 dark:text-amber-200"
    : "border-teal-600 bg-teal-50 text-teal-950 dark:bg-teal-950/40 dark:text-teal-200";
  return <div role={kind === "error" ? "alert" : "status"} className={`rounded-r-md border-l-4 px-3 py-2 text-sm ${style}`}>{children}</div>;
}

/** Header labels ending in " #" are numeric columns: right-aligned like their cells. */
export function Table({ head, children, empty }: { head: string[]; children: ReactNode; empty?: string }) {
  return (
    <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950">
          <tr>{head.map((h, i) => <th key={i} className={`px-3 py-2 font-medium ${h.endsWith(" #") ? "text-right" : ""}`}>{h.replace(/ #$/, "")}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">{children}</tbody>
      </table>
      {empty && <p className="px-3 py-6 text-center text-sm text-slate-500">{empty}</p>}
    </div>
  );
}

export const td = "px-3 py-2 align-top";
export const tdId = "px-3 py-2 align-top font-mono text-xs whitespace-nowrap";
export const tdNum = "px-3 py-2 text-right align-top font-mono tabular-nums whitespace-nowrap";
