from redundant.trace_ingest import load_spans
from redundant.detection import analyze
from redundant.lang_cache import LangCache, route_findings

spans = load_spans()
result = analyze(spans)
route_findings(result["findings"])

cache = LangCache()
spans_by_id = {s.span_id: s for s in spans}
written = cache.populate_from_findings(result["findings"], spans_by_id)

print(f"Spans loaded: {len(spans)}")
print(f"Findings: {len(result['findings'])}")
print(f"Total cost: ${result['total_cost_usd']}")
print(f"Wasted cost: ${result['wasted_cost_usd']} ({result['waste_pct']}%)")
print(f"Cache entries written: {written}")
for f in result["findings"]:
    print(f"  [{f.type}] {f.severity}/{f.route} count={f.count} ${f.dollar_cost} - {f.description[:70]}")
