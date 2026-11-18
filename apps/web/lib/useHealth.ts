"use client";

import { useEffect, useState } from "react";
import type { Health } from "@aab/contracts";
import { api } from "./api";

export function useHealth(): Health | null {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    void api.health().then(setHealth).catch(() => {});
    const timer = setInterval(() => {
      void api.health().then(setHealth).catch(() => {});
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  return health;
}
