"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { LibraryItem } from "@aab/contracts";
import { Header } from "@/components/Header";
import { api, messageOf } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { shortDate } from "@/lib/format";
import { useHealth } from "@/lib/useHealth";

export default function LibraryPage() {
  const health = useHealth();
  const { user, ready } = useAuth();
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ready || !user) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const page = await api.library();
        if (!cancelled) setItems(page.items);
      } catch (err) {
        if (!cancelled) setError(messageOf(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, user]);

  const remove = async (id: string) => {
    try {
      await api.libraryRemove(id);
      setItems((previous) => previous.filter((item) => item.id !== id));
    } catch (err) {
      setError(messageOf(err));
    }
  };

  return (
    <div className="min-h-screen">
      <Header health={health} />
      <main className="mx-auto max-w-3xl p-6">
        <h1 className="text-2xl font-semibold">Your library</h1>
        <p className="mt-1 text-sm text-mist-400">Books you have added to your shelf.</p>

        {error && <p className="mt-4 text-sm text-rose-400">{error}</p>}

        {!ready ? (
          <p className="mt-6 text-sm text-mist-400">Restoring session…</p>
        ) : !user ? (
          <div className="panel mt-6 p-5">
            <p className="text-sm text-mist-300">
              Sign in to keep a personal shelf and remember where you stopped listening.
            </p>
            <Link href="/" className="link mt-3 inline-block text-sm">
              Back to the catalogue →
            </Link>
          </div>
        ) : loading ? (
          <p className="mt-6 text-sm text-mist-400">Loading…</p>
        ) : items.length === 0 ? (
          <p className="mt-6 text-sm text-mist-400">
            Your shelf is empty. Add a book from the catalogue.
          </p>
        ) : (
          <ul className="mt-6 grid gap-2">
            {items.map((item) => (
              <li key={item.id} className="panel flex items-center gap-4 p-4">
                <div className="min-w-0 flex-1">
                  <Link href={`/?book=${encodeURIComponent(item.id)}`} className="font-semibold hover:text-mint-400">
                    {item.title}
                  </Link>
                  <p className="mt-0.5 text-xs text-mist-400">
                    {item.author || "Unknown"} · added {shortDate(item.added_at)} · {item.status}
                  </p>
                </div>
                <Link href={`/?book=${encodeURIComponent(item.id)}`} className="btn-ghost !px-3 !py-1.5 !text-xs">
                  Listen
                </Link>
                <button
                  type="button"
                  className="text-mist-400 hover:text-rose-400"
                  title="Remove from shelf"
                  onClick={() => void remove(item.id)}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
