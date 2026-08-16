import { defineConfig, globalIgnores } from "eslint/config"
import nextVitals from "eslint-config-next/core-web-vitals"

// Rules introduced by eslint-plugin-react-hooks v7, which turns the whole
// React Compiler rule set on as errors by default. eslint-config-next@13
// shipped react-hooks v4, so none of these were ever enforced here.
//
// They were held at "warn" so the toolchain upgrade stayed reviewable on its
// own — 78 findings on arrival. Anything not listed below keeps the config
// default of "error", so removing a rule from this array is how it gets
// promoted.
//
// All four rules that ever had findings are now clear and back at "error":
// `purity` (1) and `immutability` (2) were the cheap start, then `refs`
// (23 / 4 files), then `set-state-in-effect` — 51 -> 25 -> 5 -> 0 across
// batches A-G. The last five were effects that legitimately seed local state
// from a prop or an external source and then let handlers write it: four carry
// a targeted disable with a reason, and TagInput's was simply deleted.
//
// Every rule still listed has 0 findings in the current tree, so this array is
// now a regression net rather than a backlog. `set-state-in-render` was the last
// rule with a clean 0-count that could be promoted for free; it was moved to
// `error` too. What remains here has never had a finding in this codebase — held
// at `warn` only so a future violation surfaces as a warning to triage rather
// than an immediate hard build break.
const reactCompilerRules = [
  "component-hook-factories",
  "config",
  "error-boundaries",
  "gating",
  "globals",
  "incompatible-library",
  "preserve-manual-memoization",
  "static-components",
  "unsupported-syntax",
  "use-memo",
]

export default defineConfig([
  ...nextVitals,
  {
    rules: Object.fromEntries(reactCompilerRules.map((r) => [`react-hooks/${r}`, "warn"])),
  },
  {
    // eslint-config-next configures an import resolver
    // (settings["import/resolver"], typescript: alwaysTryTypes) but enables no
    // rule that consumes it, so a broken "@/..." path was caught only by tsc.
    // This turns that already-paid-for resolution into an actual lint guard.
    // Enabled at 0 findings across the tree.
    //
    // NB: the rule ships via eslint-plugin-import, a TRANSITIVE dep of
    // eslint-config-next -- it is not in package.json. If a future
    // eslint-config-next drops it, this line fails loudly ("Could not find
    // plugin") rather than silently going unchecked.
    rules: { "import/no-unresolved": "error" },
  },
  {
    // Three more eslint-plugin-import rules, same transitive-dep source and same
    // fail-loud caveat as import/no-unresolved above. All three measured to 0
    // findings before promotion (count-first): each was forced on across the
    // whole tree via `eslint . --rule` and parsed per-ruleId.
    //
    //   no-cycle       0 findings, no source change. It walks the import graph,
    //                  so it is by far the expensive one: measured here it adds
    //                  ~40-45s of CPU (~16s -> ~50-58s wall) and dominates the
    //                  lint run. Absolute numbers are inflated by this host's
    //                  memory pressure -- the ratio is the point, ~2.5x the
    //                  baseline lint CPU. Kept anyway: the guard is worth it.
    //   no-duplicates  6 findings / 3 files, all trivially mergeable duplicate
    //                  import statements from one module (heroicons/24/outline
    //                  x2, @/app/types/SubscriptionsOptions). Merged, then 0.
    //   named          1 finding, a type-only-export false positive:
    //                  Waveform.tsx imported `Region` (used only as a type) from
    //                  the runtime regions.js, which exports no VALUE named
    //                  Region -- tsc passed off the .d.ts, this rule checks the
    //                  runtime module. Fixed correctly with an inline `type`
    //                  import (`{ type Region }`), which is both accurate and
    //                  drops the name from the runtime import; re-measured to 0.
    rules: {
      "import/no-cycle": "error",
      "import/no-duplicates": "error",
      "import/named": "error",
    },
  },
  {
    // app/_hooks/useFetchEffect.ts takes (callback, deps) exactly like
    // useEffect, so exhaustive-deps can check its dep arrays too. Without this
    // the hook's hand-written dep lists are the one unguarded thing about it —
    // a captured variable left out of `deps` silently fetches with stale
    // arguments. Severity stays "warn", as eslint-config-next sets it.
    //
    // The cost: exhaustive-deps then treats the callback like a useEffect body
    // and rejects an inline `async` arrow. Pass a named async useCallback by
    // reference, or a non-async arrow returning a promise. See the hook's own
    // docblock.
    rules: {
      "react-hooks/exhaustive-deps": ["warn", { additionalHooks: "^useFetchEffect$" }],
    },
  },
  // Default ignores of eslint-config-next, restated because supplying any
  // globalIgnores replaces them.
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
])
