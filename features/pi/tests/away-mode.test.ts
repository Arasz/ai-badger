import { describe, expect, test } from "bun:test";
import { createAwayState } from "../adjustments/adapter/hook-bridge.ts";

describe("away mode is session-scoped state with no persistence", () => {
  test("default off: an env without the flag starts disarmed", () => {
    expect(createAwayState({}).armed()).toBe(false);
  });

  test("the env flag arms it at session start", () => {
    expect(createAwayState({ AI_BADGER_PI_AWAY: "1" }).armed()).toBe(true);
  });

  test("toggling flips the state and reports the new value", () => {
    const state = createAwayState({});
    expect(state.toggle()).toBe(true);
    expect(state.armed()).toBe(true);
    expect(state.toggle()).toBe(false);
    expect(state.armed()).toBe(false);
  });

  test("two sessions do not share arming — the state is not a module global", () => {
    const one = createAwayState({});
    const two = createAwayState({});
    one.toggle();
    expect(one.armed()).toBe(true);
    expect(two.armed()).toBe(false);
  });

  test("nothing is persisted: a state rebuilt from the same env has forgotten the toggle", () => {
    const env = {};
    const first = createAwayState(env);
    first.toggle();
    expect(createAwayState(env).armed()).toBe(false);
  });
});
