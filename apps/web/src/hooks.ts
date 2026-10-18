import { useEffect, useState } from "react";

export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  // loading stays true until the first answer lands, so a screen can tell "still fetching" from "nothing here".
  const [loading, setLoading] = useState(true);
  const reload = () => {
    setError(""); setLoading(true);
    load().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false));
  };
  useEffect(reload, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, loading, reload, setError };
}
