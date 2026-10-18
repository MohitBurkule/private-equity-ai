import clsx from "clsx";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export const Card = ({ className, children }: { className?: string; children: ReactNode }) => (
  <div className={clsx("rounded-xl border border-line bg-panel", className)}>{children}</div>
);

export const CardHead = ({ title, hint, right }: { title: string; hint?: string; right?: ReactNode }) => (
  <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
    <div>
      <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-mut">{hint}</p>}
    </div>
    {right}
  </div>
);

export function Button({ variant = "default", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "ghost" }) {
  return (
    <button
      {...p}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-50",
        variant === "primary" && "bg-acc text-bg hover:opacity-90",
        variant === "default" && "border border-line bg-panel hover:border-acc",
        variant === "ghost" && "text-mut hover:bg-sunk hover:text-fg",
        className,
      )}
    />
  );
}

export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={clsx("min-w-0 rounded-lg border border-line bg-bg px-3 py-2 text-sm placeholder:text-mut", className)} />
);

export const Badge = ({ tone = "mut", children }: { tone?: "mut" | "ok" | "bad" | "warn" | "acc"; children: ReactNode }) => (
  <span
    className={clsx(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
      tone === "mut" && "border-line text-mut",
      tone === "ok" && "border-ok/40 text-ok",
      tone === "bad" && "border-bad/50 text-bad",
      tone === "warn" && "border-warn/50 text-warn",
      tone === "acc" && "border-acc/40 bg-acc-soft text-acc",
    )}
  >
    {children}
  </span>
);

export const Loading = () => <p className="px-5 py-8 text-center text-sm text-mut" role="status">Loading…</p>;

export const Empty = ({ children }: { children: ReactNode }) => (
  <p className="px-5 py-8 text-center text-sm text-mut">{children}</p>
);

export const ErrorLine = ({ e }: { e: string }) =>
  e ? <p role="alert" className="mx-5 my-3 rounded-lg bg-bad/10 px-3 py-2 text-sm text-bad">{e}</p> : null;

/** Page frame shared by every section: title, one-line hint, then cards. */
export const Page = ({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) => (
  <div className="mx-auto max-w-4xl space-y-5 p-6">
    <div><h1 className="text-xl font-semibold tracking-tight">{title}</h1>{hint && <p className="text-sm text-mut">{hint}</p>}</div>
    {children}
  </div>
);
