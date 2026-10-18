import { useState } from "react";
import { Note } from "./api";
import { useLoad } from "./hooks";
import { Button, Card, CardHead, ErrorLine, Input, Loading } from "./ui";

type NotesApi = { list: () => Promise<Note[]>; add: (body: string) => Promise<Note>; edit: (id: number, body: string) => Promise<Note> };

// Shared notes list: add, and edit a note. Edits show "edited" with the time, and the old text stays in the audit trail.
export function NotesPanel({ title, hint, api, deps }: { title: string; hint: string; api: NotesApi; deps: unknown[] }) {
  const notes = useLoad(() => api.list(), deps);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const save = async () => {
    setErr("");
    try {
      if (editing !== null) await api.edit(editing, text); else await api.add(draft);
      setDraft(""); setEditing(null); setText("");
      notes.reload();
    } catch (e) {
      setErr(String(e));
    }
  };
  return (
    <Card>
      <CardHead title={title} hint={hint} />
      <div className="space-y-3 p-4 text-sm">
        <ErrorLine e={err || notes.error} />
        {notes.loading && <Loading />}
        {(notes.data ?? []).map((n) => (
          <div key={n.id} className="rounded-lg border border-line p-3">
            <div className="mb-1 flex justify-between text-xs text-mut">
              <span>{n.author} · {n.created_at}{n.edited_at && ` · edited ${n.edited_at}`}</span>
              <button className="underline" onClick={() => { setEditing(n.id); setText(n.body); }}>Edit</button>
            </div>
            {editing === n.id ? (
              <div className="flex gap-2"><Input aria-label="Edit note" value={text} onChange={(e) => setText(e.target.value)} className="flex-1" />
                <Button variant="primary" onClick={save}>Save</Button></div>
            ) : <p className="whitespace-pre-wrap">{n.body}</p>}
          </div>
        ))}
        {notes.data && notes.data.length === 0 && <p className="text-mut">No notes yet.</p>}
        {editing === null && (
          <div className="flex gap-2">
            <Input aria-label="New note" placeholder="Add a note" value={draft} onChange={(e) => setDraft(e.target.value)} className="flex-1" />
            <Button variant="primary" onClick={save} disabled={!draft.trim()}>Add</Button>
          </div>
        )}
      </div>
    </Card>
  );
}
