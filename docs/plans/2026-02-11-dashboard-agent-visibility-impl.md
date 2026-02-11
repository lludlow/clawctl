# Dashboard Agent Visibility — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the clawctl dashboard to show the full task pipeline (7 statuses), agent activity feed, and richer agent status indicators.

**Architecture:** Backend adds two new API endpoints (`/api/feed`, `/api/task/<id>/blockers`) and extends the board API to include blocker IDs. Frontend restructures the board into 4 groups with per-status badges, adds a collapsible activity feed panel, and enhances agent visibility in the header and cards.

**Tech Stack:** Python/Flask backend, vanilla JS frontend (single `index.html`), SQLite, SSE for live updates.

**Design doc:** `docs/plans/2026-02-11-dashboard-agent-visibility-design.md`

**Worktree:** `.worktrees/dashboard-agent-visibility` (branch: `feature/dashboard-agent-visibility`)

**Run tests:** `.venv/bin/python -m pytest tests/ --cov=clawctl --cov=dashboard --cov-report=term-missing`

---

### Task 1: Add `/api/feed` endpoint

**Files:**
- Modify: `dashboard/server.py` (add endpoint after line ~109)
- Test: `tests/test_server.py` (add test class)

**Step 1: Write the failing tests**

Add to the end of `tests/test_server.py`, before no other class:

