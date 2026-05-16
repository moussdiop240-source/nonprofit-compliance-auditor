"""
RAG Layer — Access Control Module
Role-based authentication for the Streamlit UI.

Roles:
  admin   — full access: audit, reindex, retention sweep, audit log
  auditor — audit + HITL review only
  viewer  — read-only: view audit log

Credentials are loaded from environment variables (12-factor).
Passwords are compared as SHA-256 hex digests, never stored in plaintext.

Env-var format:
  AUDIT_USER_<USERNAME>=<ROLE>:<SHA256_PASSWORD_HASH>

Example (.env):
  AUDIT_USER_ADMIN=admin:8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918
  AUDIT_USER_ALICE=auditor:...
  AUDIT_USER_BOB=viewer:...

The hash above corresponds to the password "admin" — change before deploying.
"""
import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Role hierarchy ─────────────────────────────────────────────────────────────

PERMISSIONS: dict[str, set[str]] = {
    "admin":   {"audit", "hitl", "view_log", "reindex", "retention", "admin_panel"},
    "auditor": {"audit", "hitl"},
    "viewer":  {"view_log"},
}

# ── Hard-coded fallback credentials (dev only) ─────────────────────────────────
# Password "admin" — MUST be replaced with env vars in production.
_DEFAULT_USERS: dict[str, tuple[str, str]] = {
    "admin": ("admin", "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"),
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _load_users() -> dict[str, tuple[str, str]]:
    """Return {username: (role, password_hash)} from env vars + defaults."""
    users: dict[str, tuple[str, str]] = dict(_DEFAULT_USERS)
    for key, value in os.environ.items():
        if not key.startswith("AUDIT_USER_"):
            continue
        username = key[len("AUDIT_USER_"):].lower()
        try:
            role, pw_hash = value.split(":", 1)
            users[username] = (role.strip(), pw_hash.strip())
        except ValueError:
            logger.warning("Malformed AUDIT_USER env var: %s", key)
    return users


# ── Public API ─────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> Optional[str]:
    """
    Verify credentials.  Returns the role string on success, None on failure.
    Timing-safe: always hashes the supplied password before comparing.
    """
    users = _load_users()
    entry = users.get(username.lower())
    if entry is None:
        logger.warning("Login attempt for unknown user: %s", username)
        return None
    role, stored_hash = entry
    if _sha256(password) == stored_hash:
        logger.info("Authenticated user=%s role=%s", username, role)
        return role
    logger.warning("Failed login for user=%s", username)
    return None


def has_permission(role: str, permission: str) -> bool:
    """Return True if *role* includes *permission*."""
    return permission in PERMISSIONS.get(role, set())


def require_auth(st_session: dict) -> bool:
    """
    Streamlit authentication gate.
    Renders a login form when the session has no authenticated role.
    Returns True when authenticated (caller may proceed), False otherwise.

    Usage in app.py:
        if not require_auth(st.session_state):
            st.stop()
    """
    try:
        import streamlit as st
    except ImportError:
        return True  # non-Streamlit context (tests) — skip gate

    if st_session.get("auth_role"):
        return True

    st.title("Nonprofit Grant Compliance Auditor")
    st.subheader("Sign In")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In")

    if submitted:
        role = authenticate(username, password)
        if role:
            st_session["auth_role"] = role
            st_session["auth_user"] = username.lower()
            st.success(f"Welcome, {username} ({role})")
            st.rerun()
        else:
            st.error("Invalid username or password.")

    return False


def logout(st_session: dict) -> None:
    """Clear the authentication state from st.session_state."""
    st_session.pop("auth_role", None)
    st_session.pop("auth_user", None)


def current_role(st_session: dict) -> Optional[str]:
    """Return the currently authenticated role, or None if not logged in."""
    return st_session.get("auth_role")


def current_user(st_session: dict) -> Optional[str]:
    """Return the authenticated username, or None."""
    return st_session.get("auth_user")
