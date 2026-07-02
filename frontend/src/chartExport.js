// SVG style properties to inline so exported images are self-contained.
// getComputedStyle resolves inheritance and CSS variables, so inlining these
// captures the actual rendered values rather than "inherit" or var(--x).
const SVG_STYLE_PROPS = [
  "fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity",
  "stroke-dasharray", "stroke-linecap", "stroke-linejoin",
  "opacity", "font-family", "font-size", "font-weight", "font-style",
  "text-anchor", "dominant-baseline", "letter-spacing",
];

/**
 * Given a React ref (or any object with a `.current` DOM node), finds the first
 * <svg> inside it, inlines computed styles so the export is self-contained, and
 * returns { svgBlob, pngBlob } where pngBlob is a 2x-DPR rasterization.
 *
 * The style-inlining step is what prevents the PNG from coming out blank:
 * Recharts may apply colors via external CSS that doesn't travel with a
 * serialized SVG node; copying computed values onto inline style fixes that.
 */
export async function exportChartAssets(containerRef) {
  const container = containerRef.current ?? containerRef;
  if (!container) throw new Error("Chart container not mounted");

  // Bug 1 fix: querySelector("svg") returns the first SVG in DOM order, which may be
  // a 14×14 legend-icon swatch (.recharts-surface) rather than the main chart.
  // Instead, collect all .recharts-surface nodes and pick the one with the largest area.
  const surfaces = Array.from(container.querySelectorAll("svg.recharts-surface"));
  if (surfaces.length === 0) {
    const fallback = container.querySelector("svg");
    if (!fallback) throw new Error("No SVG found in chart container");
    surfaces.push(fallback);
  }
  const svgEl = surfaces.reduce((best, el) => {
    const r = el.getBoundingClientRect();
    const b = best.getBoundingClientRect();
    return r.width * r.height > b.width * b.height ? el : best;
  });

  // Read the real rendered pixel size from the live node before cloning.
  const { width, height } = svgEl.getBoundingClientRect();
  const w = Math.round(width);
  const h = Math.round(height);

  // Clone so we can mutate without touching the live DOM.
  const clone = svgEl.cloneNode(true);

  // Walk originals and clone in lock-step to copy computed → inline styles.
  const origNodes  = [svgEl,  ...svgEl.querySelectorAll("*")];
  const cloneNodes = [clone, ...clone.querySelectorAll("*")];

  for (let i = 0; i < origNodes.length; i++) {
    if (origNodes[i].nodeType !== Node.ELEMENT_NODE) continue;
    const computed = window.getComputedStyle(origNodes[i]);
    for (const prop of SVG_STYLE_PROPS) {
      const val = computed.getPropertyValue(prop);
      if (val) cloneNodes[i].style.setProperty(prop, val);
    }
  }

  // Bug 2 fix: Recharts sets style="width:100%;height:100%" on the SVG root.
  // cloneNode copies that verbatim, and the percentage CSS overrides explicit width/height
  // attributes when the SVG is loaded as a standalone blob — leaving intrinsic size
  // undefined, so rasterization produces a tiny or empty canvas. Strip the percentages
  // and set unambiguous pixel dimensions plus a matching viewBox.
  clone.style.removeProperty("width");
  clone.style.removeProperty("height");
  clone.setAttribute("width",   String(w));
  clone.setAttribute("height",  String(h));
  clone.setAttribute("viewBox", `0 0 ${w} ${h}`);
  clone.setAttribute("xmlns",   "http://www.w3.org/2000/svg");

  const svgStr  = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });

  // Rasterize at 2× device pixels for a crisp PNG.
  const DPR = 2;
  const pngBlob = await new Promise((resolve, reject) => {
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const canvas = document.createElement("canvas");
      canvas.width  = w * DPR;
      canvas.height = h * DPR;
      const ctx = canvas.getContext("2d");
      ctx.scale(DPR, DPR);
      ctx.drawImage(img, 0, 0, w, h);
      canvas.toBlob(blob => {
        if (blob) resolve(blob);
        else reject(new Error("canvas.toBlob returned null"));
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to rasterize chart SVG"));
    };
    img.src = url;
  });

  return { svgBlob, pngBlob };
}

/** RFC 4180-compliant CSV row serializer. */
export function toCsvRow(values) {
  return values.map(v => {
    const s = String(v ?? "");
    return /[,"\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",");
}
