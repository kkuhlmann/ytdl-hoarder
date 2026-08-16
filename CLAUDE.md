# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

All shared project guidance — architecture, development commands, configuration, code style — lives
in `AGENTS.md`, so every agent reads the same source of truth. **Put new project guidance there, not
here.** This file is only for behavior specific to Claude Code.

@AGENTS.md

## Planning Mode Instructions

When in planning mode, ask clarifying questions early in the process before finalizing your plan. Use the `AskUserQuestion` tool to:
- Clarify ambiguous requirements
- Confirm assumptions about the intended behavior
- Get decisions on implementation choices (e.g., library choices, architectural patterns)
- Understand edge cases or error handling expectations

Do not make large assumptions about user intent. It's better to ask upfront than to plan incorrectly.
