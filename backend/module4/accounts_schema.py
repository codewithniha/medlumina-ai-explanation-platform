"""
accounts_schema.py  --  Step 2 of the MedLumina dashboards work.

WHAT THIS FILE DOES
Adds the tables that accounts, doctor verification, report versions, stored
files and the audit log need, to the SAME SQLite file session_store.py already
uses (SESSION_DB_PATH, default ./sessions.db). It never drops or rewrites
anything that exists today.

ANALOGY
Think of sessions.db as a hospital records room that so far has only visit
folders. This file adds: a staff/visitor register (users), the credential
folder for doctors (doctor_profiles), wristband stubs (auth_sessions), a
page-history binder for each report (report_versions), a locked cabinet index
for X-ray files (visit_files), and a tamper-evident logbook (audit_log).

TERMS USED (same words as the rest of the project)
  record = one person's whole history = the existing `patients` row (PT-XXXXXX)
  visit  = one upload inside a record = the existing `sessions` row

WHAT CHANGES IN EXISTING TABLES
  patients.owner_user_id  (new, nullable): which account owns this record.
  Old records created before accounts existed keep owner_user_id = NULL. They
  stay in the database but no account can open them (there is no "claim" step).
  Everything else in sessions / patients / turns is untouched.

RULES THE DATABASE ITSELF ENFORCES (so a bug in app code cannot break them)
  - role / status combinations are valid (a patient can never be 'pending')
  - emails are unique, ignoring upper/lower case
  - a doctor marked 'verified' must have verified_at, verified_by and a
    licence expiry date
  - at most ONE final report version per visit
  - the content of a report version can never be edited (insert a new one)
  - audit_log rows can never be updated or deleted
  - foreign keys are enforced on connections made with get_conn()

SENSITIVE DATA RULES
  - PMDC numbers and certificate paths live ONLY in doctor_profiles.
  - Never copy them into audit_log before/after JSON, and never log them.
  - Passwords are never stored: only the argon2id hash (step 3 writes it).
  - Session tokens are never stored: only their SHA-256 hash.
  - Stored X-ray files go in a private folder that is git-ignored
    (backend/module4/private_store/); the database holds only relative paths.

USAGE (run from backend/module4, the folder you start uvicorn from)
  python accounts_schema.py            # self-test on a throwaway database
  python accounts_schema.py --apply    # backup, then migrate your real sessions.db
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(db_path: str | None) -> str:
    if db_path:
        return db_path
    # Imported lazily: importing session_store creates its base tables, which
    # have to exist before this migration alters `patients`.
    import session_store

    return session_store.SESSION_DB_PATH


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    """
    Connection for all account/report code from step 3 on. Differs from
    session_store._get_conn() in one important way: foreign keys are ON
    (SQLite ignores them unless asked on every connection).
    """
    conn = sqlite3.connect(_resolve_db_path(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Migration 1 ──────────────────────────────────────────────────────────────
# One statement per list entry so the whole migration can run inside a single
# explicit transaction (all-or-nothing).
_MIGRATION_1_STATEMENTS = [
    # Accounts. display_id is DR-XXXXXX for doctors and AD-XXXXXX for admins;
    # it stays NULL for patients (a patient is identified to others by the
    # PT-XXXXXX code of their record, and signs in with email).
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id            TEXT PRIMARY KEY,
        role               TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'admin')),
        display_id         TEXT UNIQUE,
        email              TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash      TEXT NOT NULL,
        full_name          TEXT NOT NULL DEFAULT '',
        status             TEXT NOT NULL,
        failed_login_count INTEGER NOT NULL DEFAULT 0,
        locked_until       TEXT,
        created_at         TEXT NOT NULL,
        last_login_at      TEXT,
        CHECK (
            (role = 'doctor' AND status IN ('pending', 'verified', 'rejected', 'disabled'))
            OR
            (role IN ('patient', 'admin') AND status IN ('active', 'disabled'))
        )
    )
    """,
    # users.status is the ONE gate the doctor dashboard checks ('verified').
    # This table keeps the evidence and the reason behind that status.
    """
    CREATE TABLE IF NOT EXISTS doctor_profiles (
        user_id              TEXT PRIMARY KEY REFERENCES users (user_id),
        pmdc_number          TEXT NOT NULL UNIQUE,
        register_full_name   TEXT NOT NULL,
        register_father_name TEXT NOT NULL DEFAULT '',
        certificate_path     TEXT,
        verification_status  TEXT NOT NULL DEFAULT 'pending'
            CHECK (verification_status IN ('pending', 'verified', 'rejected', 'expired')),
        license_valid_upto   TEXT,
        submitted_at         TEXT NOT NULL,
        verified_at          TEXT,
        verified_by          TEXT REFERENCES users (user_id),
        rejection_reason     TEXT,
        CHECK (
            verification_status <> 'verified'
            OR (verified_at IS NOT NULL AND verified_by IS NOT NULL AND license_valid_upto IS NOT NULL)
        )
    )
    """,
    # Server-side login sessions (the "wristband stubs"). Only hashes stored.
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash   TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL REFERENCES users (user_id),
        csrf_hash    TEXT,
        created_at   TEXT NOT NULL,
        expires_at   TEXT NOT NULL,
        last_seen_at TEXT,
        revoked_at   TEXT
    )
    """,
    # Page history of a report. A doctor edit inserts a NEW row; it never
    # changes an old one. Exactly one row per visit may be is_final = 1: that
    # is the version the RAG indexes.
    """
    CREATE TABLE IF NOT EXISTS report_versions (
        version_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id          TEXT NOT NULL REFERENCES sessions (session_id),
        version_no          INTEGER NOT NULL CHECK (version_no >= 1),
        source              TEXT NOT NULL CHECK (source IN ('ai', 'doctor_edit')),
        author_user_id      TEXT REFERENCES users (user_id),
        created_at          TEXT NOT NULL,
        report_text         TEXT NOT NULL,
        structured_findings TEXT,
        is_final            INTEGER NOT NULL DEFAULT 0 CHECK (is_final IN (0, 1)),
        UNIQUE (session_id, version_no),
        CHECK (source = 'ai' OR author_user_id IS NOT NULL)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS one_final_version_per_visit ON report_versions (session_id) WHERE is_final = 1",
    """
    CREATE TRIGGER IF NOT EXISTS report_versions_content_immutable
    BEFORE UPDATE OF session_id, version_no, source, author_user_id, created_at, report_text, structured_findings
    ON report_versions
    BEGIN
        SELECT RAISE(ABORT, 'report version content is immutable: insert a new version instead');
    END
    """,
    # Index of files kept on disk. version_id is NULL for the original X-ray
    # (it never changes) and set for files that belong to one report version
    # (e.g. an annotated image redrawn after a doctor edits a region).
    """
    CREATE TABLE IF NOT EXISTS visit_files (
        file_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id    TEXT NOT NULL REFERENCES sessions (session_id),
        version_id    INTEGER REFERENCES report_versions (version_id),
        kind          TEXT NOT NULL
            CHECK (kind IN ('xray_original', 'annotated', 'comparison', 'analysis_json')),
        relative_path TEXT NOT NULL,
        mime_type     TEXT NOT NULL,
        size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
        sha256        TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )
    """,
    # Tamper-evident logbook. No foreign key on the actor on purpose: the log
    # must survive even if an account is later removed.
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        audit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        at            TEXT NOT NULL,
        actor_user_id TEXT,
        actor_role    TEXT,
        action        TEXT NOT NULL,
        target_type   TEXT,
        target_id     TEXT,
        before_json   TEXT,
        after_json    TEXT
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only');
    END
    """,
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions (expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_report_versions_session ON report_versions (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_visit_files_session ON visit_files (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log (at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log (actor_user_id)",
]


def _apply_migration_1(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_1_STATEMENTS:
        conn.execute(statement)

    # Existing table, so it needs the check-then-ALTER pattern session_store.py
    # already uses (SQLite has no "ADD COLUMN IF NOT EXISTS").
    patient_cols = {row["name"] for row in conn.execute("PRAGMA table_info(patients)")}
    if not patient_cols:
        raise RuntimeError(
            "The `patients` table does not exist. Import session_store (or start "
            "module4_api.py once) so the base tables are created, then run again."
        )
    if "owner_user_id" not in patient_cols:
        conn.execute("ALTER TABLE patients ADD COLUMN owner_user_id TEXT REFERENCES users (user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_patients_owner ON patients (owner_user_id)")


def _backup(db_path: str) -> str | None:
    """Consistent copy of the database before it is changed (SQLite backup API)."""
    if not os.path.exists(db_path):
        return None
    backup_path = f"{db_path}.bak-before-accounts-v{SCHEMA_VERSION}"
    if os.path.exists(backup_path):
        return backup_path  # keep the FIRST backup; never overwrite it
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


def init_accounts_schema(db_path: str | None = None, backup: bool = True) -> dict:
    """
    Idempotent. Safe to call on every startup (step 3 wires it into the API's
    startup). Returns {"applied": [...], "already": [...], "backup": path|None}.
    """
    path = _resolve_db_path(db_path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # we control the transaction explicitly
    conn.execute("PRAGMA foreign_keys = ON")
    result = {"applied": [], "already": [], "backup": None}
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        if 1 in done:
            result["already"].append(1)
            return result

        if backup:
            conn.close()  # release before the backup API opens the file
            result["backup"] = _backup(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.isolation_level = None
            conn.execute("PRAGMA foreign_keys = ON")

        conn.execute("BEGIN")
        try:
            _apply_migration_1(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, 'accounts_v1', ?)",
                (_now(),),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        result["applied"].append(1)
        return result
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# OFFLINE VERIFICATION -- same pattern as session_store.py. Runs against a
# throwaway temp database, NEVER your real sessions.db.
# ──────────────────────────────────────────────────────────────────────────────
def _offline_verification() -> bool:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    os.environ["SESSION_DB_PATH"] = tmp_path  # must be set BEFORE importing session_store

    passed = failed = 0

    def check(label, condition):
        nonlocal passed, failed
        print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
        if condition:
            passed += 1
        else:
            failed += 1

    def raises(fn, exc=sqlite3.Error) -> bool:
        try:
            fn()
        except exc:
            return True
        return False

    try:
        import session_store  # creates the OLD schema in the temp db

        print("\n[TEST 1] Existing data survives the migration")
        pid, code = session_store.create_patient(name="Old Record")
        sid = session_store.create_session(patient_id=pid)
        res = init_accounts_schema(tmp_path, backup=True)
        check("migration 1 applied", res["applied"] == [1])
        check("a backup of the old database was written", bool(res["backup"]) and os.path.exists(res["backup"]))
        conn = get_conn(tmp_path)
        old = conn.execute("SELECT * FROM patients WHERE patient_code = ?", (code,)).fetchone()
        check("old patient row still there", old is not None and old["name"] == "Old Record")
        check("old patient row has owner_user_id = NULL", old["owner_user_id"] is None)
        check("old session still linked to the old patient",
              conn.execute("SELECT patient_id FROM sessions WHERE session_id = ?", (sid,)).fetchone()["patient_id"] == pid)

        print("\n[TEST 2] Running it again is a safe no-op")
        res2 = init_accounts_schema(tmp_path, backup=True)
        check("second run reports already-applied", res2["already"] == [1] and res2["applied"] == [])
        check("exactly one schema_migrations row",
              conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1)

        print("\n[TEST 3] users: role/status rules and email uniqueness")
        def add_user(uid, role, status, email, display=None):
            conn.execute(
                "INSERT INTO users (user_id, role, display_id, email, password_hash, status, created_at) "
                "VALUES (?, ?, ?, ?, 'hash', ?, ?)",
                (uid, role, display, email, status, _now()),
            )
        add_user("u-pat", "patient", "active", "Pat@Example.com")
        add_user("u-doc", "doctor", "pending", "doc@example.com", "DR-AAAAAA")
        add_user("u-adm", "admin", "active", "adm@example.com", "AD-AAAAAA")
        check("valid patient / doctor / admin rows insert", True)
        check("unknown role is rejected", raises(lambda: add_user("x1", "hacker", "active", "x1@e.com")))
        check("patient cannot be 'pending'", raises(lambda: add_user("x2", "patient", "pending", "x2@e.com")))
        check("doctor cannot be plain 'active'", raises(lambda: add_user("x3", "doctor", "active", "x3@e.com")))
        check("same email in different letter case is rejected",
              raises(lambda: add_user("x4", "patient", "active", "pat@example.COM")))
        add_user("u-pat2", "patient", "active", "pat2@example.com")
        check("two patients may both have display_id NULL", True)
        check("duplicate display_id is rejected",
              raises(lambda: add_user("x5", "doctor", "pending", "x5@e.com", "DR-AAAAAA")))

        print("\n[TEST 4] doctor_profiles: a 'verified' doctor needs real evidence")
        def add_profile(uid, pmdc, vstatus, verified_at=None, verified_by=None, upto=None):
            conn.execute(
                "INSERT INTO doctor_profiles (user_id, pmdc_number, register_full_name, verification_status, "
                "license_valid_upto, submitted_at, verified_at, verified_by) VALUES (?, ?, 'Dr Test', ?, ?, ?, ?, ?)",
                (uid, pmdc, vstatus, upto, _now(), verified_at, verified_by),
            )
        add_profile("u-doc", "12345-P", "pending")
        check("pending profile inserts", True)
        add_user("u-doc2", "doctor", "pending", "doc2@example.com", "DR-BBBBBB")
        check("same PMDC number on a second account is rejected",
              raises(lambda: add_profile("u-doc2", "12345-P", "pending")))
        check("'verified' without verified_at/by/expiry is rejected",
              raises(lambda: add_profile("u-doc2", "99999-P", "verified")))
        add_profile("u-doc2", "99999-P", "verified", _now(), "u-adm", "2030-01-01")
        check("'verified' with full evidence inserts", True)

        print("\n[TEST 5] foreign keys are enforced on get_conn() connections")
        check("auth_session for an unknown user is rejected",
              raises(lambda: conn.execute(
                  "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES ('h', 'nope', ?, ?)",
                  (_now(), _now()))))
        conn.execute("INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES ('h2', 'u-pat', ?, ?)",
                     (_now(), _now()))
        check("auth_session for a real user inserts", True)

        print("\n[TEST 6] records can be owned by an account")
        conn.execute("UPDATE patients SET owner_user_id = 'u-pat' WHERE patient_code = ?", (code,))
        check("owner set", conn.execute("SELECT owner_user_id FROM patients WHERE patient_code = ?", (code,)).fetchone()[0] == "u-pat")
        check("owner must be a real user",
              raises(lambda: conn.execute("UPDATE patients SET owner_user_id = 'ghost' WHERE patient_code = ?", (code,))))

        print("\n[TEST 7] report versions: one final per visit, content immutable")
        def add_version(no, source="ai", author=None, final=0, text="report"):
            conn.execute(
                "INSERT INTO report_versions (session_id, version_no, source, author_user_id, created_at, report_text, is_final) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (sid, no, source, author, _now(), text, final))
        add_version(1, final=1, text="v1 text")
        check("version 1 (final) inserts", True)
        check("a second FINAL version for the same visit is rejected", raises(lambda: add_version(2, "doctor_edit", "u-doc", 1)))
        check("duplicate version number is rejected", raises(lambda: add_version(1)))
        check("doctor_edit without an author is rejected", raises(lambda: add_version(2, "doctor_edit", None, 0)))
        conn.execute("UPDATE report_versions SET is_final = 0 WHERE session_id = ? AND version_no = 1", (sid,))
        add_version(2, "doctor_edit", "u-doc", 1, "v2 edited text")
        check("flipping is_final off then inserting the new final works", True)
        check("editing report_text of an old version is blocked",
              raises(lambda: conn.execute("UPDATE report_versions SET report_text = 'tampered' WHERE version_no = 1")))
        check("old version text is unchanged",
              conn.execute("SELECT report_text FROM report_versions WHERE session_id = ? AND version_no = 1", (sid,)).fetchone()[0] == "v1 text")

        print("\n[TEST 8] visit_files rules")
        conn.execute("INSERT INTO visit_files (session_id, kind, relative_path, mime_type, size_bytes, sha256, created_at) "
                     "VALUES (?, 'xray_original', 'a/b.png', 'image/png', 10, 'abc', ?)", (sid, _now()))
        check("valid file row inserts", True)
        check("unknown file kind is rejected",
              raises(lambda: conn.execute("INSERT INTO visit_files (session_id, kind, relative_path, mime_type, size_bytes, sha256, created_at) "
                                          "VALUES (?, 'virus', 'x', 'x', 1, 'x', ?)", (sid, _now()))))

        print("\n[TEST 9] audit_log is append-only")
        conn.execute("INSERT INTO audit_log (at, actor_user_id, actor_role, action) VALUES (?, 'u-doc', 'doctor', 'test')", (_now(),))
        check("insert works", True)
        check("UPDATE is blocked", raises(lambda: conn.execute("UPDATE audit_log SET action = 'changed'")))
        check("DELETE is blocked", raises(lambda: conn.execute("DELETE FROM audit_log")))
        check("row is still there and unchanged",
              conn.execute("SELECT action FROM audit_log").fetchone()[0] == "test")

        conn.commit()
        conn.close()

        print("\n[TEST 10] a failing migration leaves NO half-built tables (all-or-nothing)")
        tmp2_fd, tmp2 = tempfile.mkstemp(suffix=".db")
        os.close(tmp2_fd)
        try:
            bare = sqlite3.connect(tmp2)
            bare.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY)")  # NO patients table on purpose
            bare.commit()
            bare.close()
            check("migration refuses to run without the base `patients` table",
                  raises(lambda: init_accounts_schema(tmp2, backup=False), RuntimeError))
            chk = sqlite3.connect(tmp2)
            leftovers = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            chk.close()
            check("users table was rolled back (not left behind)", "users" not in leftovers)
            check("schema_migrations has no version recorded",
                  not any(True for _ in sqlite3.connect(tmp2).execute("SELECT 1 FROM schema_migrations")))
        finally:
            for p in (tmp2,):
                try:
                    os.remove(p)
                except OSError:
                    pass
    finally:
        for p in (tmp_path, f"{tmp_path}.bak-before-accounts-v{SCHEMA_VERSION}"):
            try:
                os.remove(p)
            except OSError:
                pass

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} offline verification tests passed.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    if "--apply" in sys.argv:
        outcome = init_accounts_schema()
        import session_store

        print(f"Database: {os.path.abspath(session_store.SESSION_DB_PATH)}")
        if outcome["backup"]:
            print(f"Backup:   {os.path.abspath(outcome['backup'])}")
        print("Applied migration 1." if outcome["applied"] else "Migration 1 was already applied. Nothing changed.")
    else:
        sys.exit(0 if _offline_verification() else 1)
