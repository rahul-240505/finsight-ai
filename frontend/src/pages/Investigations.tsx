import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, waitForJob, type Dataset, type Job, type Report, type Step, type User } from "../api";
import { Button, Card, Field, inputClass, money, Note, Status, Table, td, tdNum, when } from "../ui";

// Report text comes from a language model that read user data, so it is untrusted: it is only
// ever rendered as React text (escaped), never as HTML, and links in it are not made clickable.

export default function Investigations({ user, reportId, onOpen }: { user: User; reportId: string; onOpen: (id: string) => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [focus, setFocus] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const canStart = user.role !== "viewer";

  const load = () => api.reports().then(setReports, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
    if (canStart) api.datasets().then((d) => { setDatasets(d); setDatasetId(d[0]?.id ?? ""); }, () => undefined);
  }, []);

  const start = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setElapsed(0);
    const t0 = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      const done = await waitForJob((await api.investigate(datasetId, focus)).id, setJob, 2000);
      setJob(done);
      if (done.status === "succeeded") { await load(); onOpen(String(done.result?.report_id)); }
    } catch (err) { setError(errorText(err)); }
    finally { clearInterval(timer); }
  };

  const running = job?.status === "queued" || job?.status === "running";
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div className="flex flex-col gap-6">
        {canStart && (
          <Card title="New investigation">
            <form onSubmit={start} className="flex flex-col gap-3">
              <Field label="Dataset">
                <select id="inv-dataset" className={inputClass} value={datasetId} onChange={(e) => setDatasetId(e.target.value)} required>
                  {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </Field>
              <Field label="What should the agent look into?" hint="The agent reads data with read-only tools and writes a draft. A reviewer must approve it.">
                <textarea id="inv-focus" className={`${inputClass} min-h-20`} minLength={3} maxLength={500} required value={focus}
                  onChange={(e) => setFocus(e.target.value)} placeholder="e.g. Unusual night-time transfers to new merchants" />
              </Field>
              <div><Button type="submit" disabled={running || !datasetId}>{running ? `Investigating… ${elapsed} s` : "Start investigation"}</Button></div>
            </form>
            {job && !running && job.status === "failed" && <div className="mt-3"><Note>{job.error?.message ?? "The investigation failed."}</Note></div>}
          </Card>
        )}
        <Card title="Reports">
          {error && <Note>{error}</Note>}
          <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
            {reports.map((r) => (
              <li key={r.id}>
                <button onClick={() => onOpen(r.id)} aria-current={r.id === reportId || undefined}
                  className={`flex w-full flex-col gap-1 px-2 py-3 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-950 ${r.id === reportId ? "bg-teal-50 dark:bg-teal-950/40" : ""}`}>
                  <span className="flex items-center gap-2"><Status value={r.status} /><span className="text-slate-500">{when(r.created_at)}</span></span>
                  <span className="line-clamp-2">{r.focus}</span>
                </button>
              </li>
            ))}
            {!reports.length && <li className="py-4 text-sm text-slate-500">No reports yet.</li>}
          </ul>
        </Card>
      </div>
      {reportId ? <ReportView key={reportId} id={reportId} user={user} onChange={load} /> : (
        <Card><p className="text-sm text-slate-500">Choose a report to read it.</p></Card>
      )}
    </div>
  );
}

