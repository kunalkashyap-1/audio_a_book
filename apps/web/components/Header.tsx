"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Health } from "@aab/contracts";
import { AuthControls } from "./AuthControls";

export function Header({ health }: { health: Health | null }) {
  const pathname = usePathname();
  const queue = health?.queue ?? {};
  const queued = typeof queue.queued === "number" ? queue.queued : 0;
  const running = typeof queue.running === "number" ? queue.running : 0;

  const status = health
    ? `${health.speech} · ${health.provider} · ${queued} queued, ${running} running` +
      (health.auth_required ? " · accounts available" : "")
    : "offline";

  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-ink-800 bg-ink-950/95 px-5 py-4 backdrop-blur">
      <Link href="/" className="text-base font-semibold tracking-wide">
        Open Audio Book
      </Link>
      <span className="text-xs text-mist-400" title={status}>
        {status}
      </span>

      <nav className="ml-auto flex items-center gap-1">
        {[
          { href: "/", label: "Listen" },
          { href: "/library", label: "Library" },
          { href: "/admin", label: "Admin" },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
              pathname === item.href
                ? "bg-ink-800 text-mist-100"
                : "text-mist-400 hover:bg-ink-900 hover:text-mist-100"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <AuthControls />
    </header>
  );
}
