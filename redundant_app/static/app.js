let currentRunId = null;
let currentAnnotationItem = null;

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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function preview(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value || {});
  return text.length > 220 ? `${text.slice(0, 220)}...` : text;
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
  $("labeledItems").textContent = stats.labeled_items || 0;
  $("datasetPreview").textContent = JSON.stringify(items, null, 2);
  renderDatasetHealth(stats);
  await refreshAnnotations();
  await refreshEval();
}

async function ingestData() {
  $("ingestButton").disabled = true;
  $("ingestStatus").textContent = "Importing...";
  try {
    const result = await jsonFetch("/api/dataset/ingest", {
      method: "POST",
      body: JSON.stringify({ text: $("ingestText").value }),
    });
    $("ingestStatus").textContent = `${result.ingest.accepted} accepted, ${result.ingest.duplicates} duplicates, ${result.ingest.rejected} rejected`;
    await refreshDataset();
  } catch (error) {
    $("ingestStatus").textContent = error.message;
  } finally {
    $("ingestButton").disabled = false;
  }
}

async function refreshAnnotations() {
  const queue = await jsonFetch("/api/annotations/queue?limit=1");
  renderAnnotation(queue[0] || null);
  const stats = await jsonFetch("/api/dataset/stats");
  $("queueStatus").textContent = `${stats.unlabeled_items || 0} pending`;
}

async function submitCurrentLabel() {
  if (!currentAnnotationItem) return;
  $("labelButton").disabled = true;
  try {
    await jsonFetch("/api/annotations/label", {
      method: "POST",
      body: JSON.stringify({
        pair_id: currentAnnotationItem.pair_id,
        final_label: $("finalLabel").value,
        confidence: $("labelConfidence").value,
        short_reason: $("labelReason").value,
      }),
    });
    $("labelReason").value = "";
    await refreshDataset();
  } catch (error) {
    $("annotationItem").innerHTML += `<p><strong>${escapeHtml(error.message)}</strong></p>`;
  } finally {
    $("labelButton").disabled = false;
  }
}

async function refreshEval() {
  const evaluation = await jsonFetch("/api/eval");
  renderEvaluation(evaluation);
}

function renderDatasetHealth(stats) {
  $("datasetHealth").innerHTML = [
    ["Status", stats.dataset_health || "unknown"],
    ["Total items", stats.total_items || 0],
    ["Labeled", stats.labeled_items || 0],
    ["Unlabeled", stats.unlabeled_items || 0],
    ["Pure LLM", stats.pure_llm_items || 0],
    ["Pure LLM labeled", stats.pure_llm_labeled_items || 0],
    ["Kinds", JSON.stringify(stats.by_call_kind || {})],
    ["Labels", JSON.stringify(stats.by_label_hint || {})],
  ]
    .map(([label, value]) => `<div class="item"><strong>${label}</strong><span>${value}</span></div>`)
    .join("");
}

function renderAnnotation(item) {
  currentAnnotationItem = item;
  if (!item) {
    $("annotationItem").textContent = "No unlabeled items.";
    $("labelButton").disabled = true;
    return;
  }
  $("labelButton").disabled = false;
  const hint = item.review_prompt && item.review_prompt.label_hint;
  if (hint && [...$("finalLabel").options].some((option) => option.value === hint)) {
    $("finalLabel").value = hint;
  }
  const newCall = item.new_call || {};
  const cached = item.candidate_cached_call || {};
  const signals = item.runtime_signals || {};
  $("annotationItem").innerHTML = `
    <strong>${escapeHtml(item.pair_id)}</strong>
    <p><code>${escapeHtml(newCall.call_kind || "unknown")}</code> ${escapeHtml(newCall.tool_name || "none")} · hint ${escapeHtml(hint || "unclear")}</p>
    <p><strong>New</strong> ${escapeHtml(preview(newCall.prompt_or_args))}</p>
    <p><strong>Cached</strong> ${escapeHtml(preview(cached.prompt_or_args))}</p>
    <p>similarity ${escapeHtml(signals.redis_similarity ?? "n/a")} · exact ${escapeHtml(Boolean(signals.exact_key_match))}</p>
  `;
}

function renderEvaluation(evaluation) {
  const raw = evaluation.raw_redis_policy || {};
  const gated = evaluation.terac_gated_policy || {};
  $("evaluation").innerHTML = [
    ["Labeled", evaluation.labeled_items || 0],
    ["Unlabeled", evaluation.unlabeled_items || 0],
    ["Pure LLM labeled", evaluation.pure_llm_labeled_items || 0],
    ["Hint agreement", evaluation.hint_agreement_rate || 0],
    ["Raw unsafe reuse", `${raw.unsafe_reuses || 0}/${raw.reuse_candidates || 0}`],
    ["Terac allow", gated.allow_reuse || 0],
    ["Terac refresh", gated.refresh_then_reuse || 0],
    ["Terac block", gated.block_reuse || 0],
    ["Final labels", JSON.stringify(evaluation.label_distribution || {})],
  ]
    .map(([label, value]) => `<div class="item"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></div>`)
    .join("");
}

function renderReport(report) {
  $("runId").textContent = report.run_id;
  $("attempted").textContent = report.attempted_calls;
  $("saved").textContent = money(report.saved_cost_usd);
  $("labelItems").textContent = report.dataset.labelable_items_generated;
  $("llmItems").textContent = report.dataset.pure_llm_items_generated;
  $("labeledItems").textContent = report.dataset.labeled_items ?? $("labeledItems").textContent;
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
$("ingestButton").addEventListener("click", ingestData);
$("labelButton").addEventListener("click", submitCurrentLabel);
refreshDataset().catch(() => {});
