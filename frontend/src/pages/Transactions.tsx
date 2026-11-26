import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, type Assessment, type Dataset, type Summary, type Transaction } from "../api";
import { Button, Card, Field, inputClass, money, Note, Table, td, tdId, tdNum, when } from "../ui";

const EMPTY = { account_id: "", category: "", min_amount: "", max_amount: "", date_from: "", date_to: "" };

export default function Transactions({ datasetId, onPick }: { datasetId: string; onPick: (id: string) => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [filters, setFilters] = useState(EMPTY);
  const [view, setView] = useState<"all" | "flagged">("all");
  const [rows, setRows] = useState<Transaction[]>([]);
  const [flagged, setFlagged] = useState<Assessment[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [cursors, setCursors] = useState<(string | null)[]>([null]); // cursor of each page seen so far
  const [next, setNext] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => { api.datasets().then((d) => { setDatasets(d); if (!datasetId && d[0]) onPick(d[0].id); }, (e) => setError(errorText(e))); }, []);

  const query = { dataset_id: datasetId, ...filters, date_from: filters.date_from && `${filters.date_from}T00:00:00Z`, date_to: filters.date_to && `${filters.date_to}T23:59:59Z` };
  const page = cursors[cursors.length - 1];

  useEffect(() => {
    if (!datasetId) return;
    setError("");
    if (view === "all") {
      api.transactions({ ...query, limit: 50, cursor: page }).then((r) => { setRows(r.items); setNext(r.next_cursor); }, (e) => setError(errorText(e)));
    } else {
      api.flagged(datasetId, offset).then(setFlagged, (e) => setError(errorText(e)));
    }
  }, [datasetId, filters, view, page, offset]);

  useEffect(() => { if (datasetId) api.summary(query).then(setSummary, () => setSummary(null)); }, [datasetId, filters]);

  const apply = (e: FormEvent) => { e.preventDefault(); setCursors([null]); setFilters(form); };
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <>
      <Card title="Transactions" actions={
        <select aria-label="Dataset" className={inputClass} value={datasetId} onChange={(e) => { setCursors([null]); setOffset(0); onPick(e.target.value); }}>
          {datasets.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.row_count.toLocaleString()} rows)</option>)}
        </select>}>
        <form onSubmit={apply} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7 lg:items-end">
          <Field label="Account"><input id="f-account" className={inputClass} value={form.account_id} onChange={set("account_id")} placeholder="ACC-0001" /></Field>
          <Field label="Category"><input id="f-category" className={inputClass} value={form.category} onChange={set("category")} placeholder="travel" /></Field>
          <Field label="Min amount"><input id="f-min" className={inputClass} inputMode="decimal" value={form.min_amount} onChange={set("min_amount")} /></Field>
          <Field label="Max amount"><input id="f-max" className={inputClass} inputMode="decimal" value={form.max_amount} onChange={set("max_amount")} /></Field>
          <Field label="From"><input id="f-from" className={inputClass} type="date" value={form.date_from} onChange={set("date_from")} /></Field>
          <Field label="To"><input id="f-to" className={inputClass} type="date" value={form.date_to} onChange={set("date_to")} /></Field>
          <div className="flex gap-2"><Button type="submit">Apply</Button><Button type="button" kind="secondary" onClick={() => { setForm(EMPTY); setFilters(EMPTY); setCursors([null]); }}>Clear</Button></div>
        </form>
        {summary && summary.totals.length > 0 && (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {summary.totals.map((t) => [
              ["Transactions", Number(t.count).toLocaleString()], ["Total", money(t.total, t.currency)],
              ["Average", money(t.average, t.currency)], ["Largest", money(t.max, t.currency)],
            ].map(([k, v]) => (
              <div key={t.currency + k} className="rounded-md bg-slate-50 px-3 py-2 dark:bg-slate-950">
                <dt className="text-xs uppercase tracking-wide text-slate-500">{k}{summary.totals.length > 1 ? ` · ${t.currency}` : ""}</dt>
                <dd className="font-mono text-sm tabular-nums">{v}</dd>
              </div>
            )))}
          </dl>
        )}
      </Card>

      <Card title={view === "all" ? "All matching transactions" : "Flagged for review (highest risk first)"} actions={
        <div className="flex gap-1" role="group" aria-label="View">
          <Button kind={view === "all" ? "primary" : "secondary"} onClick={() => setView("all")}>All</Button>
          <Button kind={view === "flagged" ? "primary" : "secondary"} onClick={() => { setOffset(0); setView("flagged"); }}>Flagged</Button>
        </div>}>
        {error && <Note>{error}</Note>}
        {view === "all" ? (
          <>
            <Table head={["When", "Account", "Merchant", "Category", "Amount #"]} empty={rows.length ? undefined : "No transactions match."}>
              {rows.map((t) => (
                <tr key={t.id}><td className={td}>{when(t.occurred_at)}</td><td className={tdId}>{t.account_id}</td>
                  <td className={td}>{t.merchant}</td><td className={td}>{t.category}</td><td className={tdNum}>{money(t.amount, t.currency)}</td></tr>
              ))}
            </Table>
            <div className="mt-3 flex justify-between text-sm">
              <Button kind="secondary" disabled={cursors.length < 2} onClick={() => setCursors(cursors.slice(0, -1))}>← Newer</Button>
              <span className="self-center text-slate-500">Page {cursors.length}</span>
              <Button kind="secondary" disabled={!next} onClick={() => setCursors([...cursors, next])}>Older →</Button>
            </div>
          </>
        ) : (
          <>
            <Table head={["Risk #", "When", "Account", "Merchant", "Amount #", "Why it was flagged"]} empty={flagged.length ? undefined : "Nothing flagged. Score the dataset on the Datasets page first."}>
              {flagged.map((a) => (
                <tr key={a.transaction_id}><td className={tdNum}>{a.risk_score.toFixed(3)}</td><td className={td}>{when(a.occurred_at)}</td>
                  <td className={tdId}>{a.account_id}</td><td className={td}>{a.merchant}</td>
                  <td className={tdNum}>{money(a.amount, a.currency)}</td><td className={`${td} text-slate-600 dark:text-slate-400`}>{a.reasons.join("; ")}</td></tr>
              ))}
            </Table>
            <div className="mt-3 flex justify-between text-sm">
              <Button kind="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>← Previous</Button>
              <Button kind="secondary" disabled={flagged.length < 50} onClick={() => setOffset(offset + 50)}>Next →</Button>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
