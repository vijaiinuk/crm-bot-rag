const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdSmall = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 4 });
const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const pctFmt = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0 });

/** Dollars, with sub-cent precision for tiny per-call amounts. */
export function money(v: number): string {
  return v !== 0 && Math.abs(v) < 0.01 ? usdSmall.format(v) : usd.format(v);
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : pctFmt.format(v);
}

export function day(iso: string): string {
  return dateFmt.format(new Date(iso));
}

export function when(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : "–";
}

export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export function int(v: number): string {
  return v.toLocaleString("en-US");
}

export function humanize(s: string): string {
  return s.replace(/[_:]/g, " ");
}
