## @stack-adjustments: azure review adjustments

Apply alongside the generic route when the diff touches Azure-hosted infrastructure or functions.

- The checklist's azure phases merge into `.ai-badger/skills/code-review-checklist/SKILL.md` at
  scaffold time — follow them there for cloud-specific gate items.
- Weight the orchestration and async patterns (checklist Phase 8) above style **when** the diff
  touches Functions, Durable Functions, or Service Bus handlers: long-running work returns an
  acknowledgment, orchestration code stays deterministic, every retry loop has a finite cap.
- Treat a missing idempotency check on a trigger-fired handler as a correctness finding — queue
  and timer triggers redeliver, and at-least-once is the delivery guarantee, not the exception.
- Verify secrets reach the runtime through configuration, not literals — a connection string in
  appsettings or code is a Phase 1 gate failure even when it works.
