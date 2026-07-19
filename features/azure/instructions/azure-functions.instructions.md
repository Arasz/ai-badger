---
description: 'Azure Functions and Durable Functions conventions.'
applyTo: '**/*Function*.cs,**/*Orchestrator*.cs,**/*Activity*.cs,**/functions/**/*.ts,**/functions/**/*.js,**/*[Oo]rchestrator*.ts,**/*[Oo]rchestrator*.js,**/host.json,**/local.settings.json'
---

# Azure Functions & Durable Functions

- Prefer managed identity over connection-string/key auth for bindings and outbound calls wherever the target service supports it.
- Keep orchestrator functions deterministic: no direct I/O, no current-time or random/GUID calls (`DateTime.Now`, `Guid.NewGuid()`, `Date.now()`, `crypto.randomUUID()`), and no non-deterministic branching inside an orchestrator body — push those into activity functions, or use the durable SDK's deterministic equivalents (`CurrentUtcDateTime`, `newGuid`, `context.df.currentUtcDateTime`).
- Give every retry loop an explicit, bounded cap (max attempts, max ignored-event count, or equivalent); an unbounded retry is a production incident waiting to happen.
- Use a sole-writer pattern per entity/aggregate to avoid concurrent-write races across orchestration instances.
- Configure `host.json` timeouts and concurrency limits deliberately rather than leaving platform defaults unexamined for a workload with real throughput.
- Log structurally, using the platform's lowest-overhead logging path (source-generated `[LoggerMessage]` in .NET, the injected `context`/`InvocationContext` logger in Node); correlate orchestration instance id across activity spans.
