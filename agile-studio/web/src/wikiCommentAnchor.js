/** Anchors a span in Markdown source (quote + prefix/suffix strategy, optional offsets). */

const CTX = 72;

export function buildWikiTextAnchor(fullText, start, end) {
  const len = typeof fullText === "string" ? fullText.length : 0;
  const s = Math.max(0, Math.min(Number(start) || 0, len));
  const e = Math.max(s, Math.min(Number(end) || 0, len));
  const quote = fullText.slice(s, e);
  const prefix = fullText.slice(Math.max(0, s - CTX), s);
  const suffix = fullText.slice(e, Math.min(len, e + CTX));
  return {
    quote,
    prefix,
    suffix,
    text_offset_start: s,
    text_offset_end: e,
  };
}

function contextMatchesAround(fullText, quote, absStart, prefix, suffix) {
  const segP = fullText.slice(Math.max(0, absStart - CTX), absStart);
  const segS = fullText.slice(
    absStart + quote.length,
    Math.min(fullText.length, absStart + quote.length + CTX),
  );
  const pTail = prefix ? prefix.slice(Math.max(0, prefix.length - CTX)) : "";
  const sHead = suffix ? suffix.slice(0, Math.min(suffix.length, CTX)) : "";
  const pOk = !prefix || segP.endsWith(pTail);
  const sOk = !suffix || segS.startsWith(sHead);
  return pOk && sOk;
}

/**
 * Returns `{ start, end, orphaned }` — if `quote` cannot be located in `fullText`, `orphaned` is true.
 */
export function resolveWikiTextAnchor(fullText, anchor) {
  const text = typeof fullText === "string" ? fullText : "";
  const quote = anchor?.quote || "";
  const prefix = anchor?.prefix ?? null;
  const suffix = anchor?.suffix ?? null;
  const o0 = anchor?.text_offset_start;
  const o1 = anchor?.text_offset_end;

  if (!quote) {
    return { start: 0, end: 0, orphaned: true };
  }

  const n = text.length;
  if (
    typeof o0 === "number" &&
    typeof o1 === "number" &&
    o0 >= 0 &&
    o1 <= n &&
    o0 < o1 &&
    text.slice(o0, o1) === quote
  ) {
    return { start: o0, end: o1, orphaned: false };
  }

  const candidates = [];
  let pos = 0;
  while (pos <= n) {
    const i = text.indexOf(quote, pos);
    if (i === -1) break;
    if (prefix == null && suffix == null) {
      candidates.push(i);
    } else if (contextMatchesAround(text, quote, i, prefix || "", suffix || "")) {
      candidates.push(i);
    }
    pos = i + 1;
  }

  if (candidates.length === 1) {
    const i = candidates[0];
    return { start: i, end: i + quote.length, orphaned: false };
  }

  if (candidates.length > 1 && typeof o0 === "number") {
    let best = candidates[0];
    let bestD = Math.abs(best - o0);
    for (let k = 1; k < candidates.length; k += 1) {
      const c = candidates[k];
      const d = Math.abs(c - o0);
      if (d < bestD) {
        best = c;
        bestD = d;
      }
    }
    return { start: best, end: best + quote.length, orphaned: false };
  }

  if (candidates.length > 1) {
    const i = candidates[0];
    return { start: i, end: i + quote.length, orphaned: false };
  }

  return { start: 0, end: 0, orphaned: true };
}
