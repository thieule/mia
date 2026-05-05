import mermaid from "mermaid";
import { useEffect, useId, useRef, useState } from "react";

let _mermaidInit = false;
function ensureMermaidInit() {
  if (_mermaidInit) return;
  _mermaidInit = true;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    theme: "neutral",
  });
}

/**
 * Renders Mermaid from fenced markdown: ```mermaid ... ```
 */
export function MermaidBlock({ chart }) {
  const raw = String(chart || "").trim();
  const stableId = useId().replace(/:/g, "");
  const containerRef = useRef(null);
  const [err, setErr] = useState(null);
  const renderNonce = useRef(0);

  useEffect(() => {
    if (!raw) {
      if (containerRef.current) containerRef.current.innerHTML = "";
      setErr(null);
      return;
    }
    ensureMermaidInit();
    let cancelled = false;
    const run = ++renderNonce.current;
    const el = containerRef.current;
    if (el) el.innerHTML = "";
    setErr(null);

    const renderId = `mmd-${stableId}-${run}`;
    mermaid
      .render(renderId, raw)
      .then(({ svg, bindFunctions }) => {
        if (cancelled || run !== renderNonce.current || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        bindFunctions?.(containerRef.current);
      })
      .catch((e) => {
        if (cancelled || run !== renderNonce.current) return;
        setErr(String(e?.message || e));
      });

    return () => {
      cancelled = true;
    };
  }, [raw, stableId]);

  if (!raw) return null;
  if (err) {
    return (
      <div className="border rounded p-2 small text-danger bg-light my-2">
        <div className="fw-semibold mb-1">Mermaid</div>
        <pre className="mb-0 small text-wrap" style={{ whiteSpace: "pre-wrap" }}>
          {err}
        </pre>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="as-mermaid-chart my-2 overflow-auto"
      aria-label="Diagram"
    />
  );
}