function ReportView({ id, user, onChange }: { id: string; user: User; onChange: () => void }) {
  const [report, setReport] = useState<Report | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.report(id).then(setReport, (e) => setError(errorText(e)));
    api.steps(id).then(setSteps, () => setSteps([]));
  }, [id]);

  const act = async (fn: () => Promise<Report>) => {
    setError("");
    try { setReport(await fn()); onChange(); } catch (err) { setError(errorText(err)); }
  };

  if (error && !report) return <Card><Note>{error}</Note></Card>;
  if (!report) return <Card><p className="text-sm text-slate-500">Loading…</p></Card>;
  const c = report.content;
  const isOwner = report.owner_id === user.id;
  const canReview = user.role === "admin" && !isOwner && report.status === "submitted";

  return (
    <Card title={<span className="flex items-center gap-2">Investigation report <Status value={report.status} /></span>}>
      <div className="flex flex-col gap-5 text-sm">
        <p className="text-slate-500">Focus: {report.focus}</p>
        {c.wording_flag && <Note>The model used the word “fraud” even after being asked not to. Read with care.</Note>}
        <section><h3 className="mb-1 font-semibold">Summary</h3><p className="whitespace-pre-wrap leading-relaxed">{c.summary}</p></section>
        <section>
          <h3 className="mb-2 font-semibold">Findings ({c.findings.length})</h3>
          <Table head={["Transaction", "Amount #", "Risk #", "Observation"]} empty={c.findings.length ? undefined : "No findings."}>
            {c.findings.map((f) => (
              <tr key={f.transaction_id}>
                <td className={td}><span className="font-mono text-xs">{f.evidence.account_id}</span><br />{f.evidence.merchant} · {when(f.evidence.occurred_at)}</td>
                <td className={tdNum}>{money(f.evidence.amount, f.evidence.currency)}</td>
                <td className={tdNum}>{f.evidence.risk_score?.toFixed(3) ?? "—"}</td>
                <td className={td}>{f.observation}</td>
              </tr>
            ))}
          </Table>
          <p className="mt-1 text-xs text-slate-500">Amounts, merchants and scores come from the database, not from the model.{c.dropped_findings ? ` ${c.dropped_findings} finding(s) about transactions the agent never looked up were removed.` : ""}</p>
        </section>
        <section><h3 className="mb-1 font-semibold">Recommendation</h3><p className="whitespace-pre-wrap">{c.recommendation}</p></section>
        {c.policy_refs.length > 0 && (
          <section><h3 className="mb-1 font-semibold">Policy references</h3>
            <ul className="flex flex-col gap-2">{c.policy_refs.map((p) => (
              <li key={p.id} className="rounded-md border border-slate-200 p-2 dark:border-slate-800"><b>{p.filename}</b> · page {p.page}<p className="text-slate-600 dark:text-slate-400">“{p.excerpt}”</p></li>
            ))}</ul>
          </section>
        )}
        <p className="text-xs text-slate-500">{c.disclaimer} · {report.model} · {c.tool_calls} tool calls</p>
        {report.review_note && <Note kind="info">Reviewer note: {report.review_note}</Note>}
        {error && <Note>{error}</Note>}
        <div className="flex flex-wrap items-end gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
          {isOwner && report.status === "draft" && <Button onClick={() => act(() => api.submit(id))}>Submit for review</Button>}
          {canReview && (
            <>
              <Field label="Review note"><input id="review-note" className={inputClass} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
              <Button onClick={() => act(() => api.approve(id, note))}>Approve</Button>
              <Button kind="danger" onClick={() => act(() => api.reject(id, note))}>Reject</Button>
            </>
          )}
          {report.status === "submitted" && isOwner && <p className="text-slate-500">Waiting for another person to review.</p>}
        </div>
        {steps.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer font-semibold">Audit trail ({steps.length} steps)</summary>
            <div className="mt-2"><Table head={["Step #", "Tool", "Outcome", "Result chars #", "Time #"]}>
              {steps.map((s) => (
                <tr key={`${s.attempt}-${s.step}`}><td className={tdNum}>{s.step}</td><td className={`${td} font-mono text-xs`}>{s.tool}</td>
                  <td className={td}><Status value={s.status} />{s.error && <span className="ml-2 text-xs text-slate-500">{s.error.slice(0, 120)}</span>}</td>
                  <td className={tdNum}>{s.result_chars}</td><td className={tdNum}>{Math.round(s.latency_ms)} ms</td></tr>
              ))}
            </Table></div>
          </details>
        )}
      </div>
    </Card>
  );
}
