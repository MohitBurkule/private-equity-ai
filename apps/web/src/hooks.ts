import { useEffect, useState } from "react";

export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = () => { setError(""); load().then(setData).catch((e) => setError(String(e))); };
  useEffect(reload, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, reload, setError };
}
