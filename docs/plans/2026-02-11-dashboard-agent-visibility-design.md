# Dashboard Agent Visibility & Task Pipeline

**Date:** 2026-02-11
**Status:** Approved
**Problem:** The dashboard only shows 3 groups (pending, in progress, done), hiding the real task pipeline and providing no visibility into agent activity.

## Task Board Restructuring

Reorganize the board into 4 groups that better reflect the pipeline. Keep the vertical layout.

| Group | Statuses Included | Accent Color | Bracket |
|-------|-------------------|-------------|---------|
| **Queued** | `pending`, `claimed` | amber | `[ ]` |
| **Active** | `in_progress`, `review` | cyan | `[>]` |
| **Blocked** | `blocked` | red | `[X]` |
| **Done** | `done`, `cancelled` | green | `[+]` |

### Card Status Badges

Each card shows a prominent, color-coded badge for its exact status instead of the generic group name:

- `pending` — amber badge
- `claimed` — amber-cyan badge, shows claiming agent
- `in_progress` — cyan badge
- `review` — purple/magenta badge (`--purple: #c084fc`)
- `blocked` — red badge, shows blocker task IDs
- `cancelled` — dim/strikethrough in Done section

### Time-in-Status Indicator

Each card shows a small label (e.g., "2h", "3d") indicating how long the task has been in its current status, calculated from `updated_at`. Makes stale tasks immediately visible.

## Activity Feed Panel

A collapsible panel at the bottom of the board, toggled via a `FEED` button in the header. When expanded, it takes ~40% of viewport height and slides up from the bottom.

### Feed Content

Pulls from the `activity` table. Displays the latest 30 actions as a chronological stream:

```
2m ago   agent-3   task_claimed     #14 "Set up auth middleware"
5m ago   agent-1   task_completed   #11 "Fix login redirect"
8m ago   agent-2   task_started     #13 "Add rate limiter"
```

### Agent Filter

A row of clickable agent name pills at the top of the panel. Click to filter to one agent. Click again to deselect. Active pill gets green highlight.

### Live Updates

The existing SSE `fetchBoard()` trigger gets a parallel `fetchFeed()` call so the feed auto-refreshes.

### New API Endpoint

`GET /api/feed?limit=30&agent=<optional>` — thin wrapper around existing `db.get_feed()`.

## Agent Status Enhancements

### Header

Replace the generic stats line with per-agent indicators:

```
$ fleet: agent-1 [green dot] agent-2 [green dot] agent-3 [amber dot]  |  2 active  |  5 tasks
```

- Green dot = busy/active
- Amber dot = idle
- Dim dot = offline (last_seen > 15 min)

Clicking an agent name scrolls to their tasks and filters the feed panel.

### Card Enhancements

- Show agent role in dim text after agent name (e.g., `agent-1 (coder)`)
- On blocked tasks: show "blocked by #7, #9" below meta, clickable to open those task details

### Detail Sheet Enhancements

Add two new grid cells:
- **Time in Status** — duration since `updated_at`
- **Total Duration** — time from `created_at` to now (or `completed_at` if done)

Show blocker tasks as clickable links.

## Implementation Plan

### Backend (server.py + db.py)

1. Add `GET /api/feed` endpoint wrapping `db.get_feed()`
2. Add `GET /api/task/<id>/blockers` endpoint wrapping `db.get_blockers()`
3. Extend `get_board_api()` to include blocker IDs per task via LEFT JOIN on `task_deps`

### Frontend (index.html)

1. `renderBoard()` — regroup into Queued/Active/Blocked/Done; `review` goes into Active
2. `renderCard()` — prominent per-status badges with distinct colors, time-in-status label, agent role, blocker links
3. `renderDetail()` — add Time in Status and Total Duration grid cells, clickable blockers
4. New `renderFeed()` function and collapsible feed panel with agent filter pills
5. Header — agent status indicators with click-to-filter
6. New CSS — review status color, feed panel styles, agent pill styles

### No Schema Changes

All required data already exists in the database.

### Testing

- New `/api/feed` endpoint gets a test in `test_server.py`
- Frontend changes verified manually
- Existing db layer tests remain unchanged
