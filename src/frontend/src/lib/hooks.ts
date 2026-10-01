import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** True only for the first load, so polling never flashes a spinner. */
  initial: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

/**
 * Runs `fn` on mount and whenever `deps` change. When `intervalMs` is set the
 * request repeats on that interval, which is how the running screen follows a
 * pipeline without a websocket.
 */
export function useApi<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  intervalMs?: number | null,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [initial, setInitial] = useState(true);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      setLoading(true);
      try {
        const result = await fnRef.current();
        if (cancelled) return;
        setData(result);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
          setInitial(false);
        }
      }
    };

    void run();
    if (!intervalMs) return () => {
      cancelled = true;
    };

    const timer = window.setInterval(run, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, intervalMs]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, initial, reload, setData };
}

/**
 * Milliseconds between `start` and now, ticking once a second while `active`.
 * Once `end` is set the clock freezes on the real duration rather than
 * continuing to count time nobody spent waiting.
 */
export function useElapsed(
  start: string | null | undefined,
  active: boolean,
  end?: string | null,
): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  if (!start) return 0;
  const from = new Date(start).getTime();
  const to = end ? new Date(end).getTime() : now;
  return Math.max(0, to - from);
}

export function useLocalStorage(key: string, fallback: string): [string, (v: string) => void] {
  const [value, setValue] = useState<string>(
    () => window.localStorage.getItem(key) ?? fallback,
  );
  const update = useCallback(
    (next: string) => {
      setValue(next);
      window.localStorage.setItem(key, next);
    },
    [key],
  );
  return [value, update];
}

/** Theme and density are attributes on <body>, matching the design brief's
 *  token switches, and they persist per browser. */
export function useDisplayPreferences() {
  const [theme, setTheme] = useLocalStorage("repovue.theme", "light");
  const [density, setDensity] = useLocalStorage("repovue.density", "comfortable");

  useEffect(() => {
    document.body.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    document.body.dataset.density = density;
  }, [density]);

  return {
    theme,
    density,
    toggleTheme: () => setTheme(theme === "dark" ? "light" : "dark"),
    toggleDensity: () => setDensity(density === "compact" ? "comfortable" : "compact"),
  };
}

/** Fires `handler` for keys pressed outside of inputs. */
export function useKeyboard(handler: (event: KeyboardEvent) => void, active = true) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      ref.current(event);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);
}
