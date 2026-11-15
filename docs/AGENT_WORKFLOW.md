# Working through FaZeTime with Claude Code

This repository is a planning kit. Implementation starts only when the owner gives the coding agent a build task. Root `PROJECT_PLAN.md` contains the canonical phases 0–11. This document explains how to execute those phases without losing context or letting parallel workers create conflicting implementations.

## Start one coordinator session

1. Start Claude Code at the repository root using the owner's intended model available in that account. Worker definitions use `model: inherit`; this kit does not override the selected model with a cheaper one.
2. Record the installed Claude Code version and selected model in the working handoff. Use `/memory` to verify that root instructions loaded and `/agents` to inspect worker availability. Restart if the agents directory did not exist when the current session began.
3. Read `AGENTS.md`, `docs/STATUS.md`, and the current phase in root `PROJECT_PLAN.md`. Read only the accepted contracts, relevant decisions, and recent handoff needed for that phase.
4. Inspect the actual checkout: current commit, branch, uncommitted changes, and available files. A progress note is not evidence that code exists or tests pass.
5. Identify unresolved user/provider decisions that block this task. Continue independent work; do not silently choose a materially different feature, paid service, feed, or money rule.
6. Assign one small task with an explicit acceptance check. Check phase prerequisites before beginning implementation.

`CLAUDE.md` imports `AGENTS.md` for compatibility. Current Claude Code also supports native AGENTS.md loading, but behavior depends on version and other instruction files. The explicit import remains supported and is deduplicated. Do not add a second full copy of the instructions. Importing a large file still loads its full contents, so the root instructions should point to detailed documents rather than import every plan and research file. [1]

## Context and document ownership

| File or area | Purpose | Writer |
| --- | --- | --- |
| `PROJECT_PLAN.md` | Phase order, scope, dependencies, acceptance gates | Coordinator |
| `docs/DECISIONS.md` | Accepted choices and their rationale | Coordinator |
| `docs/STATUS.md` | Compact current progress index | Coordinator |
| `docs/HANDOFF.md` | Current restart/recovery checkpoint | Coordinator |
| `AGENTS.md`, `CLAUDE.md` | Shared durable operating instructions | Coordinator |
| API/data contracts and shared package metadata | Agreed interfaces | One explicitly assigned owner |
| Feature files and tests | Assigned implementation | Reserved worker |
| Review report | Independent findings returned to coordinator | Reviewer |

A worker returns proposed plan/decision/status changes in its result. The coordinator checks and merges them. Research alternatives, an old chat summary, and agent auto-memory do not override accepted decisions or the phase plan. If a user changes a requirement, update the affected canonical phase and decision record together, then redistribute the changed contract to active workers.

Use these evidence labels in reports:

- `USER_CONFIRMED`: the owner explicitly chose it.
- `VERIFIED_DOC`: a current primary source documents the capability.
- `MEASURED`: it was observed on the actual account/device/revision.
- `PROPOSED`: an engineering choice awaiting a relevant decision or test.
- `BLOCKED`: a necessary dependency or decision is missing.

A documented free tier is not measured account entitlement. A successful mock is not a successful provider call. A model's confidence number is not an observed accuracy rate.

## Worker roles

| Agent | Typical assignment | Ownership boundary |
| --- | --- | --- |
| `planner` | Research a gap, refine one phase, identify provider blockers | Read-only; returns proposals |
| `extension-engineer` | Twitch panel, packaged UI, operator UI, browser integration | Assigned `apps/extension/**` and/or `apps/operator/**` |
| `backend-engineer` | Python API, database, ledger, market lifecycle, presence | Assigned `services/api/**`; sole monetary mutation owner |
| `media-ai-engineer` | Twitch ingestion, transcription, evidence, proposals/resolution inputs | Assigned `services/worker/**`; no balance mutation |
| `integrations-engineer` | Chert calls and Stripe test-mode adapters | Assigned `services/calls/**` and reserved integration paths |
| `reviewer` | Compare diff and evidence with phase acceptance criteria | Read-only; does not execute tests |

The reviewer deliberately has no Bash or write tools. The coordinator or implementation worker supplies actual test output; the reviewer checks its relevance and adequacy. If fresh execution is needed, assign it explicitly to a verifier with the appropriate tools. Do not describe a shell-enabled agent as technically read-only.

Subagent files use supported YAML frontmatter: unique `name`, meaningful `description`, a narrow `tools` list, `model: inherit`, `permissionMode: default`, and bounded `maxTurns`. They do not enable bypass permissions, install hooks, account access, or automatic billing. Permissions still depend on the parent session and local policy; Markdown and a subagent description are not a sandbox. [2][3]

## Delegation packet

Every worker task should contain:

```text
Phase/task ID:
Objective:
Accepted decisions and relevant question IDs:
Base commit:
Owned paths:
Read-only dependencies:
Contract/schema version:
Inputs and fixtures:
Acceptance checks:
External actions already authorized:
Budget boundary: $0; no paid activation without owner approval.
Do not change:
Return: changed paths, revision, actual tests/results, blockers,
        contract proposals, and next integration step.
```

