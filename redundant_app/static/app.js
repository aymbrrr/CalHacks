let currentRunId = null;

const $ = (id) => document.getElementById(id);

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function money(value) {
  return `$${Number(value || 0).toFixed(4)}`;
}

async function runDemo() {
  $("runDemo").disabled = true;
  $("runDemo").textContent = "Running...";
  try {
    const result = await jsonFetch("/api/runs/start", {
      method: "POST",
      body: JSON.stringify({ mode: "redundant" }),
    });
    currentRunId = result.run_id;
    renderReport(result.report);
    await refreshEvents();
    await refreshDataset();
  } finally {
    $("runDemo").disabled = false;
    $("runDemo").textContent = "Run Demo";
  }
}

async function refreshEvents() {
  if (!currentRunId) return;
  const events = await jsonFetch(`/api/runs/${currentRunId}/events`);
  $("events").innerHTML = events
    .map((event) => {
      const warn = event.decision === "BLOCK_OR_WARN" ? " warn" : "";
      return `<div class="event">
        <strong><span class="decision${warn}">${event.decision}</span> ${event.tool_name}</strong>
        <small>${event.agent_id} · ${event.cacheability} · ${event.event_id}</small>
        <small>${event.explanation}</small>
        <small>Saved ${money(event.saved_cost_usd)} / ${event.saved_tokens} tokens</small>
      </div>`;
    })
    .join("");
}

async function refreshDataset() {
  const stats = await jsonFetch("/api/dataset/stats");
  const items = await jsonFetch("/api/dataset/labelable?limit=6");
  $("labelItems").textContent = stats.total_items || 0;
  $("llmItems").textContent = (stats.by_call_kind && stats.by_call_kind.llm) || 0;
  $("datasetPreview").textContent = JSON.stringify(items, null, 2);
}

function renderReport(report) {
  $("runId").textContent = report.run_id;
  $("attempted").textContent = report.attempted_calls;
  $("saved").textContent = money(report.saved_cost_usd);
  $("labelItems").textContent = report.dataset.labelable_items_generated;
  $("llmItems").textContent = report.dataset.pure_llm_items_generated;
  $("clusters").innerHTML = report.clusters
    .map((cluster) => `<div class="item">
      <strong>${cluster.label}</strong>
      <span>${cluster.calls} calls · ${cluster.unique_needed} needed · saved ${money(cluster.saved_cost_usd)}</span>
    </div>`)
    .join("");
  $("fixes").innerHTML = report.fixes
    .map((fix) => `<div class="item">
      <strong>${fix.title}</strong>
      <span>${fix.description}</span>
    </div>`)
    .join("");
}

$("runDemo").addEventListener("click", runDemo);
$("refreshDataset").addEventListener("click", refreshDataset);
refreshDataset().catch(() => {});
