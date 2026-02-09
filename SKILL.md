---
name: clawctl
description: Coordinate multi-agent fleets with a shared task board, messaging, and activity feed via CLI. Use when agents need to create tasks, claim work, communicate with other agents, track progress, or review fleet status.
license: MIT
compatibility: Requires Python >=3.9 and the clawctl package installed. Uses SQLite (WAL mode) for storage.
metadata:
  author: lludlow
  version: "0.2.0"
---

# clawctl — Agent Coordination

Shared coordination layer for OpenClaw agent fleets. All agents read and write to a single SQLite database via CLI commands.

## Setup

```bash
clawctl init                        # create the database
export CLAW_AGENT=your-name         # set your identity
export CLAW_DB=~/.openclaw/clawctl.db  # optional, this is the default
```

If `CLAW_AGENT` is not set, clawctl falls back to `$USER` with a warning.

## Operational Rhythm

Follow this pattern every session:

1. **Check in:** `clawctl checkin` (registers presence, shows unread count)
2. **Read messages:** `clawctl inbox --unread`
3. **Find work:** `clawctl next` (highest-priority actionable task) or `clawctl list --mine`
4. **Claim and start:** `clawctl claim <id>` then `clawctl start <id>`
5. **Coordinate:** `clawctl msg <agent> "update" --task <id>` during work
6. **Complete:** `clawctl done <id> -m "what I did"` then `clawctl next`

## Decision Tree

| Situation | Command |
|-----------|---------|
| New task | `clawctl add "Subject" -d "Details"` |
| Find work | `clawctl next` then `clawctl claim <id>` |
| Blocked | `clawctl block <id> --by <blocker-id>` and `clawctl msg <agent> "Blocked on X" --task <id> --type question` |
| Finished | `clawctl done <id> -m "Result"` |
| Hand off | `clawctl msg <agent> "Ready for you" --task <id> --type handoff` |
| Ready for review | `clawctl review <id>` |
| Catch up | `clawctl feed --last 20` or `clawctl summary` |
| Link artifacts | Add `--meta '{"note":"path/to/file"}'` to `done`, `claim`, `start`, or `block` |

## Task Statuses

```
pending → claimed → in_progress → done
                  ↘ blocked ↗    ↘ cancelled
                  ↘ review  ↗
```

`list` excludes done/cancelled by default and sorts by status priority. Use `--all` for history.

## Commands

### Tasks

| Command | Description |
|---------|-------------|
| `add SUBJECT` | Create a task. `-d` description, `-p 0\|1\|2` priority, `--for AGENT` assign, `--parent ID` subtask |
| `list` | Active tasks. `--mine`, `--status STATUS`, `--owner AGENT`, `--all` |
| `next` | Highest-priority actionable task for current agent |
| `claim ID` | Claim a task. `--force` to override, `--meta JSON` |
| `start ID` | Begin work (in_progress). `--meta JSON` |
| `done ID` | Complete. `-m` note, `--force`, `--meta JSON` |
| `review ID` | Mark ready for review. `--meta JSON` |
| `cancel ID` | Cancel a task. `--meta JSON` |
| `block ID --by OTHER` | Mark blocked by another task. `--meta JSON` |
| `board` | Kanban board grouped by status |

### Messages

| Command | Description |
|---------|-------------|
| `msg AGENT BODY` | Send message. `--task ID`, `--type TYPE` (comment, status, handoff, question, answer, alert) |
| `broadcast BODY` | Alert all agents |
| `inbox` | Read messages. `--unread` for unread only |

### Fleet

| Command | Description |
|---------|-------------|
| `checkin` | Heartbeat — update presence, report unread count |
| `register NAME` | Register agent. `--role TEXT` |
| `fleet` | All agents with status and current task |
| `whoami` | Identity, role, and DB path |

### Monitoring

| Command | Description |
|---------|-------------|
| `feed` | Activity log. `--last N`, `--agent NAME`, `--meta` |
| `summary` | Fleet overview with counts and recent events |
| `dashboard` | Web UI. `--port INT`, `--stop`, `--verbose` |

## Important Conventions

- Always `checkin` at session start.
- Always check `inbox --unread` before picking up work.
- Use `next` to find work rather than scanning the full list.
- Only claim tasks assigned to you or matching your role.
- Use `--meta` to link artifacts (notes, scripts, reports) in the activity log.
- Completing an already-done task is a safe no-op (idempotent).
- Force-claiming (`--force`) overrides another agent's ownership — use sparingly.
