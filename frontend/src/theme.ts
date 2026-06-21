/** Design tokens lifted from project/Redundant.dc.html. */
export const theme = {
  // Surfaces
  bg: "#0B0D10",
  surface: "#12161B",
  surfaceAlt: "#0F1318",
  surfaceDeep: "#0E1217",
  // Borders
  border: "#2A323C",
  borderSoft: "#1F262E",
  borderInner: "#171C22",
  borderStrong: "#3A4452",
  // Text
  text: "#E6EBF0",
  textSoft: "#D4DAE2",
  // Hot palette
  red: "#F87171",
  redSoft: "#E5A3A3",
  green: "#4ADE80",
  greenSoft: "#86EFAC",
  amber: "#F59E0B",
  amberSoft: "#FCD34D",
  blue: "#38BDF8",
  blueSoft: "#7DD3FC",
  // Agent palette (matches design prototype)
  agents: {
    orchestrator: "var(--gt-mut)",
    planner: "#C4B5FD",
    researcher_a: "#7DD3FC",
    researcher_b: "#38BDF8",
    researcher_c: "#60A5FA",
    researcher: "#7DD3FC",
    analyst: "#FCD34D",
    reporter: "#60A5FA",
    writer: "#FCD34D",
    fact_checker: "#F87171",
  } as Record<string, string>,
  // Sponsor palette
  sponsors: {
    redis: "#DC382D",
    anthropic: "#C97B5A",
    tokenco: "#E9C46A",
    terac: "#00C2A8",
  },
  // Typography
  mono: '"Geist Mono", monospace',
  sans: '"Geist", system-ui, sans-serif',
};

/** rgba() helper for the design's `hexA(hex, alpha)` shorthand. */
export function hexA(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}