```python
# ── Feed API ─────────────────────────────────────────


class TestFeedApi:
    """GET /api/feed returns activity entries."""

    def test_returns_activity_list(self, flask_client):
        client, token = flask_client
        # Create some activity by adding a task
        with db.get_db() as conn:
            db.add_task(conn, "Test task", created_by="agent-1")
        resp = client.get(f"/api/feed?token={token}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "entries" in data
        assert len(data["entries"]) > 0
        assert "agent" in data["entries"][0]
        assert "action" in data["entries"][0]

    def test_filters_by_agent(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task A", created_by="agent-1")
            db.add_task(conn, "Task B", created_by="agent-2")
        resp = client.get(f"/api/feed?token={token}&agent=agent-1")
        data = resp.get_json()
        assert all(e["agent"] == "agent-1" for e in data["entries"])

    def test_respects_limit(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            for i in range(10):
                db.add_task(conn, f"Task {i}", created_by="agent-1")
        resp = client.get(f"/api/feed?token={token}&limit=3")
        data = resp.get_json()
        assert len(data["entries"]) == 3

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.get("/api/feed")
        assert resp.status_code == 401
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestFeedApi -v`
Expected: FAIL with 404 (endpoint doesn't exist yet)

**Step 3: Implement the endpoint**

Add to `dashboard/server.py` after the `complete_task` endpoint (after line 109):

```python
@app.route("/api/feed")
def feed():
    limit = request.args.get("limit", 30, type=int)
    agent_filter = request.args.get("agent", None)
    with db.get_db() as conn:
        entries = db.get_feed(conn, limit=limit, agent_filter=agent_filter)
    return jsonify({"entries": [row_to_dict(e) for e in entries]})
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestFeedApi -v`
Expected: All 4 PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All 116 PASS (112 existing + 4 new)

**Step 6: Commit**

```bash
git add tests/test_server.py dashboard/server.py
git commit -m "feat(api): add /api/feed endpoint for activity stream"
```

---

### Task 2: Add `/api/task/<id>/blockers` endpoint

**Files:**
- Modify: `dashboard/server.py` (add endpoint)
- Test: `tests/test_server.py` (add test class)

**Step 1: Write the failing tests**

Add to `tests/test_server.py`:

```python
# ── Blockers API ─────────────────────────────────────


class TestBlockersApi:
    """GET /api/task/<id>/blockers returns blocker tasks."""

    def test_returns_empty_when_no_blockers(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task", created_by="test")
        resp = client.get(f"/api/task/1/blockers?token={token}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["blockers"] == []

    def test_returns_blocker_info(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Blocked task", created_by="test")
            db.add_task(conn, "Blocker task", created_by="test")
            db.block_task(conn, 1, 2)
        resp = client.get(f"/api/task/1/blockers?token={token}")
        data = resp.get_json()
        assert len(data["blockers"]) == 1
        assert data["blockers"][0]["id"] == 2
        assert data["blockers"][0]["subject"] == "Blocker task"

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.get("/api/task/1/blockers")
        assert resp.status_code == 401
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestBlockersApi -v`
Expected: FAIL with 404

**Step 3: Implement the endpoint**

Add to `dashboard/server.py`:

```python
@app.route("/api/task/<int:task_id>/blockers")
def task_blockers(task_id):
    with db.get_db() as conn:
        blockers = db.get_blockers(conn, task_id)
    return jsonify({"blockers": [row_to_dict(b) for b in blockers]})
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestBlockersApi -v`
Expected: All 3 PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All 119 PASS

**Step 6: Commit**

```bash
git add tests/test_server.py dashboard/server.py
git commit -m "feat(api): add /api/task/<id>/blockers endpoint"
```

---

### Task 3: Extend board API to include blocker IDs and agent roles

**Files:**
- Modify: `clawctl/db.py` — `get_board_api()` function (lines 443-462)
- Test: `tests/test_db.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
# ── Board API with blockers ──────────────────────────


class TestGetBoardApiBlockers:
    """get_board_api includes blocker_ids for blocked tasks."""

    def test_includes_blocker_ids_field(self, db_conn):
        db.add_task(db_conn, "Task A", created_by="test")
        tasks, _ = db.get_board_api(db_conn)
        # Every task row should have the blocker_ids field
        assert "blocker_ids" in tasks[0].keys()

    def test_blocker_ids_populated(self, db_conn):
        db.add_task(db_conn, "Blocked task", created_by="test")
        db.add_task(db_conn, "Blocker 1", created_by="test")
        db.add_task(db_conn, "Blocker 2", created_by="test")
        db.block_task(db_conn, 1, 2)
        db.block_task(db_conn, 1, 3)
        tasks, _ = db.get_board_api(db_conn)
        blocked = [t for t in tasks if t["id"] == 1][0]
        ids = blocked["blocker_ids"]
        # GROUP_CONCAT returns comma-separated string
        assert "2" in ids
        assert "3" in ids

    def test_no_blockers_returns_null(self, db_conn):
        db.add_task(db_conn, "Normal task", created_by="test")
        tasks, _ = db.get_board_api(db_conn)
        assert tasks[0]["blocker_ids"] is None

    def test_agents_include_role(self, db_conn):
        db.register_agent(db_conn, "agent-1", "coder")
        _, agents = db.get_board_api(db_conn)
        assert agents[0]["role"] == "coder"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_db.py::TestGetBoardApiBlockers -v`
Expected: FAIL — `blocker_ids` not in row keys

**Step 3: Modify `get_board_api()` in `clawctl/db.py`**

Replace the `get_board_api` function (lines 443-462) with:

```python
def get_board_api(conn):
    tasks = conn.execute(
        """SELECT t.id, t.subject, t.description, t.status, t.owner, t.priority,
               t.tags, t.created_at, t.updated_at, t.claimed_at, t.completed_at,
               GROUP_CONCAT(d.blocked_by) AS blocker_ids
        FROM tasks t
        LEFT JOIN task_deps d ON d.task_id = t.id
        GROUP BY t.id
        ORDER BY
            CASE t.status
                WHEN 'in_progress' THEN 1
                WHEN 'claimed' THEN 2
                WHEN 'pending' THEN 3
                WHEN 'blocked' THEN 4
                WHEN 'review' THEN 5
                WHEN 'done' THEN 6
            END,
            t.priority DESC, t.id"""
    ).fetchall()
    agents = conn.execute(
        "SELECT name, role, status, last_seen FROM agents ORDER BY status, name"
    ).fetchall()
    return tasks, agents
```

Key changes from original:
- Added `t.tags` to SELECT
- Added `GROUP_CONCAT(d.blocked_by) AS blocker_ids`
- Added `LEFT JOIN task_deps d ON d.task_id = t.id`
- Added `GROUP BY t.id`
- Prefixed all columns with `t.` for disambiguation

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_db.py::TestGetBoardApiBlockers -v`
Expected: All 4 PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All 123 PASS

**Step 6: Commit**

```bash
git add clawctl/db.py tests/test_db.py
git commit -m "feat(db): extend get_board_api with blocker_ids and tags"
```

---

### Task 4: Frontend — New CSS variables and styles

**Files:**
- Modify: `dashboard/index.html` — CSS section (lines 33-713)

**Step 1: Add new CSS variables and styles**

In the `:root` block (line 37), add after `--gray: #3a5f3a;`:

```css
  --purple: #c084fc;
```

Add new CSS blocks after the `.agent-dot.offline` rule (line 332):

```css
/* --- Status-specific badge colors --- */
.task-badge[data-status="pending"]     { border-color: var(--amber); color: var(--amber); }
.task-badge[data-status="claimed"]     { border-color: var(--amber); color: var(--amber); }
.task-badge[data-status="in_progress"] { border-color: var(--cyan); color: var(--cyan); }
.task-badge[data-status="review"]      { border-color: var(--purple); color: var(--purple); }
.task-badge[data-status="blocked"]     { border-color: var(--red); color: var(--red); }
.task-badge[data-status="done"]        { border-color: var(--green); color: var(--green); }
.task-badge[data-status="cancelled"]   { border-color: var(--gray); color: var(--fg-dim); }

/* --- Task card review accent --- */
.task-card[data-status="review"]       { --accent: var(--purple); }
.task-card[data-status="cancelled"]    { --accent: var(--gray); opacity: 0.6; }

/* --- Time in status --- */
.task-age {
  font-size: 0.6rem;
  color: var(--fg-dim);
  margin-left: auto;
  white-space: nowrap;
}

.task-age.stale { color: var(--amber); }

/* --- Blocker link on cards --- */
.task-blockers {
  font-size: 0.65rem;
  color: var(--red);
  margin-top: 0.25rem;
  cursor: pointer;
}

.task-blockers:hover { text-decoration: underline; }

/* --- Agent pills in header --- */
.agent-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.7rem;
  color: var(--fg-dim);
  cursor: pointer;
  padding: 0.125rem 0.375rem;
  border: 1px solid transparent;
  transition: border-color 0.15s, color 0.15s;
}

.agent-pill:hover {
  border-color: var(--green);
  color: var(--green);
}

.agent-pill.active {
  border-color: var(--green);
  color: var(--green);
}

/* --- Feed Panel --- */
.feed-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--bg-1);
  border-top: 2px solid var(--green);
  z-index: 15;
  transform: translateY(100%);
  transition: transform 0.3s ease-out;
  height: 40vh;
  display: flex;
  flex-direction: column;
}

.feed-panel.visible {
  transform: translateY(0);
}

.feed-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.feed-header-title {
  font-size: 0.75rem;
  color: var(--fg-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.feed-filters {
  display: flex;
  gap: 0.25rem;
  padding: 0.375rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  overflow-x: auto;
}

.feed-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem 0.75rem;
}

.feed-entry {
  display: grid;
  grid-template-columns: 4rem 6rem 1fr;
  gap: 0.5rem;
  font-size: 0.7rem;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--border);
  align-items: baseline;
}

.feed-entry:last-child { border-bottom: none; }

.feed-time { color: var(--fg-dim); }
.feed-agent { color: var(--green-dim); }
.feed-action { color: var(--fg); }

.feed-empty {
  color: var(--fg-dim);
  font-size: 0.75rem;
  padding: 1rem 0;
  text-align: center;
  font-style: italic;
}
```

Also add `--purple` to the tailwind config `colors` (line 26), after `'cc-gray'`:

```javascript
'cc-purple': 'var(--purple)',
```

And add a glow utility in the effects section (line 646), after `glow-cyan`:

```css
.effects-on .glow-purple { text-shadow: 0 0 6px rgba(192, 132, 252, 0.4); }
```

**Step 2: Verify no syntax errors**

Open `dashboard/index.html` in a browser and check it loads without console errors. The board should still render normally (no behavioral changes yet).

**Step 3: Commit**

```bash
git add dashboard/index.html
git commit -m "style: add CSS for review status, feed panel, agent pills"
```

---

### Task 5: Frontend — Restructure board into 4 groups

**Files:**
- Modify: `dashboard/index.html` — `renderBoard()` function (lines 876-911)

**Step 1: Replace the `renderBoard()` function**

Replace the `renderBoard` function body (the groups object and the html building) with:

```javascript
function renderBoard() {
  const board = document.getElementById('board');
  const groups = {
    queued: state.tasks.filter(t => t.status === 'pending' || t.status === 'claimed'),
    active: state.tasks.filter(t => t.status === 'in_progress' || t.status === 'review'),
    blocked: state.tasks.filter(t => t.status === 'blocked'),
    done: state.tasks.filter(t => t.status === 'done' || t.status === 'cancelled')
  };

  const activeAgents = state.agents.filter(a => a.status === 'busy').length;
  const statsEl = document.getElementById('header-stats');
  statsEl.innerHTML = renderHeaderAgents();

  let html = '<div id="skeleton" style="display:none;"></div>';
  html += renderSection('queued', '[ ]', 'Queued', groups.queued, 'var(--amber)');
  html += renderSection('active', '[>]', 'Active', groups.active, 'var(--cyan)');
  if (groups.blocked.length > 0) {
    html += renderSection('blocked', '[X]', 'Blocked', groups.blocked, 'var(--red)');
  }
  html += renderSection('done', '[+]', 'Done', groups.done, 'var(--green)', groups.done.length > 3);

  board.innerHTML = html;

  // Animate card entrances
  if (state.effectsOn && !prefersReducedMotion()) {
    requestAnimationFrame(() => {
      const cards = board.querySelectorAll('.card-enter');
      cards.forEach((card, i) => {
        const delay = Math.min(i * 30, 500);
        setTimeout(() => {
          card.classList.add('card-enter-active');
        }, delay);
      });
    });
  }
}
```

**Step 2: Add the `renderHeaderAgents()` function**

Add before `renderBoard()`:

```javascript
function renderHeaderAgents() {
  if (state.agents.length === 0) {
    return `$ fleet: <span style="color:var(--fg-dim)">no agents</span> <span style="color:var(--fg-dim)">|</span> <span style="color:var(--amber)">${state.tasks.length} tasks</span>`;
  }
  const pills = state.agents.map(a => {
    const st = getAgentStatus(a);
    const dotClass = st;
    const isActive = state.feedAgentFilter === a.name;
    return `<span class="agent-pill ${isActive ? 'active' : ''}" onclick="toggleAgentFilter('${escapeHtml(a.name)}')">`
      + `<span class="agent-dot ${dotClass}"></span>${escapeHtml(a.name)}</span>`;
  }).join(' ');
  const activeCount = state.agents.filter(a => a.status === 'busy').length;
  return `$ fleet: ${pills} <span style="color:var(--fg-dim)">|</span> <span style="color:var(--cyan)">${activeCount} active</span> <span style="color:var(--fg-dim)">|</span> <span style="color:var(--amber)">${state.tasks.length} tasks</span>`;
}
```

**Step 3: Add `feedAgentFilter` to state**

In the `state` object (line 804), add:

```javascript
feedAgentFilter: null,
feedEntries: [],
feedOpen: false,
```

**Step 4: Add `toggleAgentFilter()` function**

Add in the ACTIONS section:

```javascript
function toggleAgentFilter(agentName) {
  if (state.feedAgentFilter === agentName) {
    state.feedAgentFilter = null;
  } else {
    state.feedAgentFilter = agentName;
  }
  // Re-render header to update active pill
  document.getElementById('header-stats').innerHTML = renderHeaderAgents();
  // If feed is open, refresh it
  if (state.feedOpen) {
    fetchFeed();
  }
}
```

**Step 5: Verify manually**

Open the dashboard. Confirm:
- Board shows "Queued", "Active", "Blocked" (if any), "Done" sections
- Header shows agent pills with colored dots
- `review` tasks appear in the Active section
- `cancelled` tasks appear in the Done section

**Step 6: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(ui): restructure board into queued/active/blocked/done groups"
```

---

### Task 6: Frontend — Enhanced card with status badges, time-in-status, role, blockers

**Files:**
- Modify: `dashboard/index.html` — `renderCard()` function (lines 937-977)

**Step 1: Replace the `renderCard()` function**

```javascript
function renderCard(task, index) {
  const agent = state.agents.find(a => a.name === task.owner);
  const agentStatus = agent ? getAgentStatus(agent) : 'offline';
  const agentRole = agent ? agent.role : '';
  const shouldAnimate = state.effectsOn && !prefersReducedMotion();

  let priorityBadge = '';
  if (task.priority >= 2) {
    priorityBadge = '<span class="task-priority crit">CRIT</span>';
  } else if (task.priority === 1) {
    priorityBadge = '<span class="task-priority high">HIGH</span>';
  }

  const tags = task.tags ? (typeof task.tags === 'string' ? task.tags.split(',').map(s=>s.trim()).filter(Boolean) : task.tags) : [];
  const tagsHtml = tags.length > 0 ? `<div class="task-tags">${tags.map(t => `<span class="task-tag">${escapeHtml(t)}</span>`).join('')}</div>` : '';

  // Time in status
  const age = timeInStatus(task.updated_at || task.created_at);
  const isStale = age.hours >= 24;
  const ageLabel = age.hours < 1 ? `${age.minutes}m` : age.hours < 24 ? `${Math.floor(age.hours)}h` : `${Math.floor(age.hours / 24)}d`;

  // Blocker info for blocked tasks
  let blockerHtml = '';
  if (task.status === 'blocked' && task.blocker_ids) {
    const ids = task.blocker_ids.split(',');
    const links = ids.map(id => `<span onclick="event.stopPropagation();openDetail(${id})">#${id}</span>`).join(', ');
    blockerHtml = `<div class="task-blockers">blocked by ${links}</div>`;
  }

  // Status display name
  const statusDisplay = task.status === 'in_progress' ? 'in progress' : task.status;

  return `
    <div class="task-card ${shouldAnimate ? 'card-enter' : ''}" data-status="${task.status}"
         onclick="openDetail(${task.id})" tabindex="0" role="button"
         onkeydown="if(event.key==='Enter')openDetail(${task.id})">
      <div class="task-card-top">
        <div>
          <span class="task-id">#${task.id}</span>
          <span class="task-subject">${escapeHtml(task.subject)}</span>
          ${priorityBadge}
        </div>
        <div style="display:flex;align-items:center;gap:0.375rem;">
          <span class="task-age ${isStale ? 'stale' : ''}">${ageLabel}</span>
          <span class="task-badge" data-status="${task.status}">${statusDisplay}</span>
        </div>
      </div>
      <div class="task-meta">
        ${task.owner ? `
          <span class="task-agent">
            <span class="agent-dot ${agentStatus}"></span>
            ${escapeHtml(task.owner)}${agentRole ? ` <span style="color:var(--fg-dim)">(${escapeHtml(agentRole)})</span>` : ''}
          </span>
          <span class="task-meta-sep">//</span>
        ` : '<span style="color:var(--fg-dim)">unassigned</span><span class="task-meta-sep">//</span>'}
        <span>${timeAgo(task.updated_at || task.created_at)}</span>
      </div>
      ${blockerHtml}
      ${tagsHtml}
    </div>
  `;
}
```

**Step 2: Add `timeInStatus()` helper**

Add in the UTILITIES section, after `timeAgo()`:

```javascript
function timeInStatus(dateStr) {
  if (!dateStr) return { minutes: 0, hours: 0 };
  const date = new Date(dateStr.replace(' ', 'T') + 'Z');
  const ms = Date.now() - date.getTime();
  return { minutes: Math.floor(ms / 60000), hours: ms / 3600000 };
}
```

**Step 3: Verify manually**

Open the dashboard. Confirm:
- Each card shows a colored badge matching its exact status
- Time-in-status appears (e.g., "5m", "2h", "3d")
- Stale tasks (>24h) show amber time label
- Agent role shows in dim text next to agent name
- Blocked tasks show "blocked by #N" links
- Clicking a blocker link opens that task's detail

**Step 4: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(ui): enhanced cards with status badges, time-in-status, role, blockers"
```

---

### Task 7: Frontend — Activity feed panel

**Files:**
- Modify: `dashboard/index.html` — add HTML, JS functions, integrate with SSE

**Step 1: Add feed panel HTML**

Add after the bottom sheet `</div>` (after line 777, before the loading overlay):

```html
  <!-- Feed Panel -->
  <div id="feed-panel" class="feed-panel">
    <div class="feed-header">
      <span class="feed-header-title"># Activity Feed</span>
      <button onclick="toggleFeed()" class="btn-terminal" style="padding: 0.125rem 0.5rem; font-size: 0.65rem;">ESC</button>
    </div>
    <div id="feed-filters" class="feed-filters"></div>
    <div id="feed-body" class="feed-body">
      <div class="feed-empty">-- no activity --</div>
    </div>
  </div>
```

**Step 2: Add FEED button to header**

In the header-right div (line 738), add before the FX button:

```html
        <button id="feed-toggle" class="btn-terminal" onclick="toggleFeed()" aria-label="Toggle activity feed">
          FEED
        </button>
```

**Step 3: Add feed JS functions**

Add in the ACTIONS section:

```javascript
// ═══════════════════════════════════════════
// FEED
// ═══════════════════════════════════════════
function toggleFeed() {
  state.feedOpen = !state.feedOpen;
  const panel = document.getElementById('feed-panel');
  const btn = document.getElementById('feed-toggle');
  if (state.feedOpen) {
    fetchFeed();
    panel.classList.add('visible');
    btn.classList.add('active');
    // Add bottom padding to board so content isn't hidden behind feed
    document.getElementById('board').style.paddingBottom = 'calc(40vh + 2rem)';
  } else {
    panel.classList.remove('visible');
    btn.classList.remove('active');
    document.getElementById('board').style.paddingBottom = '6rem';
  }
}

async function fetchFeed() {
  try {
    let url = `/api/feed?token=${state.token}&limit=30`;
    if (state.feedAgentFilter) {
      url += `&agent=${encodeURIComponent(state.feedAgentFilter)}`;
    }
    const data = await api.get(url.replace(`/api/feed?token=${state.token}&`, '/api/feed?').replace('/api/feed?token=' + state.token, '/api/feed'));
  } catch(e) {
    // Simpler: just use the api helper
  }

  try {
    let endpoint = `/api/feed?limit=30`;
    if (state.feedAgentFilter) {
      endpoint += `&agent=${encodeURIComponent(state.feedAgentFilter)}`;
    }
    const res = await fetch(`${endpoint}&token=${state.token}`);
    if (!res.ok) return;
    const data = await res.json();
    state.feedEntries = data.entries;
    renderFeed();
  } catch (e) {
    console.error('Feed fetch error:', e);
  }
}

function renderFeed() {
  // Render filter pills
  const filtersEl = document.getElementById('feed-filters');
  const uniqueAgents = [...new Set(state.agents.map(a => a.name))];
  filtersEl.innerHTML = uniqueAgents.map(name => {
    const isActive = state.feedAgentFilter === name;
    return `<span class="agent-pill ${isActive ? 'active' : ''}" onclick="toggleAgentFilter('${escapeHtml(name)}')">${escapeHtml(name)}</span>`;
  }).join('');

  // Render entries
  const bodyEl = document.getElementById('feed-body');
  if (state.feedEntries.length === 0) {
    bodyEl.innerHTML = '<div class="feed-empty">-- no activity --</div>';
    return;
  }

  bodyEl.innerHTML = state.feedEntries.map(e => `
    <div class="feed-entry">
      <span class="feed-time">${timeAgo(e.at)}</span>
      <span class="feed-agent">${escapeHtml(e.agent || '')}</span>
      <span class="feed-action">${escapeHtml(e.action)}${e.detail ? ` <span style="color:var(--fg-dim)">${escapeHtml(e.detail)}</span>` : ''}</span>
    </div>
  `).join('');
}
```

**Step 4: Integrate feed refresh with SSE**

In the `es.onmessage` handler (line 1243), change:

```javascript
      if (data.refresh) {
        fetchBoard();
      }
```

to:

```javascript
      if (data.refresh) {
        fetchBoard();
        if (state.feedOpen) fetchFeed();
      }
```

Also in the `visibilitychange` handler (line 1271), add after `fetchBoard();`:

```javascript
    if (state.feedOpen) fetchFeed();
```

**Step 5: Verify manually**

Open the dashboard. Confirm:
- FEED button appears in header
- Clicking FEED opens collapsible panel from bottom
- Feed shows chronological activity entries
- Agent filter pills appear, clicking filters the feed
- Clicking a filtered pill again clears the filter
- Feed auto-refreshes when SSE fires
- ESC in the feed panel closes it

**Step 6: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(ui): add collapsible activity feed panel with agent filtering"
```

---

### Task 8: Frontend — Enhanced detail sheet

**Files:**
- Modify: `dashboard/index.html` — `renderDetail()` function (lines 1028-1115)

**Step 1: Update `renderDetail()`**

In the sheet grid section, add two new cells after the "Created" cell. Change the grid to 3 columns by replacing `grid-template-columns: 1fr 1fr` with `grid-template-columns: 1fr 1fr 1fr` inline on the sheet-grid div, OR add two more cells in a second row (keeping 2-column grid).

Better approach — keep 2-column grid, add a second row with two new cells after the existing 4 cells. Insert after the "Created" grid cell:

```javascript
        <div class="sheet-grid-cell">
          <div class="sheet-grid-label">Time in Status</div>
          <div class="sheet-grid-value">${(() => {
            const age = timeInStatus(task.updated_at || task.created_at);
            if (age.hours < 1) return Math.floor(age.minutes) + 'm';
            if (age.hours < 24) return Math.floor(age.hours) + 'h';
            return Math.floor(age.hours / 24) + 'd';
          })()}</div>
        </div>
        <div class="sheet-grid-cell">
          <div class="sheet-grid-label">Total Duration</div>
          <div class="sheet-grid-value">${(() => {
            const end = task.completed_at || new Date().toISOString();
            const age = timeInStatus(task.created_at);
            if (age.hours < 1) return Math.floor(age.minutes) + 'm';
            if (age.hours < 24) return Math.floor(age.hours) + 'h';
            return Math.floor(age.hours / 24) + 'd';
          })()}</div>
        </div>
```

Also, add a blockers section after the description block. If we have a blocked task, fetch and display blockers. Since we already have the `blocker_ids` from the board data, we can use that:

```javascript
      ${task.status === 'blocked' ? `
        <div style="margin-bottom: 1rem;">
          <div class="sheet-section-title"># Blocked By</div>
          <div id="sheet-blockers" style="font-size: 0.75rem; color: var(--red);">
            Loading blockers...
          </div>
        </div>
      ` : ''}
```

And add a call to load blockers after the detail renders. At the end of the `openDetail` try block (after `content.innerHTML = renderDetail(data.task, data.messages);`), add:

```javascript
    // Load blockers if task is blocked
    if (data.task && data.task.status === 'blocked') {
      loadBlockers(data.task.id);
    }
```

Add the `loadBlockers` function:

```javascript
async function loadBlockers(taskId) {
  const el = document.getElementById('sheet-blockers');
  if (!el) return;
  try {
    const res = await fetch(`/api/task/${taskId}/blockers?token=${state.token}`);
    const data = await res.json();
    if (data.blockers.length === 0) {
      el.textContent = 'No blockers found';
      return;
    }
    el.innerHTML = data.blockers.map(b =>
      `<div style="padding: 0.25rem 0; cursor: pointer;" onclick="closeDetail();setTimeout(()=>openDetail(${b.id}),350)">` +
      `#${b.id} ${escapeHtml(b.subject)} <span style="color:var(--fg-dim)">(${b.status})</span></div>`
    ).join('');
  } catch (e) {
    el.textContent = 'Failed to load blockers';
  }
}
```

**Step 2: Verify manually**

Open a task detail sheet. Confirm:
- "Time in Status" and "Total Duration" cells appear in the grid
- For blocked tasks, a "Blocked By" section appears with clickable blocker links
- Clicking a blocker link closes the current sheet and opens the blocker's detail

**Step 3: Commit**

```bash
git add dashboard/index.html
git commit -m "feat(ui): enhanced detail sheet with duration metrics and blocker links"
```

---

### Task 9: Final integration & cleanup

**Files:**
- Modify: `dashboard/index.html` — minor fixups
- Test: full test suite

**Step 1: Fix the `fetchFeed` function**

The `fetchFeed` function in Task 7 has a messy URL construction. Simplify it to:

```javascript
async function fetchFeed() {
  try {
    let url = `/api/feed?token=${state.token}&limit=30`;
    if (state.feedAgentFilter) {
      url += `&agent=${encodeURIComponent(state.feedAgentFilter)}`;
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    state.feedEntries = data.entries;
    renderFeed();
  } catch (e) {
    console.error('Feed fetch error:', e);
  }
}
```

**Step 2: Add keyboard shortcut for feed**

In the keyboard handler (line 1179), add:

```javascript
  if (e.key === 'f' && state.selectedTask === null && !e.ctrlKey && !e.metaKey) {
    toggleFeed();
  }
```

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --cov=clawctl --cov=dashboard --cov-report=term-missing`
Expected: All tests PASS, no regressions

**Step 4: Manual verification checklist**

- [ ] Board shows 4 groups: Queued, Active, Blocked, Done
- [ ] `review` tasks appear in Active section with purple badge
- [ ] `cancelled` tasks appear in Done section, dimmed
- [ ] Each card has a colored status badge matching its exact status
- [ ] Time-in-status label appears on each card
- [ ] Stale tasks (>24h) show amber time label
- [ ] Agent role appears in dim text on cards
- [ ] Blocked tasks show "blocked by #N" on the card
- [ ] Header shows per-agent indicators with colored dots
- [ ] Clicking agent name in header toggles feed filter
- [ ] FEED button toggles the activity feed panel
- [ ] Feed shows chronological activity entries
- [ ] Agent filter pills in feed work (click to filter, click again to clear)
- [ ] SSE refreshes both board and feed
- [ ] Detail sheet shows Time in Status and Total Duration
- [ ] Detail sheet for blocked tasks shows clickable blocker list
- [ ] Pressing `f` toggles the feed panel
- [ ] ESC closes the detail sheet (existing behavior preserved)
- [ ] FX toggle still works (existing behavior preserved)
- [ ] SYNC button still works (existing behavior preserved)

**Step 5: Final commit**

```bash
git add dashboard/index.html
git commit -m "fix(ui): clean up feed fetch, add keyboard shortcut for feed panel"
```
