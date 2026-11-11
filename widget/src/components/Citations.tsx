import type { Citation } from "../types";

export function Citations({ items }: { items: Citation[] }) {
  return (
    <section className="sources" aria-label="Sources">
      <h3>Sources</h3>
      <ol>
        {items.map((c) => (
          <li key={c.chunk_id}>
            <span className="source-title">{c.title}</span>
            <span className="source-crumb">{c.breadcrumb}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
