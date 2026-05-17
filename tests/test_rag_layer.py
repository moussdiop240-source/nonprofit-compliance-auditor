"""
Tests for rag_layer: entity_mapper, pseudonymizer, retention_policy, access_control.
All tests are self-contained and use temp directories / in-memory state.
"""
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── entity_mapper ────────────────────────────────────────────────────────────

class TestEntityMapper:
    def test_create_and_complete_session(self, tmp_path, monkeypatch):
        from rag_layer import entity_mapper
        monkeypatch.setattr(entity_mapper, "DB_PATH", tmp_path / "audit_log.db")

        sid = entity_mapper.create_session("Test Org", "G-001", "expenses text", "grant text")
        assert len(sid) == 36  # UUID format

        entity_mapper.complete_session(sid, item_count=5, allowable=1000.0, unallowable=50.0)

        sessions = entity_mapper.list_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert s["organization"] == "Test Org"
        assert s["grant_number"] == "G-001"
        assert s["item_count"] == 5
        assert s["allowable"] == 1000.0
        assert s["unallowable"] == 50.0
        assert s["status"] == "complete"
        assert s["session_id"].endswith("…")  # truncated

    def test_hashes_not_raw_text(self, tmp_path, monkeypatch):
        from rag_layer import entity_mapper
        monkeypatch.setattr(entity_mapper, "DB_PATH", tmp_path / "audit_log.db")

        entity_mapper.create_session("Org", "G-002", "raw expense data", "raw grant data")

        con = sqlite3.connect(str(tmp_path / "audit_log.db"))
        row = con.execute("SELECT expense_hash, grant_hash FROM audit_sessions").fetchone()
        con.close()
        assert row[0] != "raw expense data"
        assert len(row[0]) == 64  # sha256 hex length

    def test_list_sessions_empty(self, tmp_path, monkeypatch):
        from rag_layer import entity_mapper
        monkeypatch.setattr(entity_mapper, "DB_PATH", tmp_path / "audit_log.db")
        assert entity_mapper.list_sessions() == []

    def test_list_sessions_filter_by_search(self, tmp_path, monkeypatch):
        from rag_layer import entity_mapper
        monkeypatch.setattr(entity_mapper, "DB_PATH", tmp_path / "audit_log.db")

        entity_mapper.create_session("Alpha Org", "G-100", "exp", "grant")
        entity_mapper.create_session("Beta Org", "G-200", "exp", "grant")

        hits = entity_mapper.list_sessions(search="Alpha")
        assert len(hits) == 1
        assert hits[0]["organization"] == "Alpha Org"

        no_hits = entity_mapper.list_sessions(search="ZZZ")
        assert no_hits == []

    def test_list_sessions_filter_by_status(self, tmp_path, monkeypatch):
        from rag_layer import entity_mapper
        monkeypatch.setattr(entity_mapper, "DB_PATH", tmp_path / "audit_log.db")

        sid = entity_mapper.create_session("Org", "G-1", "exp", "grant")
        entity_mapper.create_session("Org", "G-2", "exp", "grant")
        entity_mapper.complete_session(sid, item_count=3, allowable=500.0, unallowable=0.0)

        complete_sessions = entity_mapper.list_sessions(status_filter="complete")
        assert len(complete_sessions) == 1
        assert complete_sessions[0]["status"] == "complete"

        started_sessions = entity_mapper.list_sessions(status_filter="started")
        assert len(started_sessions) == 1
        assert started_sessions[0]["status"] == "started"

    def test_list_sessions_filter_by_date(self, tmp_path, monkeypatch):
        from rag_layer import entity_mapper
        import sqlite3
        monkeypatch.setattr(entity_mapper, "DB_PATH", tmp_path / "audit_log.db")

        # Create session then manually backdate one record
        sid1 = entity_mapper.create_session("Old Org", "G-OLD", "exp", "grant")
        sid2 = entity_mapper.create_session("New Org", "G-NEW", "exp", "grant")

        con = sqlite3.connect(str(tmp_path / "audit_log.db"))
        con.execute("UPDATE audit_sessions SET created_at=? WHERE session_id=?",
                    ("2020-06-01T00:00:00", sid1))
        con.commit()
        con.close()

        recent = entity_mapper.list_sessions(date_from="2024-01-01")
        orgs = [r["organization"] for r in recent]
        assert "New Org" in orgs
        assert "Old Org" not in orgs

        old_only = entity_mapper.list_sessions(date_to="2021-12-31")
        orgs2 = [r["organization"] for r in old_only]
        assert "Old Org" in orgs2
        assert "New Org" not in orgs2


