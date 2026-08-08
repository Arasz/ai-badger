# A check you have not seen fail is not a check

Before trusting a gate, test or acceptance criterion, put the defect it exists to catch in front of it and watch it go red, then take the defect away and watch it go green. A check that has only ever passed is indistinguishable from one whose comparison can produce a single answer, and that answer looks like success. This is not the TDD red step restated: red for the wrong reason is worth nothing, and a test that pins the path a previous fix patched, or that reads differently depending on which branch you are standing on, passes forever while the defect it named moves one directory over.

"I could not make it fail" is a fact about your attempt; "it cannot fail" is a claim about the system, and only a failure you produced carries you from one to the other. Re-prove the check whenever the code beneath it moves, because the failure path belongs to the pair and not to the check alone.
