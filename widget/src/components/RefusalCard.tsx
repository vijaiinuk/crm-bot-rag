import type { RefusalKind } from "../types";

const HEADINGS: Record<RefusalKind, string> = {
  restricted: "Not available with your access",
  not_found: "No answer found",
  out_of_scope: "Outside what I can help with",
};

// The message is a server-side template from the module catalogue (rule 7);
// render it as plain text.
export function RefusalCard({ kind, message }: { kind: RefusalKind; message: string }) {
  return (
    <div className={`refusal refusal-${kind}`} role="note">
      <strong>{HEADINGS[kind]}</strong>
      <p>{message}</p>
    </div>
  );
}