# ─── pseudonymizer ────────────────────────────────────────────────────────────

class TestPseudonymizer:
    def test_masks_ssn(self):
        from rag_layer.pseudonymizer import pseudonymize
        text, counts = pseudonymize("Employee SSN: 123-45-6789")
        assert "123-45-6789" not in text
        assert "[SSN-REDACTED]" in text
        assert counts["SSN"] == 1

    def test_masks_email(self):
        from rag_layer.pseudonymizer import pseudonymize
        text, counts = pseudonymize("Contact: alice@example.org for details")
        assert "alice@example.org" not in text
        assert "[EMAIL-REDACTED]" in text

    def test_masks_ein(self):
        from rag_layer.pseudonymizer import pseudonymize
        text, counts = pseudonymize("EIN: 12-3456789")
        assert "12-3456789" not in text
        assert "[EIN-REDACTED]" in text

    def test_masks_phone(self):
        from rag_layer.pseudonymizer import pseudonymize
        text, counts = pseudonymize("Call us at (555) 867-5309")
        assert "867-5309" not in text

    def test_no_pii_unchanged(self):
        from rag_layer.pseudonymizer import pseudonymize
        text = "Travel expense: airfare to Chicago, $450"
        masked, counts = pseudonymize(text)
        assert masked == text
        assert counts == {}

    def test_redaction_summary_none_when_empty(self):
        from rag_layer.pseudonymizer import redaction_summary
        assert redaction_summary({}) is None

    def test_redaction_summary_text(self):
        from rag_layer.pseudonymizer import redaction_summary
        s = redaction_summary({"SSN": 2, "EMAIL": 1})
        assert "SSN" in s
        assert "EMAIL" in s

    def test_pseudonymize_fields(self):
        from rag_layer.pseudonymizer import pseudonymize_fields
        result = pseudonymize_fields({"vendor": "Alice (alice@test.com)", "amount": 100.0})
        assert "alice@test.com" not in result["vendor"]
        assert result["amount"] == 100.0  # non-string untouched


# ─── retention_policy ─────────────────────────────────────────────────────────

