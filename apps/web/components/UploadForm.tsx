"use client";

import { useRef, useState } from "react";
import { api, messageOf, setAdminToken } from "@/lib/api";

const RIGHTS = [
  { value: "public_domain_us", label: "Public domain (US)" },
  { value: "user_owned", label: "I own the rights" },
  { value: "unknown", label: "Unknown / private" },
];

export function UploadForm({ onUploaded }: { onUploaded: (bookId: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [rights, setRights] = useState(RIGHTS[0].value);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Choose a file first.");
      return;
    }

    // Legacy operator token, stored locally the same way the zero-build player does it.
    if (token.trim()) setAdminToken(token.trim());

    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("author", author);
    form.append("rights_basis", rights);

    setBusy(true);
    try {
      const result = await api.upload(form);
      onUploaded(result.book_id);
      setTitle("");
      setAuthor("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-2.5">
      <input
        className="field"
        placeholder="Title (optional)"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
      />
      <input
        className="field"
        placeholder="Author (optional)"
        value={author}
        onChange={(event) => setAuthor(event.target.value)}
      />
      <select className="field" value={rights} onChange={(event) => setRights(event.target.value)}>
        {RIGHTS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <input
        ref={fileRef}
        className="field text-xs"
        type="file"
        accept=".txt,.md,.html,.htm,.epub"
      />
      <input
        className="field"
        type="password"
        placeholder="Operator token (if required)"
        value={token}
        onChange={(event) => setToken(event.target.value)}
      />
      <button type="submit" className="btn" disabled={busy}>
        {busy ? "Uploading…" : "Upload & analyse"}
      </button>
      <p className="text-xs leading-relaxed text-mist-400">
        TXT, Markdown, HTML or EPUB. Max 25&nbsp;MB. Files stay on this machine.
      </p>
      {error && <p className="text-xs text-rose-400">{error}</p>}
    </form>
  );
}
