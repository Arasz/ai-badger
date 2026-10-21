# prompt-markers extension: limited-env

Handle prompt markers from the conversation and the repository's marker reference as ordinary instructions. Apply the marker's documented priority and queue behavior yourself; no prompt hook injects the marker text or interrupts a running turn. For an interrupt marker, stop at the next safe boundary, record what is in flight, and then handle the new instruction.
