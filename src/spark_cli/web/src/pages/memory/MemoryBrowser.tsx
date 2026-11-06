import { useEffect, useState } from "react";
import { memoryReview, type FactPage, type ReviewPage } from "@/lib/memoryReview";

export function MemoryBrowser() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [after, setAfter] = useState(0);
  const [facts, setFacts] = useState<FactPage | null>(null);
  const [reviewAfter, setReviewAfter] = useState("");
  const [reviews, setReviews] = useState<ReviewPage | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    memoryReview.facts(search, after, controller.signal).then((page) => {
      if (!controller.signal.aborted) { setFacts(page); setErrors((current) => ({ ...current, facts: "" })); }
    }).catch((err: unknown) => { if (!controller.signal.aborted) setErrors((current) => ({ ...current, facts: String(err) })); });
    return () => controller.abort();
  }, [search, after, retry]);
  useEffect(() => {
    const controller = new AbortController();
    memoryReview.reviews(reviewAfter, controller.signal).then((page) => {
      if (!controller.signal.aborted) { setReviews(page); setErrors((current) => ({ ...current, reviews: "" })); }
    }).catch((err: unknown) => { if (!controller.signal.aborted) setErrors((current) => ({ ...current, reviews: String(err) })); });
    return () => controller.abort();
  }, [reviewAfter, retry]);
  useEffect(() => {
    if (selected === null) return;
    const controller = new AbortController();
    memoryReview.review(selected, controller.signal).then((review) => {
      if (!controller.signal.aborted) { setContent(review.content); setErrors((current) => ({ ...current, detail: "" })); }
    }).catch((err: unknown) => { if (!controller.signal.aborted) setErrors((current) => ({ ...current, detail: String(err) })); });
    return () => controller.abort();
  }, [selected, retry]);
  return <section className="space-y-3 rounded-xl border border-border p-4">
    <h2>Local holographic facts</h2>
    <p className="text-sm text-muted-foreground">Read-only local search. Optional external providers are not queried. Missing provenance is shown as unknown.</p>
    <form onSubmit={(event) => { event.preventDefault(); setFacts(null); setAfter(0); setSearch(query); setRetry((n) => n + 1); }}>
      <input aria-label="Search local facts" maxLength={200} value={query} onChange={(event) => setQuery(event.target.value)} className="rounded border p-2" />
      <button type="submit">Search</button>
    </form>
    {Object.entries(errors).filter(([, message]) => message).map(([kind, message]) => <p role="alert" key={kind}>{message} <button onClick={() => setRetry((n) => n + 1)}>Retry {kind}</button></p>)}
    {!facts && <p>Loading facts…</p>}
    {facts?.status === "missing" && <p>No local holographic store exists in this profile.</p>}
    {facts?.status === "unavailable" && <p>{facts.message}</p>}
    {facts?.status === "available" && facts.items.length === 0 && <p>No matching facts.</p>}
    {facts?.items.map((fact) => <details key={fact.fact_id}>
      <summary className="break-words">{fact.content.slice(0, 160)}</summary>
      <p className="whitespace-pre-wrap break-words">{fact.content}</p>
      {fact.content_truncated && <p>Content exceeds the 16,384 character browsing limit; showing the beginning.</p>}
      <p>Source: {fact.source || "unknown"} · Category: {fact.category || "unknown"} · Created: {fact.created_at || "unknown"} · Updated: {fact.updated_at || "unknown"}</p>
    </details>)}
    {facts?.next_after != null && <button onClick={() => { setAfter(facts.next_after!); setFacts(null); }}>Next facts</button>}
    {after > 0 && <button onClick={() => { setAfter(0); setFacts(null); }}>First facts</button>}
    <h2>Explicit Dream reviews</h2>
    <p>Dream runs only when explicitly invoked or scheduled. Browsing does not run Dream or forget facts.</p>
    {reviews && reviews.status !== "available" && <p>Dream reviews: {reviews.status}.</p>}
    {reviews?.status === "available" && reviews.items.length === 0 && <p>No review files on this page.</p>}
    {reviews?.items.map((review) => <button className="block" key={review.name} onClick={() => { setSelected(review.name); setContent(""); }}>{review.name}</button>)}
    {reviews?.next_after && <button onClick={() => setReviewAfter(reviews.next_after!)}>Next reviews</button>}
    {reviewAfter && <button onClick={() => setReviewAfter("")}>First reviews</button>}
    {selected && <article aria-label="Dream review"><h3>{selected}</h3><pre className="whitespace-pre-wrap break-words">{content || "Loading review…"}</pre><button onClick={() => setSelected(null)}>Close review</button></article>}
  </section>;
}
