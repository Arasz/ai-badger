## Signal state discipline

Component state lives in **signals**; derived state is `computed()`. Never `mutate` a signal —
use `set` or `update`, and keep transformations pure. Treat `input()` values as immutable. State
never flows through hidden object mutation, so the view stays predictable. (Do not set
`ChangeDetectionStrategy.OnPush` explicitly — it is the default in Angular v22+.)
