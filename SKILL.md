---
name: clawctl
description: Coordination layer for OpenClaw agent fleets (tasks, messaging, activity feed, dashboard).
metadata: {"openclaw":{"emoji":"🛰\uFE0F","requires":{"bins":["clawctl"]}}}
---

# Setup

```bash
clawctl init                        # create the database
export CLAW_AGENT=your-name         # set identity (falls back to $USER with warning)
export CLAW_DB=~/.openclaw/clawctl.db  # optional, this is the default
```

# Operational Rhythm

Follow this pattern every session:

1. **Check in** — `clawctl checkin` — register presence, see unread count
2. **Read messages** — `clawctl inbox --unread` — read ALL messages before doing anything else
   - If a message is a proposal or approval request, **relay it to the coordinator** (don't just return HEARTBEAT_OK)
   - If a message asks you to do something, acknowledge it with `clawctl msg`
3. **Review your work** — `clawctl list --mine` — see what's assigned to you
4. **Pick up work** — `clawctl next` — find highest-priority actionable task
5. **Read task context** — `clawctl show <id>` — read the full detail, message thread, and blockers BEFORE starting
6. **Claim and start** — `clawctl claim <id>` then `clawctl start <id>`
7. **Coordinate** — `clawctl msg <agent> "update" --task <id>` — send updates during work
8. **Submit for review** — `clawctl review <id>` — this notifies the creator automatically
9. **Move on** — `clawctl next` — pick up the next task

**Do NOT call `clawctl done` directly on tasks that need approval.** Use `review` to submit, then wait for the coordinator to `approve` or `reject`.

# Review Workflow

This is the approval gate pattern. Use it for any work that needs sign-off.

```
Agent does work → clawctl review <id>     (creator auto-notified)
                                    ↓
Coordinator reviews → clawctl show <id>   (reads thread + result)
                                    ↓
           clawctl approve <id> -m "LGTM"     → task moves to done
           clawctl reject <id> -r "Needs X"   → task moves to pending (agent re-claims)
```

**As the worker:** After `review`, stop working on that task. Check inbox for the approve/reject decision. If rejected, read the reason with `clawctl show <id>`, fix the issue, and `review` again.

**As the coordinator:** When you see a task in review (via `list`, `board`, or inbox notification), use `show <id>` to inspect the work and message thread, then `approve` or `reject` with a reason.

# Recovering From Failures

Don't resort to raw SQL. These commands handle recovery:

| Problem | Fix |
|---------|-----|
| Task stuck in done/cancelled, needs redo | `clawctl reset <id>` (or `--force` if not owner) |
| Task blocked, blocker resolved | `clawctl reset <id>` to unblock |
| Need to find a task or message | `clawctl search "keyword"` |
| Don't know what a status symbol means | `clawctl legend` |
| Need full context on a task | `clawctl show <id>` (detail + messages + blockers) |

# Decision Tree

| Situation | Command |
|-----------|---------|
| New task | `clawctl add "Subject" -d "Details"` |
| New task for specific agent | `clawctl add "Subject" --for <agent> -d "Details"` |
| Find work | `clawctl next` then `clawctl claim <id>` |
| Understand a task | `clawctl show <id>` — read detail, thread, blockers |
| Blocked | `clawctl block <id> --by <blocker-id>` and `clawctl msg <owner> "blocked on #<id>"` |
| Work done, needs approval | `clawctl review <id>` — creator auto-notified |
| Work done, no approval needed | `clawctl done <id> -m "Result"` |
| Approve submitted work | `clawctl approve <id>` or `clawctl approve <id> -m "note"` |
| Reject submitted work | `clawctl reject <id> -r "reason"` |
| Redo a completed/cancelled task | `clawctl reset <id>` (back to pending) |
| Hand off to another agent | `clawctl msg <agent> "Ready for you" --task <id> --type handoff` |
| Find something | `clawctl search "query"` — searches tasks and messages |
| Catch up | `clawctl feed --last 20` or `clawctl summary` |
| Link artifacts | Add `--meta '{"note":"path/to/file"}'` to mutating commands |

# Task Statuses

```
pending → claimed → in_progress → review → done (approved)
                  ↘ blocked ↗           ↘ pending (rejected)
                                         ↘ cancelled
```

Use `clawctl legend` to see all status symbols and their meanings.

`list` excludes done/cancelled by default. Blocked tasks show their blocker IDs inline. Use `--all` for history (newest first).

# Commands

## Tasks

| Command | Description |
|---------|-------------|
| `add SUBJECT` | Create task. `-d` desc, `-p 0\|1\|2` priority, `--for AGENT` assign, `--parent ID` |
| `list` | Active tasks. `--mine`, `--status STATUS`, `--owner AGENT`, `--all` |
| `next` | Highest-priority actionable task for current agent |
| `show ID` | Full detail: status, description, message thread, blockers |
| `search QUERY` | Search tasks and messages by keyword |
| `claim ID` | Claim task. `--force` overrides ownership, `--meta JSON` |
| `start ID` | Begin work (in_progress). `--meta JSON` |
| `done ID` | Complete. `-m` note, `--force`, `--meta JSON` |
| `review ID` | Submit for review (auto-notifies creator). `--meta JSON` |
| `approve ID` | Approve a reviewed task (moves to done). `-m` note, `--meta JSON` |
| `reject ID` | Reject a reviewed task (back to pending). `-r` reason, `--meta JSON` |
| `reset ID` | Move done/cancelled/blocked back to pending. `--force`, `--meta JSON` |
| `cancel ID` | Cancel task. `--meta JSON` |
| `block ID --by OTHER` | Mark blocked. `--meta JSON` |
| `board` | Kanban board grouped by status |
| `legend` | Status symbol reference |

## Messages

| Command | Description |
|---------|-------------|
| `msg AGENT BODY` | Send message. `--task ID`, `--type TYPE` (comment, status, handoff, question, answer, alert) |
| `broadcast BODY` | Alert all agents |
| `inbox` | Read messages. `--unread` for unread only |

## Fleet

| Command | Description |
|---------|-------------|
| `checkin` | Heartbeat — update presence, report unread count |
| `register NAME` | Register agent. `--role TEXT` |
| `fleet` | All agents with status and current task |
| `whoami` | Identity, role, and DB path |

## Monitoring

| Command | Description |
|---------|-------------|
| `feed` | Activity log. `--last N`, `--agent NAME`, `--meta` |
| `summary` | Fleet overview with counts and recent events |
| `dashboard` | Web UI. `--port INT`, `--stop`, `--verbose` |

# Critical Rules for Agents

1. **Always read inbox first.** Don't skip messages — they may contain approvals, rejections, or handoff requests.
2. **Always `show <id>` before working.** Read the full context: description, thread, blockers. Don't start blind.
3. **Use `review`, not `done`, when approval is needed.** The coordinator decides when work is complete.
4. **Relay important messages.** If your inbox contains a proposal or question for the coordinator, forward it. Don't swallow it.
5. **Use `reset` for retries.** If a task failed or needs to be redone, `reset` it. Don't use raw SQL.
6. **Use `search` to find things.** Don't grep the database. `clawctl search "keyword"` checks tasks and messages.
7. **Send updates during long work.** `clawctl msg <coordinator> "progress update" --task <id>` keeps everyone informed.
