# Resume coordinator prompt

Resume FaZeTime from disk, not prior chat recollection. Read AGENTS.md, docs/STATUS.md, docs/HANDOFF.md, current phase in PROJECT_PLAN.md, and decisions referenced by that phase. Inspect git status, branch, HEAD, and uncommitted changes. Identify contradictions between the handoff and repository state before editing.

State the current task, its acceptance gate, and the first concrete action. Reuse verified dependencies and account capabilities; recheck only expired or changed facts. Do not redo completed research or rewrite the architecture without new evidence. If a provider trial has expired, mark its branch blocked and follow only an owner-approved fallback.

