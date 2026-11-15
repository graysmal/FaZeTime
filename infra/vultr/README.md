# Vultr (DECISIONS D34): remote speech-to-text VM with an enforced budget

The owner's limit is **$100 total including tax**, and the account holds $100 of credit. A card is on file, and Vultr has no self-service spending cap. So `budget_guard.py` enforces a pre-tax usage stop of **$85**. At worst-case Texas tax (8.25% on 80% of the invoice) that is about $90.61. It also tears everything down at the **deadline, Sun 2026-11-15 18:00 CT** (`DEADLINE_UTC`).

| Item | Value |
|---|---|
| VM | `fazetime-asr`, plan `voc-c-8c-16gb-150s-amd` (8 dedicated AMD EPYC Genoa vCPUs, 16 GB), region `dfw`, $0.219/h, tag `fazetime` |
| Access | Tailscale MagicDNS `fazetime-asr`. The public firewall group `fazetime-asr` allows only TCP 22 from the venue IP. No backups, snapshots, DDoS add-on or IPv6 |
| Guards | Pi: `~/fazetime/infra/vultr/start_guard.sh`, plus crontab `@reboot`; log in `~/fazetime-data/vultr-guard.log`. Laptop backup: `python3 -I infra/vultr/budget_guard.py --log ~/.local/state/fazetime/vultr-guard.log run` |
| API access list | The key is restricted to the venue NAT range `129.107.192.0/24`, so the laptop and the Pi egress from different addresses |

## Commands

These read `VULTR_API_KEY` from `.env.local` (on the Pi: `~/fazetime-data/vultr.env`, mode 600). They never print it.

```bash
python3 -I infra/vultr/budget_guard.py status                               # spend, burn, projection, resources
python3 -I infra/vultr/budget_guard.py check-create voc-c-8c-16gb-150s-amd  # refuse a create that would breach the cap
python3 -I infra/vultr/budget_guard.py teardown                             # destroy every fazetime resource NOW
```

**Rule:** run `check-create` before any new paid resource, including Kubernetes nodes or a load balancer. Every resource must carry the `fazetime` tag or label, or the guard cannot see or destroy it.
