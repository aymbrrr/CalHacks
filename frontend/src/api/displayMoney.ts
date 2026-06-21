// Demo-only display estimator. The backend tracks tiny per-call API costs, which
// often round to $0.00 in the UI; this scales them to an easy-to-see monthly
// burn estimate without changing any underlying calculations.
const DEMO_MONTHLY_RUNS = 25000;
const DEMO_TEAM_MULTIPLIER = 1.35;

export function demoEstimatedUsd(rawUsd: number): number {
  if (!Number.isFinite(rawUsd) || rawUsd <= 0) return 0;
  return rawUsd * DEMO_MONTHLY_RUNS * DEMO_TEAM_MULTIPLIER;
}

export function formatDemoUsd(rawUsd: number, digits = 2): string {
  return "$" + demoEstimatedUsd(rawUsd).toFixed(digits);
}
