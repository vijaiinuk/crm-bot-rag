import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "../auth";
import type { Job } from "./types";

export interface Resource<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** GET `path` and keep the result; `null` skips the request. */
export function useResource<T>(path: string | null): Resource<T> {
  const { api } = useAuth();
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: path !== null });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (path === null) return;
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    api.get<T>(path).then(
      (data) => alive && setState({ data, loading: false }),
      (error: Error) => alive && setState((s) => ({ ...s, error, loading: false })),
    );
    return () => {
      alive = false;
    };
  }, [api, path, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data: state.data, error: state.error, loading: state.loading, reload };
}

/** Poll a background job until it finishes; `onDone` runs once with the final job. */
export function useJob(jobId: string | null, onDone?: (job: Job) => void): Job | undefined {
  const { api, pollMs } = useAuth();
  const [job, setJob] = useState<Job>();
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    if (!jobId) {
      setJob(undefined);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await api.get<Job>(`/admin/jobs/${encodeURIComponent(jobId)}`);
        if (!alive) return;
        setJob(j);
        if (j.status === "succeeded" || j.status === "failed") {
          done.current?.(j);
          return;
        }
      } catch {
        /* transient: try again */
      }
      if (alive) timer = setTimeout(tick, pollMs);
    };
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [api, jobId, pollMs]);

  return job;
}

/** Run a mutation with busy and error state, for buttons. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();
  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setBusy(true);
      setError(undefined);
      try {
        return await fn(...args);
      } catch (e) {
        setError(e as Error);
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { run, busy, error, clearError: () => setError(undefined) };
}
