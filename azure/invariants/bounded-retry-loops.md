# Bounded retry loops

Every retry loop (Durable Functions orchestration, background poller, webhook re-delivery) needs an explicit, finite cap on attempts or ignored events. An unbounded retry loop is a standing availability/cost risk; always be able to answer "what stops this loop" before merging one.