Give enough context to act independently. Do not paste the entire conversation. State whether the worker is planning, implementing, or reviewing. Workers must not turn a research assignment into implementation or a fixture-only task into real phone calls.

For this project, preserve confirmed choices in every relevant packet: Python API/AI; TypeScript/WXT frontend; Twitch required; demo-only funds; no platform fee; raffle odds based on the agreed cumulative settled stakes; $0 by default. Other unresolved choices remain explicit questions, not implied permission to improvise.

## Parallel work and integration

Parallelize tasks only after their shared contract is accepted. UI work against fixtures, backend invariants, and provider feasibility research can run independently. A worker depending on an unmerged schema change must receive that exact contract/revision before implementation.

Reserve paths before spawning workers. In a shared checkout, never allow two workers to edit the same migration, lockfile, API schema, package manifest, or plan file. Shared-root edits are coordinator-owned unless explicitly reassigned. Directory ownership is a coordination rule, not filesystem enforcement.

For isolated worktrees:

1. Commit or otherwise explicitly preserve the intended starting state.
2. Create or select each worker's worktree from the same recorded integration commit.
3. Verify its branch and HEAD before editing. Current Claude worktree isolation can start from the default branch rather than the coordinator's current HEAD. Do not assume it contains the coordinator's latest changes. [2]
4. Keep environment secrets outside commits and provide only required configuration locally.
5. Have the worker return the worktree path, commit(s), and test evidence.
6. Integrate one worker at a time, inspect conflicts, run relevant checks, and update the coordinator's status/handoff.
7. Do not delete a worktree with unmerged work merely because an agent turn ended.

Native agent-team features are optional and unnecessary for this workflow. Ordinary subagents with explicit ownership and a single integration coordinator are sufficient. Subagents also consume the account's usage allowance; more parallel workers do not make inference free. [2]

## Verification and phase completion

The canonical phase supplies the acceptance criteria; do not create a conflicting checklist here. For each completed task, preserve:

- Exact revision and changed paths.
- Commands/browser actions actually performed, plus meaningful result summaries.
- Which checks used fixtures and which exercised Twitch, Gemini, Stripe test mode, or Chert.
- Relevant timing, device/model configuration, callback, and failure evidence without secrets.
- Known failures and limitations, including tests not possible in the current environment.

The coordinator inspects the code and evidence, requests an independent review for important integration/ledger changes, and runs the integration checks needed for the changed boundary. Only then may the coordinator mark the phase complete. A worker's “done” message is not an acceptance gate. Fixes invalidate affected evidence and require the relevant checks again.

Do not repeatedly run expensive external tests when no change justifies them. Prefer deterministic fixtures for iteration, with a small deliberate real-provider verification at the relevant gate. Preserve a passing baseline before combining dependent features.

## Checkpoint before compaction or session replacement

Update `docs/HANDOFF.md` while the facts are still available. Keep it short enough to read at the next session:

```text
Timestamp and coordinator:
Current phase/task:
Branch and exact commit:
Uncommitted changes and their owner:
Accepted decisions changed this session:
Actual checks passed/failed/unperformed:
External accounts/windows currently verified:
Active workers, paths, and base revisions:
Blockers and unanswered questions:
Next three concrete actions:
Do not repeat / known failed approach:
```

Stop workers at clean boundaries before replacing a coordinator session where possible. Do not abandon their work or leave their ownership ambiguous. Archive detailed historical evidence separately when necessary; keep only current actionable state in STATUS/HANDOFF. Never store API keys, session tokens, raw cards, or full phone numbers in these files.

On resume, inspect files and revisions first, reconcile the handoff with reality, then continue the next incomplete gate. Do not replay the whole plan or restart completed provider spikes unless evidence is stale, the configuration changed, or the result was never actually verified.

## Compact coordinator prompt

```text
Read AGENTS.md, docs/STATUS.md, docs/HANDOFF.md, and the current
phase of PROJECT_PLAN.md. Verify the checkout and outstanding decisions.
Continue the next incomplete gate within the accepted constraints.
Use the named subagents only for independent, explicitly owned tasks.
Keep PROJECT_PLAN.md as the phase source of truth; only you update
canonical plan/state documents. Ask about decisions that materially
change scope, costs, or provider behavior. Report actual evidence and
checkpoint before ending the session.
```

## Sources

Checked 2026-11-14. Recheck version-sensitive behavior when setting up the actual CLI.

1. [Claude Code memory and instruction loading](https://code.claude.com/docs/en/memory)
2. [Claude Code custom subagents](https://code.claude.com/docs/en/sub-agents)
3. [Claude Code permissions](https://code.claude.com/docs/en/permissions)
4. [Claude Code best practices](https://code.claude.com/docs/en/best-practices)
5. [Claude Code common workflows](https://code.claude.com/docs/en/common-workflows)
