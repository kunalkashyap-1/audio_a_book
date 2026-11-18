"use client";

/**
 * The listen screen — a typed port of the zero-build player. It owns catalogue selection,
 * generation, render polling, playback and progress persistence, and composes the presentational
 * components. All network calls go through `api`, so API shapes stay generated.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BookDetail as BookDetailType,
  BookSummary,
  ChapterManifest,
  Health,
  RenderPending,
} from "@aab/contracts";
import {
  api,
  getAccessToken,
  mediaUrl,
  messageOf,
} from "@/lib/api";
import { BookDetail } from "./BookDetail";
import { Header } from "./Header";
import { PlayerBar } from "./PlayerBar";
import { Sidebar } from "./Sidebar";

export function PlayerApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [books, setBooks] = useState<BookSummary[]>([]);
  const [bookId, setBookId] = useState<string | null>(null);
  const [book, setBook] = useState<BookDetailType | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ChapterManifest | null>(null);
  const [nowState, setNowState] = useState("");
  const [progressPct, setProgressPct] = useState(0);
  const [chapterStates, setChapterStates] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSavedRef = useRef(0);

  const setChapterState = useCallback((id: string, text: string) => {
    setChapterStates((previous) => ({ ...previous, [id]: text }));
  }, []);

  const loadBooks = useCallback(async () => {
    try {
      const page = await api.books();
      setBooks(page.items);
    } catch (err) {
      setError(messageOf(err));
    }
  }, []);

  const openBook = useCallback(async (id: string) => {
    try {
      const detail = await api.book(id);
      setBookId(id);
      setBook(detail);
      setError("");
    } catch (err) {
      setError(messageOf(err));
    }
  }, []);

  const refreshBook = useCallback(async () => {
    if (!bookId) return;
    try {
      setBook(await api.book(bookId));
    } catch {
      // A transient failure while polling is not worth interrupting playback.
    }
  }, [bookId]);

  // Boot: health, catalogue, and an optional ?book=<id> deep link from the library.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        setHealth(await api.health());
      } catch {
        // health text falls back to "offline"
      }
      await loadBooks();
      const requested =
        typeof window !== "undefined"
          ? new URLSearchParams(window.location.search).get("book")
          : null;
      if (requested && !cancelled) await openBook(requested);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadBooks, openBook]);

  useEffect(() => {
    const timer = setInterval(() => {
      void api.health().then(setHealth).catch(() => {});
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      if (!playingId) void refreshBook();
    }, 12000);
    return () => clearInterval(timer);
  }, [playingId, refreshBook]);

  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
    },
    [],
  );

  // Start playback from a finished manifest, restoring the saved position first.
  const start = useCallback(
    async (chapterId: string, finished: ChapterManifest) => {
      const audio = audioRef.current;
      if (!audio || !finished.master_url) {
        setNowState("no audio");
        return;
      }

      let savedMs = 0;
      if (getAccessToken()) {
        try {
          const progress = await api.progress(chapterId);
          savedMs = progress?.position_ms ?? 0;
        } catch {
          // Fall through to the local position.
        }
      }
      if (!savedMs && typeof window !== "undefined") {
        savedMs = Number(localStorage.getItem(`pos:${chapterId}`) || 0);
      }

      if (savedMs > 2000) {
        audio.addEventListener(
          "loadedmetadata",
          () => {
            try {
              audio.currentTime = savedMs / 1000;
            } catch {
              /* metadata may not be seekable yet */
            }
          },
          { once: true },
        );
      }

      audio.src = mediaUrl(finished.master_url);
      void audio.play().catch(() => {});
      lastSavedRef.current = savedMs;

      setManifest(finished);
      setNowState(finished.complete ? "" : "partial");
      setChapterState(chapterId, "playing");
      void refreshBook();
    },
    [refreshBook, setChapterState],
  );

  // poll a rendering chapter until its manifest is ready.
  const startPolling = useCallback(
    (chapterId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      let attempts = 0;
      pollRef.current = setInterval(() => {
        attempts += 1;
        if (attempts > 400) {
          if (pollRef.current) clearInterval(pollRef.current);
          setNowState("render timed out");
          return;
        }
        void (async () => {
          try {
            const { status, data } = await api.renderStatus(chapterId);
            if (status === 200) {
              if (pollRef.current) clearInterval(pollRef.current);
              await start(chapterId, data as ChapterManifest);
              return;
            }
            const info = data as RenderPending;
            if (info.total) {
              setChapterState(chapterId, `${info.progress}/${info.total}`);
              setNowState(`rendering ${info.progress}/${info.total}`);
              setProgressPct((100 * info.progress) / info.total);
            } else {
              setChapterState(chapterId, info.status || "queued");
              setNowState(info.status || "queued");
            }
          } catch {
            // Keep polling through transient errors.
          }
        })();
      }, 1500);
    },
    [start, setChapterState],
  );

  const playChapter = useCallback(
    async (chapterId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      const audio = audioRef.current;
      if (audio) {
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      }
      setPlayingId(chapterId);
      setManifest(null);
      setNowState("");
      setProgressPct(0);

      try {
        const { status, data } = await api.renderStatus(chapterId);
        if (status === 200) {
          await start(chapterId, data as ChapterManifest);
          return;
        }
        setChapterState(chapterId, "queued…");
        setNowState("queued…");
        await api.render(chapterId);
        startPolling(chapterId);
      } catch (err) {
        setError(messageOf(err));
        setChapterState(chapterId, "error");
      }
    },
    [start, startPolling, setChapterState],
  );

  const nextChapter = useCallback(() => {
    const chapters = book?.chapters ?? [];
    const index = chapters.findIndex((chapter) => chapter.id === playingId);
    if (index >= 0 && index + 1 < chapters.length) {
      void playChapter(chapters[index + 1].id);
    }
  }, [book, playingId, playChapter]);

  const onTimeUpdate = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !audio.duration || !playingId) return;
    setProgressPct((100 * audio.currentTime) / audio.duration);
    const positionMs = Math.round(audio.currentTime * 1000);
    try {
      localStorage.setItem(`pos:${playingId}`, String(positionMs));
    } catch {
      // Storage may be unavailable in private mode.
    }
    if (getAccessToken() && positionMs - lastSavedRef.current > 5000) {
      lastSavedRef.current = positionMs;
      void api
        .saveProgress(playingId, {
          position_ms: positionMs,
          duration_ms: Math.round(audio.duration * 1000),
        })
        .catch(() => {});
    }
  }, [playingId]);

  const generateAll = useCallback(async () => {
    if (!book) return;
    setGenerating(true);
    try {
      await api.generate(book.work.id);
      setTimeout(() => {
        void refreshBook();
      }, 800);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setGenerating(false);
    }
  }, [book, refreshBook]);

  const onUploaded = useCallback(
    async (id: string) => {
      await loadBooks();
      await openBook(id);
      setTimeout(() => {
        void api
          .book(id)
          .then(setBook)
          .catch(() => {});
      }, 2500);
    },
    [loadBooks, openBook],
  );

  const playing = book?.chapters.find((chapter) => chapter.id === playingId) ?? null;

  return (
    <div className="min-h-screen">
      <Header health={health} />

      {error && (
        <div className="mx-5 mt-3 flex items-center justify-between gap-3 rounded-lg border border-rose-400/40 bg-rose-400/10 px-4 py-2 text-sm text-rose-400">
          <span>{error}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setError("")}>
            ✕
          </button>
        </div>
      )}

      <main className="grid md:grid-cols-[300px_1fr]">
        <Sidebar
          books={books}
          activeId={bookId}
          search={search}
          onSearch={setSearch}
          onRefresh={() => void loadBooks()}
          onOpen={(id) => void openBook(id)}
          onUploaded={(id) => void onUploaded(id)}
        />

        <section className="max-w-5xl p-5 md:p-7">
          {book ? (
            <BookDetail
              book={book}
              playingId={playingId}
              chapterStates={chapterStates}
              onPlay={(id) => void playChapter(id)}
              onGenerate={() => void generateAll()}
              generating={generating}
            />
          ) : (
            <p className="text-mist-400">Choose a book to begin.</p>
          )}

          <PlayerBar
            playing={playing}
            nowState={nowState}
            progressPct={progressPct}
            audioRef={audioRef}
            onTimeUpdate={onTimeUpdate}
            onEnded={nextChapter}
          />
        </section>
      </main>
    </div>
  );
}
