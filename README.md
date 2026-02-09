# clawctl

Coordination layer for [OpenClaw](https://github.com/openclaw/openclaw) agent fleets. Task board, inter-agent messaging, activity feed, and a live web dashboard — all backed by a single SQLite database.

```
$ clawctl board

═══ CLAWCTL ═══  agent: neo

── ○ pending (2) ──
  #3 Enumerate open ports on staging box              !
  #4 Patch CVE-2024-3094 before someone notices

── ▶ in_progress (1) ──
  #1 Scrape vendor API for leaked endpoints     recon

── ✗ blocked (1) ──
  #5 Deploy honeypot to DMZ                     ghost

── ✓ done (1) ──
  #2 Rotate all prod SSH keys                   cipher
```

## Why this exists

Multiple agents working in parallel need a shared source of truth. Without one, you get duplicate work, missed handoffs, and no audit trail.

clawctl is the answer for OpenClaw fleets:

- **Zero infrastructure.** Local SQLite in WAL mode. No cloud, no signup, no build step.
- **SSH-queryable.** `ssh your-vps clawctl board` works out of the box.
- **Race-safe.** Atomic claims and completions via single-UPDATE patterns with WHERE guards. No read-then-write races.
- **Auditable.** Every mutation hits an append-only activity log with optional JSON metadata for linking PRs, issues, test results.
- **OpenClaw-native.** Install as a skill, drop into any agent's workflow.

## Install

```bash
# As an OpenClaw skill (recommended)
openclaw skills install clawctl

# Or standalone
git clone https://github.com/lludlow/clawctl.git
cd clawctl
pip install .

# For development
pip install -e .
```

**Requirements:** Python >= 3.9, Click, Flask

## Quick start

```bash
# Initialize
clawctl init

# Register your operatives
clawctl register recon --role "reconnaissance & OSINT"
clawctl register cipher --role "crypto & key management"
clawctl register ghost --role "infrastructure & deployment"

# Create tasks
clawctl add "Scrape vendor API for leaked endpoints" --for recon
clawctl add "Rotate all prod SSH keys" -p 1
clawctl add "Audit deps for supply chain vulns" --parent 1

# Agent workflow
CLAW_AGENT=recon clawctl claim 1
CLAW_AGENT=recon clawctl start 1
CLAW_AGENT=recon clawctl done 1 -m "Found 3 undocumented endpoints" \
  --meta '{"report":"/recon/api-surface.md"}'

# Coordinate
CLAW_AGENT=recon clawctl msg cipher "Key rotation can proceed, attack surface mapped" --task 2

# Monitor
clawctl board
clawctl fleet
clawctl feed --last 10
```

## Agent integration

The typical agent loop:

```bash
# On startup — check messages, find work
CLAW_AGENT=ghost clawctl checkin
CLAW_AGENT=ghost clawctl inbox --unread
CLAW_AGENT=ghost clawctl next

# Do the work, then close out
CLAW_AGENT=ghost clawctl done <id> -m "Honeypot deployed to 10.0.0.42" \
  --meta '{"host":"10.0.0.42","containers":3}'
```

Add a heartbeat to each agent's cron:

```
*/10 * * * * CLAW_AGENT=ghost clawctl checkin
```

Add to each agent's system prompt or AGENTS.md:

```
Before starting work: clawctl inbox --unread && clawctl list --mine
After completing work: clawctl done <id> -m "what I did"
Only claim tasks assigned to you or matching your role.
```

> If `CLAW_AGENT` is not set, clawctl falls back to `$USER` and prints a one-time warning on identity-sensitive commands.

## Commands

### Tasks

| Command | Description |
|---------|-------------|
| `add SUBJECT` | Create a task. Options: `-d` description, `-p 0\|1\|2` priority, `--for AGENT` pre-assign, `--parent ID` subtask |
| `list` | List active tasks. Options: `--mine`, `--status STATUS`, `--owner AGENT`, `--all` (include done/cancelled) |
| `next` | Show the highest-priority actionable task for the current agent |
| `claim ID` | Claim a task. Options: `--force` to override, `--meta JSON` |
| `start ID` | Begin work (transitions to in_progress). Options: `--meta JSON` |
| `done ID` | Complete a task. Options: `-m` note, `--meta JSON` |
| `block ID --by OTHER` | Mark task as blocked. Options: `--meta JSON` |
| `board` | Kanban board view grouped by status |

### Messages

| Command | Description |
|---------|-------------|
| `msg AGENT BODY` | Send a message. Options: `--task ID`, `--type TYPE` |
| `broadcast BODY` | Message all agents (type: alert) |
| `inbox` | Read messages. Options: `--unread` |

### Fleet

| Command | Description |
|---------|-------------|
| `register NAME` | Register an agent. Options: `--role TEXT` |
| `checkin` | Heartbeat — update presence, check for unread |
| `fleet` | Show all agents with status and current task |
| `whoami` | Show identity, role, and DB path |

### Monitoring

| Command | Description |
|---------|-------------|
| `feed` | Activity log. Options: `--last N`, `--agent NAME`, `--meta` |
| `summary` | Fleet overview with counts and recent events |

### Dashboard

| Command | Description |
|---------|-------------|
| `dashboard` | Start the web UI. Options: `--port INT` (default: 3737) |
| `dashboard --stop` | Stop the running dashboard |

## Task statuses

```
pending ─→ claimed ─→ in_progress ─→ done
                    ↘ blocked ↗     ↘ cancelled
```

`list` excludes done/cancelled by default and sorts by status priority (in_progress > claimed > blocked > pending), oldest first. `--all` flips to newest-first for history browsing.

## Activity metadata

Mutating commands (`claim`, `start`, `done`, `block`) accept `--meta` with a JSON string stored in the activity log. Use it to link back to external artifacts:

```bash
clawctl claim 1 --meta '{"source":"github","issue":42}'
clawctl done 1 -m "Patched and verified" --meta '{"pr":187,"cve":"CVE-2024-3094"}'

# Review what happened overnight
clawctl feed --last 50 --agent recon --meta
```

## Web dashboard

A live web UI served by Flask with token authentication and SSE for real-time updates.

```bash
clawctl dashboard
# Opens at http://localhost:3737/?token=<TOKEN>
```

Features:
- Live board with SSE push updates (no polling)
- Task detail view with messages and metadata grid
- Complete and delete actions from the UI
- Terminal/hacker aesthetic with optional CRT effects
- Keyboard accessible (Esc to close, Tab trapping in modals)
- Works on narrow viewports
- Token persisted at `~/.openclaw/.clawctl-token` across restarts

The dashboard is read-mostly — it shares the same SQLite database the CLI writes to. The CLI is the primary interface; the dashboard is for monitoring.

## Architecture

```
┌─────────────────────────────┐
│  clawctl CLI (Python/Click) │ ← Every agent calls this
├─────────────────────────────┤
│  db.py — all SQL lives here │ ← Shared by CLI + Flask
├─────────────────────────────┤
│  SQLite (WAL mode)          │ ← ~/.openclaw/clawctl.db
├─────────────────────────────┤
│  5 tables + indexes:        │
│  tasks          task_deps   │ ← Board + blocking graph
│  messages       agents      │ ← Comms + fleet registry
│  activity                   │ ← Append-only audit log
├─────────────────────────────┤
│  Flask dashboard (optional) │ ← dashboard/server.py
└─────────────────────────────┘
```

**Key design decisions:**

- **All SQL in `db.py`.** The CLI and Flask server import it. No queries in `cli.py` or `server.py`.
- **Race safety.** `claim_task()` and `complete_task()` use atomic single-UPDATE with WHERE guards and rowcount checks. No read-then-write.
- **Normalized blocking.** Dependencies live in the `task_deps` join table with a UNIQUE constraint. Not JSON columns.
- **Parameterized queries.** Every query uses `?` placeholders. No string interpolation.
- **Idempotent completions.** `done` on an already-done task is a safe no-op.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAW_AGENT` | `$USER` (with warning) | Agent identity for all commands |
| `CLAW_DB` | `~/.openclaw/clawctl.db` | Database file path |

## License

MIT
