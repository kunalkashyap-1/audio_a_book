"use client";

import type { BookSummary } from "@aab/contracts";
import { UploadForm } from "./UploadForm";

type Props = {
  books: BookSummary[];
  activeId: string | null;
  search: string;
  onSearch: (value: string) => void;
  onRefresh: () => void;
  onOpen: (id: string) => void;
  onUploaded: (id: string) => void;
};

export function Sidebar({
  books,
  activeId,
  search,
  onSearch,
  onRefresh,
  onOpen,
  onUploaded,
}: Props) {
  const query = search.trim().toLowerCase();
  const filtered = books.filter((book) =>
    `${book.title} ${book.author ?? ""}`.toLowerCase().includes(query),
  );

  return (
    <aside className="border-b border-ink-800 p-4 md:min-h-[calc(100vh-69px)] md:border-b-0 md:border-r">
      <div className="mb-3 flex gap-2">
        <input
          className="field"
          placeholder="Filter books"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
        <button type="button" className="btn-ghost !px-3" title="Refresh" onClick={onRefresh}>
          ↻
        </button>
      </div>

      <div className="mb-4 grid gap-1">
        {filtered.length === 0 ? (
          <p className="text-sm text-mist-400">No books yet. Upload one.</p>
        ) : (
          filtered.map((book) => (
            <button
              key={book.id}
              type="button"
              onClick={() => onOpen(book.id)}
              className={`rounded-lg border px-3 py-2 text-left transition-colors ${
                activeId === book.id
                  ? "border-ink-800 bg-ink-900"
                  : "border-transparent hover:bg-ink-900"
              }`}
            >
              <div className="text-sm font-semibold">{book.title}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-mist-400">
                <span>{book.author || "Unknown"}</span>
                <span className={`badge ${book.status === "ready" ? "" : "badge-grey"}`}>
                  {book.status}
                </span>
                <span className="badge badge-grey">{book.chapters} ch</span>
              </div>
            </button>
          ))
        )}
      </div>

      <details className="border-t border-ink-800 pt-4">
        <summary className="cursor-pointer text-sm text-mist-400 hover:text-mist-100">
          Add a book
        </summary>
        <div className="mt-3">
          <UploadForm onUploaded={onUploaded} />
        </div>
      </details>
    </aside>
  );
}
