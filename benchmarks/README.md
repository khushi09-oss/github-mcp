# Offline artifact evaluation

Run from this checkout with the locked analysis extra:

```powershell
uv run --locked --extra analysis python benchmarks/evaluate.py --repeats 3
```

The command emits JSON and exits nonzero for a failed worker or missing labelled
graph relation. Six synthetic Python/JavaScript/TypeScript files contain three
labelled cross-file calls and top-level exceptions that must never run.
The fixture is a fixed input, never imported or executed. Each trial starts a new
isolated Python process, limits memory to 1 GiB and execution to 45 seconds, and
denies Python network/process audit events. Credentials/provider keys are excluded.
Parser caches are fresh; OS/library caches and machine load are uncontrolled.

Both arms use the same fixture bytes and synthetic snapshot identity. Retrieval
calls the actual line-reading function with in-memory GitHub responses; graph
calls the pinned extractor/normalizer with 50 nodes/100 edges. No GitHub, model,
or end-to-end client latency is measured. Synthetic source URLs are shape checks,
not working GitHub citations. Workers always run retrieval then graph per repeat.

Results retain every failed trial and wall time including process startup/imports.
Payload bytes count JSON structured data only, excluding MCP framing and mirrored
text. Retrieval reports whether labelled callsite lines were supplied, not whether
a model understood them. Graph checks caller/callee labels, paths and callsite
evidence. These are different outputs; byte size is not utility or token savings.
Model, tokens and provider cost are null because evaluation is offline-only.

## Recorded local observation

Windows/Python 3.12.13, graphifyy 0.9.100, three fresh-process trials per arm:

| Arm | Failures | Median seconds | Structured bytes | Label checks |
| --- | ---: | ---: | ---: | --- |
| Retrieval | 0/3 | 2.7675 | 3,095 | 3/3 callsite lines supplied each run |
| Graph | 0/3 | 4.2346 | 8,629 | 3/3 labelled calls found each run |

Fixture SHA-256: `b5f83a2f746ecba7b36167b03eb3b731be8294a5e38225efcd7eefddea579899`.
Graph reported no fixture omissions/failures, but completeness remains false.
This tiny, hand-labelled fixture does not measure semantic answer quality,
production accuracy, client compliance, tokens or financial savings. It provides
no evidence that the graph is faster or cheaper. Repeated model comparison was
explicitly excluded by the offline-only evaluation decision.
