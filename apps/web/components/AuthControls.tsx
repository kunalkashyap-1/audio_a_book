"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { messageOf } from "@/lib/api";

export function AuthControls() {
  const { user, authEnabled, login, register, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!authEnabled) {
    return <span className="chip" title="Set AAB_JWT_SECRET to enable accounts">single-operator</span>;
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await login({ email, password });
      else await register({ email, password });
      setOpen(false);
      setPassword("");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {user ? (
        <div className="flex items-center gap-2">
          <span className="chip">
            {user.email}
            <span className="font-semibold text-mint-400">{user.role}</span>
          </span>
          <button
            type="button"
            className="btn-ghost !px-2 !py-1 !text-xs"
            onClick={() => void logout().catch(() => {})}
          >
            Sign out
          </button>
        </div>
      ) : (
        <button type="button" className="btn-ghost !px-3 !py-1.5" onClick={() => setOpen(true)}>
          Sign in
        </button>
      )}

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setOpen(false)}
        >
          <div className="panel w-full max-w-sm p-6" onClick={(event) => event.stopPropagation()}>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                {mode === "login" ? "Welcome back" : "Create an account"}
              </h2>
              <button
                type="button"
                className="text-mist-400 hover:text-mist-100"
                aria-label="Close"
                onClick={() => setOpen(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={submit} className="grid gap-3">
              <label className="grid gap-1 text-xs text-mist-400">
                Email
                <input
                  className="field"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>
              <label className="grid gap-1 text-xs text-mist-400">
                Password
                <input
                  className="field"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                  minLength={mode === "register" ? 8 : undefined}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>

              {error && <p className="text-xs text-rose-400">{error}</p>}

              <button type="submit" className="btn mt-1" disabled={busy}>
                {busy ? "Working…" : mode === "login" ? "Sign in" : "Register"}
              </button>
            </form>

            <p className="mt-4 text-center text-xs text-mist-400">
              {mode === "login" ? "New here?" : "Already have an account?"}{" "}
              <button
                type="button"
                className="link"
                onClick={() => {
                  setMode(mode === "login" ? "register" : "login");
                  setError("");
                }}
              >
                {mode === "login" ? "Register" : "Sign in"}
              </button>
            </p>
          </div>
        </div>
      )}
    </>
  );
}
