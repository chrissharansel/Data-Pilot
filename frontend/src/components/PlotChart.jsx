import { useEffect, useRef, useState } from "react";

// plotly.js is loaded on first use so the main bundle stays small.
export default function PlotChart({ figure, title }) {
  const ref = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let plotly;
    let cancelled = false;
    import("plotly.js-basic-dist-min")
      .then((m) => {
        if (cancelled || !ref.current) return;
        plotly = m.default;
        const layout = {
          ...figure.layout,
          title: { text: title, font: { size: 15 }, x: 0.02 },
          autosize: true,
          margin: { l: 56, r: 16, t: 44, b: 44 },
          font: { family: "Source Sans 3, system-ui, sans-serif", size: 13, color: "#1d2233" },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          legend: { orientation: "h", y: -0.18 },
        };
        plotly.newPlot(ref.current, figure.data, layout, { responsive: true, displaylogo: false });
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      if (plotly && ref.current) plotly.purge(ref.current);
    };
  }, [figure, title]);

  if (failed) return <p className="muted">Chart could not be loaded.</p>;
  return <div ref={ref} className="plot" role="img" aria-label={title} />;
}
