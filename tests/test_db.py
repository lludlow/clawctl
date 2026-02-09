"""Tests for clawctl.db — the database layer.

Each test documents expected behavior of a public function.
Tests use in-memory SQLite via the db_conn/seeded_db fixtures.
"""

from unittest.mock import patch

from clawctl import db


# ── Init & Schema ─────────────────────────────────────


class TestInitDb:
    """Database initialization creates all tables and is safe to re-run."""

    def test_creates_all_tables(self, db_conn):
        tables = {
            row["name"]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"tasks", "task_deps", "messages", "agents", "activity"} <= tables

    def test_is_idempotent(self, db_conn):
        """Running schema twice doesn't error (CREATE IF NOT EXISTS)."""
        from pathlib import Path

        schema = (Path(__file__).parent.parent / "clawctl" / "schema.sql").read_text()
        db_conn.executescript(schema)  # second load — should not raise

    def test_wal_mode_on_file_db(self, tmp_path):
        """init_db enables WAL journal mode on file-backed databases."""
        db_path = str(tmp_path / "test.db")
        with patch.object(db, "DB_PATH", db_path):
            db.init_db()
            import sqlite3

            conn = sqlite3.connect(db_path)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
        assert mode == "wal"


# ── Activity Logging ──────────────────────────────────


class TestLogActivity:
    """Every mutation records an activity entry."""

    def test_inserts_activity_row(self, db_conn):
        db.log_activity(db_conn, "alice", "test_action", "task", 1, "detail text")
        row = db_conn.execute("SELECT * FROM activity").fetchone()
        assert row["agent"] == "alice"
        assert row["action"] == "test_action"
        assert row["detail"] == "detail text"

    def test_stores_metadata(self, db_conn):
        db.log_activity(db_conn, "alice", "act", "task", 1, meta='{"key": "val"}')
        row = db_conn.execute("SELECT meta FROM activity").fetchone()
        assert row["meta"] == '{"key": "val"}'


# ── Agent Operations ──────────────────────────────────


class TestAgents:
    """Agent registration, check-in, and info queries."""

    def test_register_creates_agent(self, db_conn):
        ok, _ = db.register_agent(db_conn, "alice", "planner")
        row = db_conn.execute(
            "SELECT name, role, status FROM agents WHERE name='alice'"
        ).fetchone()
        assert ok is True
        assert row["role"] == "planner"
        assert row["status"] == "idle"

    def test_register_logs_activity(self, db_conn):
        db.register_agent(db_conn, "alice", "planner")
        row = db_conn.execute(
            "SELECT action FROM activity WHERE agent='alice'"
        ).fetchone()
        assert row["action"] == "agent_registered"

    def test_checkin_updates_last_seen(self, db_conn):
        db.register_agent(db_conn, "alice")
        db.checkin_agent(db_conn, "alice")
        row = db_conn.execute(
            "SELECT last_seen FROM agents WHERE name='alice'"
        ).fetchone()
        assert row["last_seen"] is not None

    def test_checkin_detects_busy_from_tasks(self, db_conn):
        """Agent with in_progress tasks is detected as busy on checkin."""
        db.register_agent(db_conn, "bob")
        db_conn.execute(
            "INSERT INTO tasks(subject, status, owner) VALUES('work', 'in_progress', 'bob')"
        )
        db.checkin_agent(db_conn, "bob")
        row = db_conn.execute("SELECT status FROM agents WHERE name='bob'").fetchone()
        assert row["status"] == "busy"

    def test_checkin_detects_idle(self, db_conn):
        """Agent with no in_progress tasks is idle on checkin."""
        db.register_agent(db_conn, "bob")
        db.checkin_agent(db_conn, "bob")
        row = db_conn.execute("SELECT status FROM agents WHERE name='bob'").fetchone()
        assert row["status"] == "idle"

    def test_unread_count(self, seeded_db):
        """Counts only direct messages, not broadcasts."""
        count = db.get_unread_count(seeded_db, "bob")
        assert count == 1  # one direct message from alice

    def test_get_agent_info_registered(self, db_conn):
        db.register_agent(db_conn, "alice", "planner")
        assert db.get_agent_info(db_conn, "alice") == "planner"

    def test_get_agent_info_unregistered(self, db_conn):
        assert db.get_agent_info(db_conn, "nobody") == "unregistered"


