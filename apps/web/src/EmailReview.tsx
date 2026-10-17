import { useEffect, useState } from "react";
import { api2, UnattachedEmail } from "./api";
import { Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Ingested emails no deal matched. Attaching one files it to a deal; the server checks the key may write there. */
export function EmailReview() {
  const [emails, setEmails] = useState<UnattachedEmail[] | null>(null);
  const [deal, setDeal] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = () => api2.emailReview().then((r) => { setEmails(r.emails); setErr(""); }).catch((x) => setErr(String(x)));
  useEffect(() => { load(); }, []);

  const attach = (docId: string) => {
    const name = (deal[docId] ?? "").trim();
    if (!name) return;
    setBusy(docId);
    api2.emailAttach(docId, name)
      .then(() => { setEmails((rows) => rows?.filter((e) => e.document_id !== docId) ?? null); setErr(""); })
      .catch((x) => setErr(String(x)))
      .finally(() => setBusy(null));
  };

  return (
    <Page title="Email review" hint="Emails no deal matched. Attach each one to the deal it belongs to; the rest stay here.">
      {err && <ErrorLine e={err} />}
      {emails && emails.length === 0 && <Empty>Nothing waiting. Every ingested email has a deal.</Empty>}
      {emails && emails.length > 0 && (
        <Card>
          <CardHead title="Unattached" hint={`${emails.length} waiting`} />
          <ul className="divide-y divide-line text-sm">
            {emails.map((e) => (
              <li key={e.document_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <div className="truncate">{e.filename}</div>
                  {e.source_url && <a className="text-xs text-acc" href={e.source_url} target="_blank" rel="noreferrer">Open source</a>}
                </div>
                <form className="flex items-center gap-2" onSubmit={(ev) => { ev.preventDefault(); attach(e.document_id); }}>
                  <Input aria-label="Deal name" placeholder="Deal" value={deal[e.document_id] ?? ""}
                    onChange={(ev) => setDeal({ ...deal, [e.document_id]: ev.target.value })} />
                  <Button variant="primary" type="submit" disabled={!(deal[e.document_id] ?? "").trim() || busy === e.document_id}>
                    {busy === e.document_id ? "Attaching" : "Attach"}
                  </Button>
                </form>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
