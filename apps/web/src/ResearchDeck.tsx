import { useState } from "react";
import { api2 } from "./api";
import { Button, Card, CardHead, ErrorLine, Input, Page } from "./ui";

/** The research note for one target as slides, one per section. Built on the server from the same records as the note. */
export function ResearchDeck() {
  const [targetId, setTargetId] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const download = () => {
    const id = Number(targetId);
    if (!Number.isInteger(id)) return;
    setBusy(true); setErr("");
    api2.researchPptxBlob(id)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = Object.assign(document.createElement("a"), { href: url, download: `research-${id}.pptx` });
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((x) => setErr(String(x)))
      .finally(() => setBusy(false));
  };

  return (
    <Page title="Research deck" hint="Download a target's research note as a PowerPoint deck.">
      <Card>
        <CardHead title="Target" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); download(); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Target id<Input inputMode="numeric" value={targetId} onChange={(e) => setTargetId(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={!/^\d+$/.test(targetId) || busy}>{busy ? "Preparing" : "Download .pptx"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
    </Page>
  );
}
