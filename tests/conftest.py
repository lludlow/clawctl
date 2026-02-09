"""Shared fixtures for clawctl tests.

Provides in-memory SQLite databases, Click CLI runner,
and Flask test client — all isolated per test.
"""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner


# ── Helpers ────────────────────────────────────────────


def _load_schema(conn):
    """Load the clawctl schema into a connection."""
    schema_path = Path(__file__).parent.parent / "clawctl" / "schema.sql"
    conn.executescript(schema_path.read_text())


# ── Database fixtures ─────────────────────────────────


@pytest.fixture
def db_conn():
    """Fresh in-memory SQLite connection with schema loaded.

    Each test gets a clean database. Connection uses Row factory
    and has foreign keys enabled, matching production behavior.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _load_schema(conn)
    return conn


@pytest.fixture
def seeded_db(db_conn):
    """Database pre-populated with agents, tasks, and messages.

    Contents:
      - Agents: alice (planner), bob (coder)
      - Tasks: #1 pending, #2 claimed by alice, #3 in_progress by bob
      - Messages: one from alice to bob, one broadcast
    """
    conn = db_conn

    # Agents
    conn.execute(
        "INSERT INTO agents(name, role, last_seen, status) VALUES(?, ?, datetime('now'), ?)",
        ("alice", "planner", "idle"),
    )
    conn.execute(
        "INSERT INTO agents(name, role, last_seen, status) VALUES(?, ?, datetime('now'), ?)",
        ("bob", "coder", "busy"),
    )

    # Tasks
    conn.execute(
        "INSERT INTO tasks(subject, status, priority, created_by) VALUES(?, 'pending', 1, 'alice')",
        ("Design the API",),
    )
    conn.execute(
        "INSERT INTO tasks(subject, status, owner, priority, created_by, claimed_at) "
        "VALUES(?, 'claimed', 'alice', 0, 'alice', datetime('now'))",
        ("Write the docs",),
    )
    conn.execute(
        "INSERT INTO tasks(subject, status, owner, priority, created_by, claimed_at) "
        "VALUES(?, 'in_progress', 'bob', 2, 'alice', datetime('now'))",
        ("Implement auth",),
    )

    # Messages
    conn.execute(
        "INSERT INTO messages(from_agent, to_agent, body, msg_type) VALUES(?, ?, ?, 'comment')",
        ("alice", "bob", "Please review the auth design"),
    )
    conn.execute(
        "INSERT INTO messages(from_agent, to_agent, body, msg_type) VALUES(?, NULL, ?, 'alert')",
        ("alice", "Sprint starts Monday"),
    )

    conn.commit()
    return conn


# ── CLI fixture ───────────────────────────────────────


@pytest.fixture
def cli_env(tmp_path):
    """Provides a CliRunner and temp database path for CLI tests.

    Returns (runner, db_path, env) where env is a dict suitable
    for passing to runner.invoke(env=env).
    """
    db_path = str(tmp_path / "test.db")
    env = {
        "CLAW_DB": db_path,
        "CLAW_AGENT": "test-agent",
    }
    runner = CliRunner()
    return runner, db_path, env


# ── Flask fixture ─────────────────────────────────────


@pytest.fixture
def flask_client(tmp_path):
    """Flask test client with auth token pre-configured.

    Returns (client, token) tuple. The client has CLAW_DB pointed
    at a fresh temp database with schema loaded.
    """
    db_path = str(tmp_path / "test.db")
    token = "test-token-123"

    with patch.dict(os.environ, {"CLAW_DB": db_path}):
        # Reload db module to pick up new DB_PATH
        import clawctl.db as db_mod

        old_path = db_mod.DB_PATH
        db_mod.DB_PATH = db_path

        # Initialize DB
        db_mod.init_db()

        # Import server after patching
        import dashboard.server as srv

        srv.TOKEN = token
        srv.app.config["TESTING"] = True

        client = srv.app.test_client()
        yield client, token

        db_mod.DB_PATH = old_path
