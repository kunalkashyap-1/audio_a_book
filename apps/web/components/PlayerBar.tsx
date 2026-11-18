"use client";

import type { ChapterState } from "@aab/contracts";

type Props = {
  playing: ChapterState | null;
  nowState: string;
  progressPct: number;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  onTimeUpdate: () => void;
  onEnded: () => void;
};

export function PlayerBar({
  playing,
  nowState,
  progressPct,
  audioRef,
  onTimeUpdate,
  onEnded,
}: Props) {
  const title = playing
    ? playing.title || `Chapter ${playing.ordinal + 1}`
    : "Nothing playing";

  return (
    <div className="panel sticky bottom-0 mt-6 p-3 shadow-2xl shadow-black/40">
      <div className="mb-2 flex items-center justify-between gap-3">
        <strong className="truncate text-sm">{title}</strong>
        <span className="shrink-0 text-xs text-mist-400">{nowState}</span>
      </div>
      {/* src is set imperatively by the player hook so seeking and re-play are reliable. */}
      <audio
        ref={audioRef}
        className="audio-player"
        controls
        preload="metadata"
        onTimeUpdate={onTimeUpdate}
        onEnded={onEnded}
      />
      <div className="mt-2 h-[3px] overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full bg-mint-400 transition-[width]"
          style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
        />
      </div>
    </div>
  );
}
