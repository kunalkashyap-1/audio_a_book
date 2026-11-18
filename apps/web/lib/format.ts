import type { ChapterState } from "@aab/contracts";

/** Compact status label for a chapter row, matching the zero-build player. */
export function chapterLabel(chapter: ChapterState): string {
  switch (chapter.status) {
    case "ready":
      return "ready";
    case "rendering":
      return chapter.total ? `${chapter.progress}/${chapter.total}` : "rendering";
    case "ready_with_gaps":
      return "ready (gaps)";
    case "not_started":
      return "not started";
    default:
      return chapter.status;
  }
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
}