class TestRetentionPolicy:
    def test_purge_old_sessions(self, tmp_path, monkeypatch):
        from rag_layer import retention_policy
        monkeypatch.setattr(retention_policy, "DB_PATH", tmp_path / "audit_log.db")

        # Insert an old record manually
        con = sqlite3.connect(str(tmp_path / "audit_log.db"))
        con.execute("""CREATE TABLE audit_sessions (
            session_id TEXT PRIMARY KEY, organization TEXT, grant_number TEXT,
            expense_hash TEXT, grant_hash TEXT, item_count INTEGER,
            allowable REAL, unallowable REAL, status TEXT DEFAULT 'started',
            created_at TEXT, completed_at TEXT)""")
        con.execute("INSERT INTO audit_sessions (session_id, created_at) VALUES ('old-id', '2020-01-01T00:00:00')")
        con.execute("INSERT INTO audit_sessions (session_id, created_at) VALUES ('new-id', '2099-01-01T00:00:00')")
        con.commit()
        con.close()

        deleted = retention_policy.purge_old_sessions(retention_days=365)
        assert deleted == 1

        con2 = sqlite3.connect(str(tmp_path / "audit_log.db"))
        remaining = con2.execute("SELECT session_id FROM audit_sessions").fetchall()
        con2.close()
        assert len(remaining) == 1
        assert remaining[0][0] == "new-id"

    def test_purge_no_db(self, tmp_path, monkeypatch):
        from rag_layer import retention_policy
        monkeypatch.setattr(retention_policy, "DB_PATH", tmp_path / "nonexistent.db")
        assert retention_policy.purge_old_sessions() == 0

    def test_purge_old_stores(self, tmp_path):
        from rag_layer.retention_policy import purge_old_stores
        import time

        # Create a fake old store directory
        old_store = tmp_path / "chroma_grant_abc123"
        old_store.mkdir()
        # Force mtime to be way in the past
        os.utime(str(old_store), (0, 0))

        new_store = tmp_path / "chroma_cfr200"
        new_store.mkdir()
        # mtime is now — should NOT be purged with 1-day retention

        removed = purge_old_stores(base_dir=str(tmp_path), retention_days=1)
        assert any("chroma_grant_abc123" in p for p in removed)
        assert not any("chroma_cfr200" in p for p in removed)

    def test_run_all_returns_summary(self, tmp_path, monkeypatch):
        from rag_layer import retention_policy
        monkeypatch.setattr(retention_policy, "DB_PATH", tmp_path / "audit_log.db")
        summary = retention_policy.run_all(base_dir=str(tmp_path))
        assert "sessions_deleted" in summary
        assert "stores_removed" in summary
        assert "ran_at" in summary


# ─── access_control ───────────────────────────────────────────────────────────

class TestAccessControl:
    def test_authenticate_default_admin(self):
        from rag_layer.access_control import authenticate
        role = authenticate("admin", "admin")
        assert role == "admin"

    def test_authenticate_wrong_password(self):
        from rag_layer.access_control import authenticate
        assert authenticate("admin", "wrongpassword") is None

    def test_authenticate_unknown_user(self):
        from rag_layer.access_control import authenticate
        assert authenticate("nobody", "anything") is None

    def test_authenticate_env_user(self, monkeypatch):
        import hashlib
        from rag_layer.access_control import authenticate
        pw_hash = hashlib.sha256(b"testpass").hexdigest()
        monkeypatch.setenv("AUDIT_USER_TESTUSER", f"auditor:{pw_hash}")
        role = authenticate("testuser", "testpass")
        assert role == "auditor"

    def test_has_permission_admin(self):
        from rag_layer.access_control import has_permission
        assert has_permission("admin", "audit")
        assert has_permission("admin", "admin_panel")
        assert has_permission("admin", "retention")

    def test_has_permission_auditor(self):
        from rag_layer.access_control import has_permission
        assert has_permission("auditor", "audit")
        assert has_permission("auditor", "hitl")
        assert not has_permission("auditor", "admin_panel")
        assert not has_permission("auditor", "view_log")

    def test_has_permission_viewer(self):
        from rag_layer.access_control import has_permission
        assert has_permission("viewer", "view_log")
        assert not has_permission("viewer", "audit")

    def test_has_permission_unknown_role(self):
        from rag_layer.access_control import has_permission
        assert not has_permission("ghost", "audit")

    def test_logout_clears_state(self):
        from rag_layer.access_control import logout
        session = {"auth_role": "admin", "auth_user": "admin", "other": "value"}
        logout(session)
        assert "auth_role" not in session
        assert "auth_user" not in session
        assert session["other"] == "value"

    def test_current_role_and_user(self):
        from rag_layer.access_control import current_role, current_user
        session = {"auth_role": "auditor", "auth_user": "alice"}
        assert current_role(session) == "auditor"
        assert current_user(session) == "alice"

    def test_current_role_none_when_not_logged_in(self):
        from rag_layer.access_control import current_role, current_user
        assert current_role({}) is None
        assert current_user({}) is None
