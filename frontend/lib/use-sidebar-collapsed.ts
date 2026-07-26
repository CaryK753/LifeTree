"use client";
import { useCallback, useEffect, useState } from "react";

const KEY = "lifetree.sidebar.collapsed";
const EVENT = "sidebar:collapsed-change";

export function useSidebarCollapsed() {
  const [collapsed, setCollapsedState] = useState(false);

  useEffect(() => {
    try {
      setCollapsedState(localStorage.getItem(KEY) === "1");
    } catch {}
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setCollapsedState(e.newValue === "1");
    };
    const onCustom = () => {
      try {
        setCollapsedState(localStorage.getItem(KEY) === "1");
      } catch {}
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(EVENT, onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(EVENT, onCustom);
    };
  }, []);

  const setCollapsed = useCallback((v: boolean) => {
    try {
      localStorage.setItem(KEY, v ? "1" : "0");
    } catch {}
    window.dispatchEvent(new Event(EVENT));
    setCollapsedState(v);
  }, []);

  const toggle = useCallback(() => {
    setCollapsed(!collapsed);
  }, [collapsed, setCollapsed]);

  return { collapsed, setCollapsed, toggle };
}
