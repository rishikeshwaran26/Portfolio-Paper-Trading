// A tiny inline price sparkline drawn as raw SVG.
//
// Why not recharts here: the screener renders one of these per row across dozens
// of rows. recharts spins up a full ResponsiveContainer per instance, which is
// heavy at that count. A hand-drawn polyline is a few DOM nodes and scales fine.
//
// Colour follows direction: green if the series ended above where it started,
// red otherwise — the same at-a-glance read as the mini-charts on Tickertape.
export default function Sparkline({ values, width = 96, height = 32 }) {
  if (!values || values.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1; // avoid divide-by-zero on a flat line
  const stepX = width / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = i * stepX;
      // SVG y grows downward, so invert: the max value sits at the top.
      const y = height - ((v - min) / span) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  const color = up ? "var(--pos)" : "var(--neg)";
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5"
        strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
