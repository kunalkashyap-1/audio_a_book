"use client";

import type { BookDetail as BookDetailType, ChapterState } from "@aab/contracts";
import { chapterLabel } from "@/lib/format";

type Props = {
  book: BookDetailType;
  playingId: string | null;
  chapterStates: Record<string, string>;
  onPlay: (chapterId: string) => void;
  onGenerate: () => void;
  generating: boolean;
};

export function BookDetail({
  book,
  playingId,
  chapterStates,
  onPlay,
  onGenerate,
  generating,
}: Props) {
  const { work, cast, chapters } = book;

  return (
    <div className="max-w-3xl">
      <h2 className="m-0 text-2xl font-semibold">{work.title}</h2>
      <p className="mt-1 text-sm text-mist-400">
        {work.author || "Unknown"} · {work.rights_basis} · {work.language}
      </p>

      {cast.length > 0 && (
        <div className="my-4 flex flex-wrap gap-2">
          {cast.map((member, index) => (
            <span key={member.character_id ?? `cast-${index}`} className="chip">
              {member.name} · {member.voice || "voice"}
            </span>
          ))}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <button type="button" className="btn" onClick={onGenerate} disabled={generating}>
          {generating ? "Queueing…" : "Generate all chapters"}
        </button>
        <span className="text-xs text-mist-400">Generation runs in the local worker.</span>
      </div>

      <div className="panel overflow-hidden">
        {chapters.length === 0 ? (
          <p className="p-4 text-sm text-mist-400">No chapters detected yet.</p>
        ) : (
          chapters.map((chapter: ChapterState) => (
            <button
              key={chapter.id}
              type="button"
              onClick={() => onPlay(chapter.id)}
              className={`flex w-full items-center gap-3 border-b border-ink-800 px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-ink-850 ${
                playingId === chapter.id ? "bg-ink-850 shadow-[inset_2px_0_0_var(--color-mint-400)]" : ""
              }`}
            >
              <span className="w-6 shrink-0 text-sm tabular-nums text-mist-400">
                {chapter.ordinal + 1}
              </span>
              <span className="flex-1 truncate text-sm">
                {chapter.title || `Chapter ${chapter.ordinal + 1}`}
              </span>
              <span className="shrink-0 text-xs text-mist-400" data-chapter={chapter.id}>
                {chapterStates[chapter.id] ?? chapterLabel(chapter)}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
