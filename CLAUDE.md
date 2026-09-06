# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Shared project guidance lives in `AGENTS.md` and `.claude/rules/`, so every agent reads the same
source of truth. `AGENTS.md` carries what applies everywhere — architecture map, access control, the
task orchestrator, code style — and `.claude/rules/*.md` carry the area-specific deep dives, each
scoped by `paths:` frontmatter so Claude Code loads it only when you open a matching file.
**Put new project guidance in whichever of those matches its scope, not here** (`AGENTS.md` has a
table saying which is which). This file is only for behavior specific to Claude Code.

@AGENTS.md

## Planning Mode Instructions

When in planning mode, ask clarifying questions early in the process before finalizing your plan. Use the `AskUserQuestion` tool to:
- Clarify ambiguous requirements
- Confirm assumptions about the intended behavior
- Get decisions on implementation choices (e.g., library choices, architectural patterns)
- Understand edge cases or error handling expectations

Do not make large assumptions about user intent. It's better to ask upfront than to plan incorrectly.
