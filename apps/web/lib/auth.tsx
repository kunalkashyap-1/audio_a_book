"use client";

/**
 * Browser auth state. The refresh cookie is HttpOnly, so on mount we exchange it for a
 * short-lived access token held in memory (never localStorage). When accounts are disabled
 * the API answers 403 auth_disabled and the app stays in single-operator mode.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Credentials, UserOut } from "@aab/contracts";
import { ApiError, api, refreshOnce, setAccessToken } from "./api";

type AuthValue = {
  user: UserOut | null;
  /** True once the initial refresh attempt has finished. */
  ready: boolean;
  /** False when this instance has no AAB_JWT_SECRET configured. */
  authEnabled: boolean;
  login: (credentials: Credentials) => Promise<void>;
  register: (credentials: Credentials) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const pair = await refreshOnce();
        if (cancelled) return;
        setAccessToken(pair.access_token);
        setUser(pair.user);
      } catch (error) {
        if (error instanceof ApiError && error.code === "auth_disabled") {
          if (!cancelled) setAuthEnabled(false);
        }
        // No session (401) is a normal anonymous visit — stay signed out.
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (credentials: Credentials) => {
    const pair = await api.login(credentials);
    setAccessToken(pair.access_token);
    setUser(pair.user);
  }, []);

  const register = useCallback(async (credentials: Credentials) => {
    const pair = await api.register(credentials);
    setAccessToken(pair.access_token);
    setUser(pair.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ user, ready, authEnabled, login, register, logout }),
    [user, ready, authEnabled, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
