---
description: 'Azure Functions and Durable Functions conventions.'
applyTo: '**/*Function*.cs,**/*Orchestrator*.cs,**/*Activity*.cs,host.json'
---

# Azure Functions & Durable Functions

- Prefer managed identity over connection-string/key auth for bindings and outbound calls wherever the target service supports it.
- Keep orchestrator functions deterministic: no direct I/O, `DateTime.Now`, `Guid.NewGuid()`, or non-deterministic branching inside an orchestrator body — push those into activity functions.
- Give every retry loop an explicit, bounded cap (max attempts, max ignored-event count, or equivalent); an unbounded retry is a production incident waiting to happen.
- Use a sole-writer pattern per entity/aggregate to avoid concurrent-write races across orchestration instances.
- Configure `host.json` timeouts and concurrency limits deliberately rather than leaving platform defaults unexamined for a workload with real throughput.
- Log with structured, source-generated logging; correlate orchestration instance id across activity spans.
