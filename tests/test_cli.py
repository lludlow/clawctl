"""Tests for clawctl.cli — Click command interface.

Tests use Click's CliRunner to invoke commands in-process.
Each test documents the expected CLI behavior and output.
"""

import os
from unittest.mock import patch

from click.testing import CliRunner

from clawctl import db
from clawctl.cli import cli


def _invoke(cli_env, args, agent="test-agent"):
    """Helper: invoke CLI command with isolated temp DB."""
    runner, db_path, env = cli_env
    if agent:
        env = {**env, "CLAW_AGENT": agent}
    with (
        patch.object(db, "DB_PATH", db_path),
        patch.object(db, "AGENT", agent or "test-agent"),
        patch.object(db, "AGENT_EXPLICIT", True),
    ):
        return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _init(cli_env):
    """Helper: initialize the database."""
    return _invoke(cli_env, ["init"])


# ── Init ──────────────────────────────────────────────


class TestInitCommand:
    """'clawctl init' creates the database."""

    def test_creates_database(self, cli_env):
        result = _invoke(cli_env, ["init"])
        _, db_path, _ = cli_env
        assert result.exit_code == 0
        assert "Initialized" in result.output
        assert os.path.exists(db_path)


# ── Add ───────────────────────────────────────────────


class TestAddCommand:
    """'clawctl add' creates tasks and prints confirmation."""

    def test_prints_task_id(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["add", "Build feature"])
        assert result.exit_code == 0
        assert "#1" in result.output
        assert "Build feature" in result.output

    def test_with_priority(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["add", "Urgent", "-p", "2"])
        assert result.exit_code == 0

    def test_with_assignee(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["add", "Delegated", "--for", "bob"])
        assert result.exit_code == 0
        assert "bob" in result.output

    def test_with_parent(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Parent"])
        result = _invoke(cli_env, ["add", "Child", "--parent", "1"])
        assert result.exit_code == 0


# ── List ──────────────────────────────────────────────


class TestListCommand:
    """'clawctl list' shows tasks in columnar format."""

    def test_shows_tasks(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task one"])
        _invoke(cli_env, ["add", "Task two"])
        result = _invoke(cli_env, ["list"])
        assert result.exit_code == 0
        assert "Task one" in result.output
        assert "Task two" in result.output

    def test_no_tasks_message(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["list"])
        assert "No tasks found" in result.output

    def test_mine_flag(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "My task", "--for", "test-agent"])
        _invoke(cli_env, ["add", "Other task", "--for", "bob"])
        result = _invoke(cli_env, ["list", "--mine"])
        assert "My task" in result.output
        assert "Other task" not in result.output


# ── Claim ─────────────────────────────────────────────


class TestClaimCommand:
    """'clawctl claim' assigns tasks to the current agent."""

    def test_prints_confirmation(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Free task"])
        result = _invoke(cli_env, ["claim", "1"])
        assert result.exit_code == 0
        assert "Claimed #1" in result.output

    def test_conflict_exits_1(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "bob"])
        result = _invoke(cli_env, ["claim", "1"], agent="alice")
        assert result.exit_code == 1
        assert "already claimed" in result.output


# ── Start ─────────────────────────────────────────────


class TestStartCommand:
    """'clawctl start' begins work on a claimed task."""

    def test_prints_confirmation(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "test-agent"])
        result = _invoke(cli_env, ["start", "1"])
        assert result.exit_code == 0
        assert "Working on #1" in result.output

    def test_not_owner_exits_1(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "alice"])
        result = _invoke(cli_env, ["start", "1"], agent="bob")
        assert result.exit_code == 1


# ── Done ──────────────────────────────────────────────


class TestDoneCommand:
    """'clawctl done' completes tasks."""

    def test_prints_completion(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "test-agent"])
        result = _invoke(cli_env, ["done", "1"])
        assert result.exit_code == 0
        assert "Done #1" in result.output

    def test_with_note(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "test-agent"])
        result = _invoke(cli_env, ["done", "1", "-m", "All tests pass"])
        assert "All tests pass" in result.output

    def test_already_done_no_error(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "test-agent"])
        _invoke(cli_env, ["done", "1"])
        result = _invoke(cli_env, ["done", "1"])
        assert result.exit_code == 0
        assert "already done" in result.output


# ── Review ────────────────────────────────────────────


