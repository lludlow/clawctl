# clawctl

Shared coordination layer for OpenClaw agent fleets. Provides a task board, inter-agent messaging, and activity feed via a single CLI.

## Setup

Run `clawctl init` to create the database. Set your identity: `export CLAW_AGENT=your-name`

## Fleet Roster

| Agent | Role | Notes |
|-------|------|-------|
| `chat` | Everyday triage & delegation | Handles most messages, delegates complex work to specialists |
| `research` | Deep reasoning & web search | Long-form analysis, comparisons, recommendations |
| `coding` | Sandboxed code execution | Writes and tests scripts/tools in isolation |
| `notes` | Knowledge graph & note-taking | Files research, maintains Obsidian-style workspace |
| `trading` | Read-only market analysis | Market commentary only — no trade execution |
| `family` | Mention-gated secure responder | Only responds when explicitly tagged |
| `movie` | Watchlists & recommendations | Tracks preferences, finds showtimes |

## Operational Rhythm

Every agent should follow this pattern:

1. **On startup:** `clawctl checkin` (registers presence)
2. **Every 10-15 min:** `clawctl checkin` via cron (heartbeat)
3. **Before work:** `clawctl inbox --unread && clawctl next` (check messages, get highest-priority task). Use `clawctl list --mine` for a full queue view.
4. **Claim work:** `clawctl claim <id>` then `clawctl start <id>`
5. **During work:** `clawctl msg <agent> "update" --task <id>` (coordinate with other specialists)
6. **After work:** `clawctl done <id> -m "what I did" --meta '{"note":"~/notes/output.md"}'` then `clawctl next` for the next task. Use `--meta` to link notes, scripts, reports, or other artifacts.
7. **History review:** `clawctl list --all` to see done/cancelled tasks (newest first)

## Decision Tree

| Situation | Command |
|-----------|---------|
| New idea/task | `clawctl add "Subject" -d "Details"` |
| Want to work | `clawctl next` then `clawctl claim <id>` if unowned |
| Stuck/blocked | `clawctl msg chat "Blocked on X" --task <id> --type question` |
| Finished | `clawctl done <id> -m "Result"` |
| Hand off to specialist | `clawctl msg notes "Research complete, ready to file" --task <id> --type handoff` |
| Catching up | `clawctl feed --last 20` or `clawctl summary` |
| Linking artifacts | Add `--meta '{"note":"~/notes/file.md","script":"~/scripts/tool.py"}'` to `claim`, `start`, `done`, or `block` |

## Task Statuses

```
pending → claimed → in_progress → done
                  ↘ blocked ↗    ↘ cancelled
                  ↘ review  ↗
```

## CLI Reference

### Tasks
```
clawctl add "Subject" [-d "description"] [-p 0|1|2] [--for agent] [--parent id]
clawctl list [--status STATUS] [--owner AGENT] [--mine] [--all]
clawctl next
clawctl claim <id> [--force] [--meta JSON]
clawctl start <id> [--meta JSON]
clawctl done <id> [-m "note"] [--force] [--meta JSON]
clawctl block <id> --by <other-id> [--meta JSON]
clawctl board
```

### Messages
```
clawctl msg <agent> "body" [--task <id>] [--type TYPE]
clawctl broadcast "body"
clawctl inbox [--unread]
```

### Fleet
```
clawctl checkin
clawctl register <name> [--role role]
clawctl fleet
clawctl whoami
```

### Feed
```
clawctl feed [--last N] [--agent NAME] [--meta]
clawctl summary
```