# ── Task Creation ─────────────────────────────────────


class TestAddTask:
    """Task creation with various options."""

    def test_returns_task_id(self, db_conn):
        ok, task_id = db.add_task(db_conn, "Build feature")
        assert ok is True
        assert task_id == 1

    def test_default_status_is_pending(self, db_conn):
        _, task_id = db.add_task(db_conn, "Build feature")
        row = db_conn.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["status"] == "pending"

    def test_assignee_sets_claimed_status(self, db_conn):
        """When assignee is provided, status is 'claimed' and claimed_at is set."""
        _, task_id = db.add_task(db_conn, "Review PR", assignee="bob")
        row = db_conn.execute(
            "SELECT status, owner, claimed_at FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["status"] == "claimed"
        assert row["owner"] == "bob"
        assert row["claimed_at"] is not None

    def test_priority_stored(self, db_conn):
        _, task_id = db.add_task(db_conn, "Urgent fix", priority=2)
        row = db_conn.execute(
            "SELECT priority FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["priority"] == 2

    def test_parent_id_stored(self, db_conn):
        _, parent_id = db.add_task(db_conn, "Parent")
        _, child_id = db.add_task(db_conn, "Child", parent_id=parent_id)
        row = db_conn.execute(
            "SELECT parent_id FROM tasks WHERE id=?", (child_id,)
        ).fetchone()
        assert row["parent_id"] == parent_id

    def test_logs_activity(self, db_conn):
        db.add_task(db_conn, "Test task", created_by="alice")
        row = db_conn.execute(
            "SELECT action, detail FROM activity WHERE agent='alice'"
        ).fetchone()
        assert row["action"] == "task_created"
        assert row["detail"] == "Test task"


# ── Claim ─────────────────────────────────────────────


class TestClaimTask:
    """Claiming tasks with atomic race-safe updates."""

    def test_claim_unowned_task(self, db_conn):
        _, task_id = db.add_task(db_conn, "Free task")
        ok, err = db.claim_task(db_conn, task_id, "alice")
        assert ok is True
        assert err is None
        row = db_conn.execute(
            "SELECT owner, status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["owner"] == "alice"
        assert row["status"] == "claimed"

    def test_claim_already_owned_by_another_fails(self, db_conn):
        """Race safety: can't claim a task owned by someone else."""
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, err = db.claim_task(db_conn, task_id, "bob")
        assert ok is False
        assert "already claimed by alice" in err

    def test_claim_own_task_succeeds(self, db_conn):
        """Re-claiming your own task is allowed (idempotent)."""
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, _ = db.claim_task(db_conn, task_id, "alice")
        assert ok is True

    def test_force_claim_overrides_owner(self, db_conn):
        """force=True lets you steal a task from another agent."""
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, _ = db.claim_task(db_conn, task_id, "bob", force=True)
        assert ok is True
        row = db_conn.execute(
            "SELECT owner FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["owner"] == "bob"

    def test_claim_nonexistent_task(self, db_conn):
        ok, err = db.claim_task(db_conn, 999, "alice")
        assert ok is False
        assert err == "not found"


# ── Start ─────────────────────────────────────────────


class TestStartTask:
    """Starting work transitions task to in_progress."""

    def test_start_sets_in_progress(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        ok, _ = db.start_task(db_conn, task_id, "alice")
        assert ok is True
        row = db_conn.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["status"] == "in_progress"

    def test_start_sets_agent_busy(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        db.start_task(db_conn, task_id, "alice")
        row = db_conn.execute("SELECT status FROM agents WHERE name='alice'").fetchone()
        assert row["status"] == "busy"

    def test_start_not_owner_fails(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, err = db.start_task(db_conn, task_id, "bob")
        assert ok is False
        assert "not owned by you" in err

    def test_start_nonexistent_fails(self, db_conn):
        ok, err = db.start_task(db_conn, 999, "alice")
        assert ok is False
        assert err == "not found"


# ── Complete ──────────────────────────────────────────


class TestCompleteTask:
    """Completing tasks with idempotency and force option."""

    def test_complete_sets_done(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        ok, _ = db.complete_task(db_conn, task_id, "alice")
        assert ok is True
        row = db_conn.execute(
            "SELECT status, completed_at FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["status"] == "done"
        assert row["completed_at"] is not None

    def test_complete_already_done_is_idempotent(self, db_conn):
        """Completing an already-done task returns (True, 'already done')."""
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        db.complete_task(db_conn, task_id, "alice")
        ok, info = db.complete_task(db_conn, task_id, "alice")
        assert ok is True
        assert info == "already done"

    def test_complete_not_owner_fails(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, err = db.complete_task(db_conn, task_id, "bob")
        assert ok is False
        assert "not owned by you" in err

    def test_complete_force_bypasses_owner(self, db_conn):
        """force=True allows completing tasks you don't own."""
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "bob")
        ok, _ = db.complete_task(db_conn, task_id, "bob", force=True)
        assert ok is True

    def test_complete_with_note_creates_message(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        db.complete_task(db_conn, task_id, "alice", note="All tests pass")
        msg = db_conn.execute(
            "SELECT body, msg_type FROM messages WHERE task_id=?", (task_id,)
        ).fetchone()
        assert msg["body"] == "All tests pass"
        assert msg["msg_type"] == "status"

    def test_complete_sets_agent_idle(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        db.start_task(db_conn, task_id, "alice")
        db.complete_task(db_conn, task_id, "alice")
        row = db_conn.execute("SELECT status FROM agents WHERE name='alice'").fetchone()
        assert row["status"] == "idle"

    def test_complete_nonexistent_fails(self, db_conn):
        ok, err = db.complete_task(db_conn, 999, "alice")
        assert ok is False
        assert err == "not found"


# ── Cancel ────────────────────────────────────────────


class TestCancelTask:
    """Cancelling tasks with idempotent behavior."""

    def test_cancel_sets_cancelled(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task")
        ok, _ = db.cancel_task(db_conn, task_id, "alice")
        assert ok is True
        row = db_conn.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["status"] == "cancelled"

    def test_cancel_already_done_is_idempotent(self, db_conn):
        """Cancelling a done task returns (True, 'already done')."""
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        db.register_agent(db_conn, "alice")
        db.complete_task(db_conn, task_id, "alice")
        ok, info = db.cancel_task(db_conn, task_id, "alice")
        assert ok is True
        assert "already done" in info

    def test_cancel_nonexistent_fails(self, db_conn):
        ok, err = db.cancel_task(db_conn, 999, "alice")
        assert ok is False
        assert err == "not found"


# ── Review ────────────────────────────────────────────


class TestReviewTask:
    """Moving tasks to review status."""

    def test_review_sets_status(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, _ = db.review_task(db_conn, task_id, "alice")
        assert ok is True
        row = db_conn.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row["status"] == "review"

    def test_review_not_owner_fails(self, db_conn):
        _, task_id = db.add_task(db_conn, "Task", assignee="alice")
        ok, err = db.review_task(db_conn, task_id, "bob")
        assert ok is False
        assert "not owned by you" in err


# ── Blocking & Dependencies ───────────────────────────


class TestBlocking:
    """Task dependencies and blocking behavior."""

    def test_block_creates_dependency(self, db_conn):
        _, t1 = db.add_task(db_conn, "First")
        _, t2 = db.add_task(db_conn, "Second")
        ok, _ = db.block_task(db_conn, t2, t1)
        assert ok is True
        row = db_conn.execute(
            "SELECT * FROM task_deps WHERE task_id=? AND blocked_by=?", (t2, t1)
        ).fetchone()
        assert row is not None

    def test_block_sets_status_blocked(self, db_conn):
        _, t1 = db.add_task(db_conn, "First")
        _, t2 = db.add_task(db_conn, "Second")
        db.block_task(db_conn, t2, t1)
        row = db_conn.execute("SELECT status FROM tasks WHERE id=?", (t2,)).fetchone()
        assert row["status"] == "blocked"

    def test_duplicate_block_handled_gracefully(self, db_conn):
        """UNIQUE constraint violation returns error, doesn't raise."""
        _, t1 = db.add_task(db_conn, "First")
        _, t2 = db.add_task(db_conn, "Second")
        db.block_task(db_conn, t2, t1)
        ok, err = db.block_task(db_conn, t2, t1)
        assert ok is False
        assert "already exists" in err

    def test_get_blockers_returns_blocking_tasks(self, db_conn):
        _, t1 = db.add_task(db_conn, "Blocker")
        _, t2 = db.add_task(db_conn, "Blocked")
        db.block_task(db_conn, t2, t1)
        blockers = db.get_blockers(db_conn, t2)
        assert len(blockers) == 1
        assert blockers[0]["id"] == t1
        assert blockers[0]["subject"] == "Blocker"


# ── Listing & Queries ─────────────────────────────────


class TestListTasks:
    """Task listing with filtering and sort behavior."""

    def test_excludes_done_by_default(self, seeded_db):
        """list_tasks() without include_all omits done/cancelled."""
        # Complete a task first
        db.register_agent(seeded_db, "bob")
        db.complete_task(seeded_db, 3, "bob")
        rows = db.list_tasks(seeded_db)
        statuses = [row["status"] for row in rows]
        assert "done" not in statuses

    def test_include_all_shows_done(self, seeded_db):
        """include_all=True includes done/cancelled tasks."""
        db.register_agent(seeded_db, "bob")
        db.complete_task(seeded_db, 3, "bob")
        rows = db.list_tasks(seeded_db, include_all=True)
        statuses = [row["status"] for row in rows]
        assert "✓" in [row["icon"] for row in rows]

    def test_filter_by_status(self, seeded_db):
        rows = db.list_tasks(seeded_db, status="pending")
        assert all(row["status"] == "pending" for row in rows)

    def test_filter_by_owner(self, seeded_db):
        rows = db.list_tasks(seeded_db, owner="alice")
        assert all(row["owner"] == "alice" for row in rows)

    def test_active_sort_order(self, seeded_db):
        """Active listing sorts: in_progress > claimed > pending."""
        rows = db.list_tasks(seeded_db)
        icons = [row["icon"] for row in rows]
        # in_progress (▶) should come before claimed (◉) before pending (○)
        assert icons.index("▶") < icons.index("◉")
        assert icons.index("◉") < icons.index("○")


class TestGetNextTask:
    """Next task prioritizes agent's own work, then unowned."""

    def test_returns_own_in_progress_first(self, seeded_db):
        """Agent's in_progress task is the highest priority next task."""
        row = db.get_next_task(seeded_db, "bob")
        assert row["id"] == 3  # bob's in_progress task
        assert row["status"] == "in_progress"

    def test_returns_unowned_if_no_own_tasks(self, seeded_db):
        row = db.get_next_task(seeded_db, "charlie")
        assert row["id"] == 1  # the pending unowned task

    def test_returns_none_when_no_actionable(self, db_conn):
        row = db.get_next_task(db_conn, "alice")
        assert row is None


class TestGetBoard:
    """Board view groups tasks by status."""

    def test_groups_by_status(self, seeded_db):
        board = db.get_board(seeded_db)
        assert "pending" in board
        assert "claimed" in board
        assert "in_progress" in board
        assert board["pending"]["count"] == 1
        assert board["claimed"]["count"] == 1
        assert board["in_progress"]["count"] == 1

    def test_empty_statuses_excluded(self, seeded_db):
        board = db.get_board(seeded_db)
        assert "done" not in board  # no done tasks in seed data


# ── Messaging ─────────────────────────────────────────


class TestMessaging:
    """Message sending, broadcasting, inbox, and read tracking."""

    def test_send_message(self, db_conn):
        ok, _ = db.send_message(db_conn, "alice", "bob", "Hello", msg_type="comment")
        assert ok is True
        row = db_conn.execute("SELECT * FROM messages").fetchone()
        assert row["from_agent"] == "alice"
        assert row["to_agent"] == "bob"
        assert row["body"] == "Hello"

    def test_send_with_task_id(self, db_conn):
        db.add_task(db_conn, "Task")
        db.send_message(db_conn, "alice", "bob", "Note", task_id=1)
        row = db_conn.execute("SELECT task_id FROM messages").fetchone()
        assert row["task_id"] == 1

    def test_broadcast_sets_null_to_agent(self, db_conn):
        ok, _ = db.broadcast(db_conn, "alice", "All hands meeting")
        assert ok is True
        row = db_conn.execute("SELECT to_agent, msg_type FROM messages").fetchone()
        assert row["to_agent"] is None
        assert row["msg_type"] == "alert"

    def test_inbox_shows_direct_and_broadcasts(self, seeded_db):
        """Bob's inbox includes direct messages and broadcasts."""
        rows = db.get_inbox(seeded_db, "bob")
        assert len(rows) == 2

    def test_inbox_unread_only(self, seeded_db):
        """unread_only=True filters to messages with read_at IS NULL."""
        rows = db.get_inbox(seeded_db, "bob", unread_only=True)
        assert len(rows) == 2  # both unread initially

    def test_mark_read_specific_ids(self, seeded_db):
        rows = db.get_inbox(seeded_db, "bob")
        msg_id = rows[0]["id"]
        db.mark_messages_read(seeded_db, "bob", [msg_id])
        unread = db.get_inbox(seeded_db, "bob", unread_only=True)
        assert len(unread) == 1

    def test_mark_all_read(self, seeded_db):
        """mark_messages_read without IDs marks direct messages only.

        Broadcasts (to_agent=NULL) are not marked read by the agent-scoped
        bulk operation — this is correct because broadcasts don't belong
        to a specific agent.
        """
        db.mark_messages_read(seeded_db, "bob")
        unread = db.get_inbox(seeded_db, "bob", unread_only=True)
        # Only the broadcast remains unread (to_agent IS NULL)
        assert len(unread) == 1
        assert unread[0]["from_agent"] == "alice"


# ── Fleet & Feed ──────────────────────────────────────


class TestFleetAndFeed:
    """Fleet status and activity feed queries."""

    def test_fleet_shows_agents(self, seeded_db):
        rows = db.get_fleet(seeded_db)
        names = [row["name"] for row in rows]
        assert "alice" in names
        assert "bob" in names

    def test_fleet_shows_working_on(self, seeded_db):
        """Busy agent shows current task subject."""
        rows = db.get_fleet(seeded_db)
        bob = next(r for r in rows if r["name"] == "bob")
        assert bob["working_on"] == "Implement auth"

    def test_feed_returns_activity(self, db_conn):
        db.log_activity(db_conn, "alice", "test", "task", 1, "detail")
        rows = db.get_feed(db_conn)
        assert len(rows) == 1
        assert rows[0]["agent"] == "alice"

    def test_feed_agent_filter(self, db_conn):
        db.log_activity(db_conn, "alice", "act1", "task", 1)
        db.log_activity(db_conn, "bob", "act2", "task", 2)
        rows = db.get_feed(db_conn, agent_filter="alice")
        assert len(rows) == 1
        assert rows[0]["agent"] == "alice"

    def test_feed_respects_limit(self, db_conn):
        for i in range(10):
            db.log_activity(db_conn, "alice", f"act{i}", "task", i)
        rows = db.get_feed(db_conn, limit=3)
        assert len(rows) == 3


# ── Summary ───────────────────────────────────────────


class TestSummary:
    """Summary aggregates fleet and task stats."""

    def test_summary_counts(self, seeded_db):
        data = db.get_summary(seeded_db)
        assert data["open"] == 3  # pending + claimed + in_progress
        assert data["in_progress"] == 1
        assert data["blocked"] == 0
        assert len(data["agents"]) == 2


# ── API Helpers ───────────────────────────────────────


class TestApiHelpers:
    """Helpers used by the Flask dashboard."""

    def test_board_api_returns_tasks_and_agents(self, seeded_db):
        tasks, agents = db.get_board_api(seeded_db)
        assert len(tasks) == 3
        assert len(agents) == 2

    def test_task_detail_returns_task_and_messages(self, seeded_db):
        # Add a message for task 3
        db.send_message(seeded_db, "bob", "alice", "Working on it", task_id=3)
        task, messages = db.get_task_detail(seeded_db, 3)
        assert task["subject"] == "Implement auth"
        assert len(messages) == 1

    def test_task_detail_nonexistent(self, db_conn):
        task, messages = db.get_task_detail(db_conn, 999)
        assert task is None
        assert messages == []
