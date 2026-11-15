"""Provider adapters (P6+). Stdlib only, no database access, no money authority.

Adapters translate between a provider's wire format and typed facts. Only the backend's domain
commands (inside BEGIN IMMEDIATE) move balances or append ledger rows.
Stripe is TEST MODE ONLY: live keys and live-mode events are refused.
"""
