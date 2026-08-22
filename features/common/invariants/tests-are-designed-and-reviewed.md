# Tests are designed before they are written, and judged after

A test list comes out of the acceptance criteria before the first test is written — each row naming the failure mode it targets and the mutation that will prove it real, via `design-tests` — and a change that adds or alters tests is not done until `review-tests` has asked whether that suite could have gone red. Green is the floor, not the evidence.
