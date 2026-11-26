import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, waitForJob, type Answer, type Doc, type User } from "../api";
import { Button, Card, Note, Status, Table, td, tdNum, when } from "../ui";

const REASONS: Record<string, string> = {
  no_relevant_passages: "Not enough evidence: no passage in your documents is close enough to the question.",
  model_declined: "The model said the passages don't answer this question.",
  no_valid_citation: "The model's answer did not cite the passages it was given, so it is not shown.",
};

export default function Policies({ user }: { user: User }) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [uploading, setUploading] = useState("");
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.documents().then(setDocs, (e) => setError(errorText(e)));
  useEffect(() => { load(); }, []);

  const upload = async (file: File) => {
    setError(""); setUploading("uploading");
    try {
      const res = await api.uploadDocument(file);
      if ("kind" in res) {
        const job = await waitForJob(res.id, (j) => setUploading(j.status));
        if (job.status === "failed") setError(job.error?.message ?? "Indexing failed.");
      }
      load();
    } catch (err) { setError(errorText(err)); }
    finally { setUploading(""); }
  };

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(""); setAnswer(null); setAsked(question);
    try { setAnswer(await api.ask(question)); }
    catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <Card title="Ask about your policies">
        <form onSubmit={ask} className="flex flex-col gap-3">
          <textarea id="question" className="min-h-24 rounded-md border border-slate-300 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-950"
            maxLength={500} required value={question} onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. When must a cash transaction be reported?" />
          <div><Button type="submit" disabled={busy || !question.trim()}>{busy ? "Searching your documents…" : "Ask"}</Button></div>
        </form>
        {error && <div className="mt-4"><Note>{error}</Note></div>}
        {answer && (
          <article className="mt-5 flex flex-col gap-3" aria-live="polite">
            <p className="text-sm text-slate-500">Q: {asked}</p>
            {answer.status === "answered" ? (
              <p className="whitespace-pre-wrap leading-relaxed">{answer.answer}</p>
            ) : (
              <Note kind="info">{REASONS[answer.reason ?? ""] ?? "No answer could be given."}</Note>
            )}
            {answer.citations.length > 0 && (
              <ol className="flex flex-col gap-2">
                {answer.citations.map((c) => (
                  <li key={c.source} className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
                    <p className="font-medium"><span className="font-mono text-teal-700 dark:text-teal-400">[{c.source}]</span> {c.filename} · page {c.page}</p>
                    <p className="mt-1 text-slate-600 dark:text-slate-400">“{c.excerpt}”</p>
                  </li>
                ))}
              </ol>
            )}
            <p className="font-mono text-xs text-slate-500">{answer.model ?? "no model call"} · {Math.round(answer.latency_ms)} ms</p>
          </article>
        )}
      </Card>
      <Card title="Policy documents" actions={user.role !== "viewer" && (
        <label className="cursor-pointer rounded-md border border-slate-300 px-3 py-2 text-sm hover:border-teal-600 dark:border-slate-700">
          {uploading ? `Indexing… (${uploading})` : "Upload PDF"}
          <input id="pdf-file" type="file" accept="application/pdf,.pdf" className="sr-only" disabled={!!uploading}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
        </label>)}>
        <Table head={["File", "Pages #", "Status", "Added"]} empty={docs.length ? undefined : "No documents yet."}>
          {docs.map((d) => (
            <tr key={d.id}><td className={`${td} break-all`}>{d.filename}</td><td className={tdNum}>{d.page_count}</td>
              <td className={td}><Status value={d.status} /></td><td className={td}>{when(d.created_at)}</td></tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
