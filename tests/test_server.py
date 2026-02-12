"""Tests for dashboard.server — Flask API endpoints.

Tests use Flask's test client with a fresh temp database.
Auth token is pre-configured for each test.
"""

import json

from clawctl import db


# ── Board API ─────────────────────────────────────────


class TestBoardApi:
    """GET /api/board returns tasks and agents."""

    def test_returns_json(self, flask_client):
        client, token = flask_client
        resp = client.get(f"/api/board?token={token}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tasks" in data
        assert "agents" in data
        assert "timestamp" in data

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.get("/api/board")
        assert resp.status_code == 401

    def test_wrong_token_rejected(self, flask_client):
        client, _ = flask_client
        resp = client.get("/api/board?token=wrong")
        assert resp.status_code == 401


# ── Task Detail API ───────────────────────────────────


class TestTaskDetailApi:
    """GET /api/task/<id> returns task and messages."""

    def test_returns_task(self, flask_client):
        client, token = flask_client
        # Create a task
        with db.get_db() as conn:
            db.add_task(conn, "Test task", created_by="test")
        resp = client.get(f"/api/task/1?token={token}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["task"]["subject"] == "Test task"
        assert isinstance(data["messages"], list)

    def test_nonexistent_task(self, flask_client):
        client, token = flask_client
        resp = client.get(f"/api/task/999?token={token}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["task"] is None


# ── Complete Endpoint ─────────────────────────────────


class TestCompleteEndpoint:
    """POST /api/task/<id>/complete marks task done."""

    def test_completes_task(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task to complete", created_by="test")
        resp = client.post(
            f"/api/task/1/complete?token={token}",
            data=json.dumps({"agent": "dashboard", "note": "Done from UI"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ── Delete Endpoint ───────────────────────────────────


class TestDeleteEndpoint:
    """POST /api/task/<id>/delete cancels a task."""

    def test_cancels_task(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task to cancel", created_by="test")
        resp = client.post(
            f"/api/task/1/delete?token={token}",
            data=json.dumps({"agent": "dashboard"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_already_done_returns_409(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task", created_by="test", assignee="test")
            db.register_agent(conn, "test")
            db.complete_task(conn, 1, "test")
        resp = client.post(
            f"/api/task/1/delete?token={token}",
            data=json.dumps({"agent": "dashboard"}),
            content_type="application/json",
        )
        # cancel_task returns (True, "already done") which is idempotent, not 409
        # The server only returns 409 when ok=False
        assert resp.status_code == 200


# ── Heartbeat SSE ─────────────────────────────────────


class TestHeartbeat:
    """GET /api/heartbeat requires auth like other API endpoints."""

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.get("/api/heartbeat")
        assert resp.status_code == 401


# ── Static Files ─────────────────────────────────────


class TestStaticFiles:
    """Static file serving doesn't require auth."""

    def test_index_no_auth(self, flask_client):
        client, _ = flask_client
        resp = client.get("/")
        assert resp.status_code == 200


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


# ── Approve Endpoint ────────────────────────────────


class TestApproveEndpoint:
    """POST /api/task/<id>/approve moves review task to done."""

    def test_approves_review_task(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task to approve", created_by="test", assignee="bob")
            db.register_agent(conn, "bob")
            db.review_task(conn, 1, "bob")
        resp = client.post(
            f"/api/task/1/approve?token={token}",
            data=json.dumps({"agent": "dashboard", "note": "Looks good"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_approve_non_review_returns_409(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Pending task", created_by="test")
        resp = client.post(
            f"/api/task/1/approve?token={token}",
            data=json.dumps({"agent": "dashboard"}),
            content_type="application/json",
        )
        assert resp.status_code == 409
        assert resp.get_json()["success"] is False

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.post("/api/task/1/approve")
        assert resp.status_code == 401


# ── Reject Endpoint ─────────────────────────────────


class TestRejectEndpoint:
    """POST /api/task/<id>/reject moves review task back to pending."""

    def test_rejects_review_task(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task to reject", created_by="test", assignee="bob")
            db.register_agent(conn, "bob")
            db.review_task(conn, 1, "bob")
        resp = client.post(
            f"/api/task/1/reject?token={token}",
            data=json.dumps({"agent": "dashboard", "reason": "Needs work"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_reject_non_review_returns_409(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Pending task", created_by="test")
        resp = client.post(
            f"/api/task/1/reject?token={token}",
            data=json.dumps({"agent": "dashboard"}),
            content_type="application/json",
        )
        assert resp.status_code == 409
        assert resp.get_json()["success"] is False

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.post("/api/task/1/reject")
        assert resp.status_code == 401


# ── Reset Endpoint ──────────────────────────────────


class TestResetEndpoint:
    """POST /api/task/<id>/reset moves task back to pending."""

    def test_resets_cancelled_task(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Task to reset", created_by="test")
            db.cancel_task(conn, 1, "test")
        resp = client.post(
            f"/api/task/1/reset?token={token}",
            data=json.dumps({"agent": "dashboard"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.post("/api/task/1/reset")
        assert resp.status_code == 401


# ── Search Endpoint ─────────────────────────────────


class TestSearchEndpoint:
    """GET /api/search returns matching tasks and messages."""

    def test_returns_matching_tasks(self, flask_client):
        client, token = flask_client
        with db.get_db() as conn:
            db.add_task(conn, "Fix login bug", created_by="test")
            db.add_task(conn, "Update readme", created_by="test")
        resp = client.get(f"/api/search?token={token}&q=login")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["subject"] == "Fix login bug"

    def test_empty_query_returns_empty(self, flask_client):
        client, token = flask_client
        resp = client.get(f"/api/search?token={token}&q=")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["tasks"] == []
        assert data["messages"] == []

    def test_requires_token(self, flask_client):
        client, _ = flask_client
        resp = client.get("/api/search?q=test")
        assert resp.status_code == 401
