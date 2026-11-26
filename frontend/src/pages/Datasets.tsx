import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, waitForJob, type Dataset, type Job, type User } from "../api";
import { Button, Card, Field, fileClass, inputClass, Note, Status, Table, td, tdNum, when } from "../ui";

type RowError = { line: number; column: string | null; message: string };

export default function Datasets({ user, onOpen }: { user: User; onOpen: (id: string) => void }) {
  const [items, setItems] = useState<Dataset[]>([]);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [scoring, setScoring] = useState<Record<string, string>>({});
  const canWrite = user.role !== "viewer";

  const load = () => api.datasets().then(setItems, (e) => setError(errorText(e)));
  useEffect(() => { load(); }, []);

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setError("");
    try {
      const started = await api.uploadDataset(file, name || file.name.replace(/\.csv$/i, ""));
      setJob(await waitForJob(started.id, setJob));
      load();
    } catch (err) { setError(errorText(err)); }
  };

  const score = async (id: string) => {
    setScoring((s) => ({ ...s, [id]: "queued" }));
    try {
      const done = await waitForJob((await api.score(id)).id, (j) => setScoring((s) => ({ ...s, [id]: j.status })));
      const r = done.result as { flagged?: number; scored?: number } | null;
      setScoring((s) => ({ ...s, [id]: done.status === "succeeded" ? `${r?.flagged ?? "?"} flagged of ${r?.scored ?? "?"}` : done.error?.message ?? "failed" }));
    } catch (err) { setScoring((s) => ({ ...s, [id]: errorText(err) })); }
  };

  const rowErrors = (job?.error?.errors as RowError[] | undefined) ?? [];
  return (
    <>
      {canWrite && (
        <Card title="Import transactions">
          <form onSubmit={upload} className="flex flex-wrap items-end gap-4">
            <Field label="CSV file" hint="Columns: transaction_id, account_id, timestamp, amount, currency, merchant, category">
              <input id="csv-file" type="file" accept=".csv,text/csv" required className={fileClass} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Field>
            <Field label="Dataset name"><input id="dataset-name" className={inputClass} value={name} placeholder={file?.name ?? "e.g. March export"} onChange={(e) => setName(e.target.value)} /></Field>
            <Button type="submit" disabled={!file || job?.status === "queued" || job?.status === "running"}>Import</Button>
          </form>
          {job && (
            <div className="mt-4 flex flex-col gap-2 text-sm">
              <p className="flex items-center gap-2">Import job <Status value={job.status} />
                {job.status === "succeeded" && <span>{String(job.result?.row_count ?? "")} rows saved.</span>}</p>
              {job.error && <Note>{job.error.message}</Note>}
              {rowErrors.length > 0 && (
                <ul className="max-h-48 overflow-y-auto rounded-md border border-slate-200 p-2 font-mono text-xs dark:border-slate-800">
                  {rowErrors.map((r, i) => <li key={i}>line {r.line} · {r.column ?? "row"}: {r.message}</li>)}
                </ul>
              )}
            </div>
          )}
        </Card>
      )}
      <Card title="Your datasets">
        {error && <Note>{error}</Note>}
        <Table head={["Name", "Rows #", "Imported", "Risk scoring", ""]} empty={items.length ? undefined : "No datasets yet. Import a CSV to start."}>
          {items.map((d) => (
            <tr key={d.id}>
              <td className={td}><button className="font-medium text-teal-800 hover:underline dark:text-teal-300" onClick={() => onOpen(d.id)}>{d.name}</button></td>
              <td className={tdNum}>{d.row_count.toLocaleString()}</td>
              <td className={td}>{when(d.created_at)}</td>
              <td className={td}>{scoring[d.id] ? <span className="text-sm">{scoring[d.id]}</span> : <span className="text-sm text-slate-400">—</span>}</td>
              <td className={`${td} text-right`}>
                {canWrite && <Button kind="secondary" onClick={() => score(d.id)} disabled={["queued", "running"].includes(scoring[d.id])}>Score risk</Button>}
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
