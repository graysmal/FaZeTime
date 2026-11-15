# FaZeTime — agent execution kit

Planning package prepared November 14, 2026 (America/Chicago). No application has been implemented, no credentials have been tested, and no deployment or integration is claimed working.

Copy this directory's contents, including `.claude/`, into the root of a new GitHub repository. Use uppercase `AGENTS.md` and `CLAUDE.md`; do not create a second lowercase copy that can drift. Select your intended Opus model in Claude Code. Agent definitions inherit the selected model.

## Start here

1. Read [PROJECT_PLAN.md](PROJECT_PLAN.md). Its phases are the authoritative scope and completion gates.
2. Give Claude [prompts/START_HERE.md](prompts/START_HERE.md). It begins with the unresolved phase-0 questions, not an invented hardware setup or deadline.
3. Verify Claude loaded [AGENTS.md](AGENTS.md) through [CLAUDE.md](CLAUDE.md), and that the custom agents appear in `/agents`.
4. Have the coordinator complete one phase gate at a time and maintain [STATUS](docs/STATUS.md), [DECISIONS](docs/DECISIONS.md), and [HANDOFF](docs/HANDOFF.md).

The kit contains specifications and reusable agent instructions, not a runnable scaffold. Paths such as `services/api/` describe future implementation locations. Commands for application startup/testing must be created and verified by the implementation agents, then recorded; they are intentionally not fabricated here.

## Approved direction

- Hackathon demonstration with test funds only; one Twitch channel and one unresolved market at a time.
- Python API and AI workers; TypeScript/React Chrome extension and operator dashboard.
- Team-owned prerecorded video broadcast through OBS to Twitch. Final acceptance requires analysis of media actually delivered by Twitch.
- Binary pool payouts without a fee. Raffle probability follows cumulative eligible wager amount in the current stream.
- Automatic AI proposal/resolution is the target, conditional on demonstrated quality; operator approval remains available.
- Pi with 16 GB RAM, four laptops, two iPhones; exact hardware, challenge, and remaining build time are phase-0 decisions.
- Spend $0 by default. Paid services, top-ups, or billing activation that can charge money need a concrete owner decision. Chert sponsor usage lasts 24 hours, exact start/end and limits unverified.
- Twitch capture is mandatory; manual FaceTime handoff is an accepted call fallback.

## Reading map

| File | When to read |
|---|---|
| [AGENTS.md](AGENTS.md) | Every coding session; concise stable constraints |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | Current phase and dependencies |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Service boundaries, extension, persistence, topology |
| [CONTRACTS](docs/CONTRACTS.md) | Before parallel implementation of API/UI/workers |
| [INGESTION](docs/INGESTION.md) | Twitch acquisition, clocks, discontinuities |
| [AI_PIPELINE](docs/AI_PIPELINE.md) | Speech, visual evidence, proposal and resolution |
| [ECONOMICS](docs/ECONOMICS.md) | Ledger, pool payout, raffle math |
| [INTEGRATIONS](docs/INTEGRATIONS.md) | Stripe, Chert, LiveKit, bookie |
| [COST_AND_CAPABILITIES](docs/COST_AND_CAPABILITIES.md) | Free-tier/account and hardware verification |
| [TEST_STRATEGY](docs/TEST_STRATEGY.md) | Evidence needed to close a phase |
| [RISKS](docs/RISKS.md) | Logistics blockers and stop conditions |
| [DEMO_RUNBOOK](docs/DEMO_RUNBOOK.md) | Rehearsal, reset, recovery, presentation |
| [AGENT_WORKFLOW](docs/AGENT_WORKFLOW.md) | Delegation, worktrees, context management |
| [SOURCE_MAP](docs/SOURCE_MAP.md) | Source documents, corrections, research provenance |

All technical detail is subordinate to the phase plan and recorded owner decisions. Research is dated guidance, not proof that an API key, line entitlement, package version, model, or machine works. Keep verified capability records separate from proposed design.