class TestReviewCommand:
    """'clawctl review' marks task for review."""

    def test_prints_confirmation(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task", "--for", "test-agent"])
        result = _invoke(cli_env, ["review", "1"])
        assert result.exit_code == 0
        assert "review" in result.output


# ── Cancel ────────────────────────────────────────────


class TestCancelCommand:
    """'clawctl cancel' cancels tasks."""

    def test_prints_confirmation(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task"])
        result = _invoke(cli_env, ["cancel", "1"])
        assert result.exit_code == 0
        assert "Cancelled #1" in result.output

    def test_already_cancelled_no_error(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task"])
        _invoke(cli_env, ["cancel", "1"])
        result = _invoke(cli_env, ["cancel", "1"])
        assert result.exit_code == 0
        assert "already" in result.output


# ── Block ─────────────────────────────────────────────


class TestBlockCommand:
    """'clawctl block' creates task dependencies."""

    def test_prints_confirmation(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "First"])
        _invoke(cli_env, ["add", "Second"])
        result = _invoke(cli_env, ["block", "2", "--by", "1"])
        assert result.exit_code == 0
        assert "blocked by" in result.output


# ── Messaging ─────────────────────────────────────────


class TestMsgCommand:
    """'clawctl msg' sends messages between agents."""

    def test_sends_message(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["msg", "bob", "Hello there"])
        assert result.exit_code == 0
        assert "bob" in result.output
        assert "Hello there" in result.output


class TestBroadcastCommand:
    """'clawctl broadcast' sends to all agents."""

    def test_sends_broadcast(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["broadcast", "Meeting at 3pm"])
        assert result.exit_code == 0
        assert "Broadcast" in result.output
        assert "Meeting at 3pm" in result.output


class TestInboxCommand:
    """'clawctl inbox' shows messages."""

    def test_no_messages(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["inbox"])
        assert "No messages" in result.output

    def test_shows_messages(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["broadcast", "Alert!"], agent="alice")
        result = _invoke(cli_env, ["inbox"])
        assert "Alert!" in result.output


# ── Board ─────────────────────────────────────────────


class TestBoardCommand:
    """'clawctl board' shows kanban-style task board."""

    def test_shows_columns(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Pending task"])
        _invoke(cli_env, ["add", "Claimed task", "--for", "test-agent"])
        result = _invoke(cli_env, ["board"])
        assert result.exit_code == 0
        assert "pending" in result.output
        assert "claimed" in result.output


# ── Whoami ────────────────────────────────────────────


class TestWhoamiCommand:
    """'clawctl whoami' shows agent identity."""

    def test_shows_identity(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["whoami"])
        assert result.exit_code == 0
        assert "test-agent" in result.output
        assert "DB:" in result.output


# ── Next ──────────────────────────────────────────────


class TestNextCommand:
    """'clawctl next' shows the highest priority task."""

    def test_shows_next_task(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Low priority"])
        _invoke(cli_env, ["add", "High priority", "-p", "2"])
        result = _invoke(cli_env, ["next"])
        assert result.exit_code == 0
        assert "High priority" in result.output

    def test_no_tasks(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["next"])
        assert "No actionable tasks" in result.output


# ── Fleet & Feed ──────────────────────────────────────


class TestFleetCommand:
    """'clawctl fleet' shows agent status."""

    def test_no_agents(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["fleet"])
        assert "No agents" in result.output

    def test_shows_agents(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["register", "alice", "--role", "planner"])
        result = _invoke(cli_env, ["fleet"])
        assert "alice" in result.output
        assert "planner" in result.output


class TestFeedCommand:
    """'clawctl feed' shows activity log."""

    def test_no_activity(self, cli_env):
        _init(cli_env)
        result = _invoke(cli_env, ["feed"])
        # init doesn't create activity, so feed may be empty or show init
        assert result.exit_code == 0

    def test_shows_activity(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Test task"])
        result = _invoke(cli_env, ["feed"])
        assert "task_created" in result.output


class TestSummaryCommand:
    """'clawctl summary' shows fleet overview."""

    def test_shows_summary(self, cli_env):
        _init(cli_env)
        _invoke(cli_env, ["add", "Task one"])
        _invoke(cli_env, ["register", "alice"])
        result = _invoke(cli_env, ["summary"])
        assert result.exit_code == 0
        assert "SUMMARY" in result.output
        assert "Open tasks" in result.output
