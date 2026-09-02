"""
session_store.py

Lightweight SQLite-based storage for two things:
  1. Session metadata (which patient session exists, when it was created)
  2. Conversation turns (question + answer + classification label), so
     follow-up questions have real conversational memory.

Deliberately NOT Postgres -- see the note in the chat: nothing in the current
MedLumina setup runs a Postgres server, and adding one just for session
history is unnecessary weight for an FYP demo. SQLite is a single file, no
server, works out of the box. If this ever needs to scale beyond a demo,
swapping the sqlite3 calls below for a Postgres connection (e.g. via
psycopg2) is a contained change -- this module is the only place that
touches the database directly, nothing else in Module 4 talks to SQL.
"""

import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SESSION_DB_PATH = os.getenv("SESSION_DB_PATH", "./sessions.db")


def _get_conn():
    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


VALID_EXPLANATION_LEVELS = ("simple", "detailed")


def _generate_patient_code() -> str:
    """
    Short, human-writable code the patient/doctor can actually copy down
    and type back in -- NOT the internal patient_id (a full UUID, way too
    long to expect anyone to write on paper). secrets.token_hex is
    cryptographically random, so codes aren't guessable/enumerable --
    matters here since this is the only thing standing between a stranger
    and someone else's medical conversation history.
    Format: "PT-XXXXXX" (6 hex chars = 16.7M possibilities, collision
    check below handles the astronomically unlikely clash anyway).
    """
    return f"PT-{secrets.token_hex(3).upper()}"


def init_db() -> None:
    conn = _get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    )

    # ── Patient identity: returning patients across sessions ───────────────
    # A patient is identified by phone number (no password -- see chat notes
    # on why this is an intentional FYP-scope decision, not an oversight).
    # One patient can have many sessions (one per visit/report); sessions.
    # patient_id links a session back to the patient who owns it. Sessions
    # created before this change simply have patient_id = NULL -- they still
    # work exactly as before, just aren't linked to any patient record.
    # ── ID system redesign: phone_number -> patient_code ────────────────────
    # Supervisor feedback: identify patients/doctors by a proper
    # system-generated ID, not personal phone numbers (privacy, and not
    # every user -- especially doctors just testing something -- wants to
    # give a phone number). Renamed in place (keeps the existing UNIQUE
    # constraint and any already-recorded patients intact) rather than
    # dropping and recreating the column, which risks data loss.
    existing_patient_cols = {row["name"] for row in conn.execute("PRAGMA table_info(patients)")}
    if "phone_number" in existing_patient_cols and "patient_code" not in existing_patient_cols:
        conn.execute("ALTER TABLE patients RENAME COLUMN phone_number TO patient_code")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            patient_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            question TEXT NOT NULL,
            classification TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        )
        """
    )

    # ── FE-4 migration: explanation_level column ────────────────────────────
    # Your existing sessions.db (37 rows as of this session) predates this
    # column -- SQLite has no "ADD COLUMN IF NOT EXISTS", so we check
    # PRAGMA table_info() ourselves and only ALTER TABLE if it's actually
    # missing. Existing rows get the DEFAULT 'simple' value automatically;
    # nothing about old sessions breaks.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "explanation_level" not in existing_cols:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN explanation_level TEXT NOT NULL DEFAULT 'simple'"
        )

    # ── Patient-persistence migration: sessions.patient_id ──────────────────
    # Same safe pattern as above: only ALTER TABLE if the column is actually
    # missing, so this runs cleanly on your existing sessions.db without
    # losing or corrupting any of your already-recorded sessions.
    if "patient_id" not in existing_cols:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN patient_id TEXT DEFAULT NULL"
        )

    # ── Confidence tracking migration: turns.confidence ─────────────────────
    # Same safe pattern as the other migrations above -- only added if
    # missing, existing turns just get NULL (meaning "asked before this
    # feature existed", not "zero confidence" -- same distinction the
    # retrieval layer uses).
    existing_turn_cols = {row["name"] for row in conn.execute("PRAGMA table_info(turns)")}
    if "confidence" not in existing_turn_cols:
        conn.execute("ALTER TABLE turns ADD COLUMN confidence REAL DEFAULT NULL")

    conn.commit()
    conn.close()


def create_patient(name: str = "") -> tuple[str, str]:
    """
    Always creates a NEW patient record with a fresh, system-generated
    code -- replaces the old phone-number-based get_or_create_patient().
    Returns (patient_id, patient_code): patient_id is the internal UUID
    (used for the sessions.patient_id foreign key, never shown to anyone);
    patient_code is the short human-facing code to actually display and
    have the patient/doctor write down.
    """
    patient_id = str(uuid.uuid4())
    patient_code = _generate_patient_code()

    conn = _get_conn()
    # Collision is astronomically unlikely (1-in-16.7M per attempt) but
    # checked anyway rather than assumed away -- costs nothing, and
    # "assumed unique" is exactly the kind of assumption that's fine until
    # it silently isn't.
    while conn.execute(
        "SELECT 1 FROM patients WHERE patient_code = ?", (patient_code,)
    ).fetchone():
        patient_code = _generate_patient_code()

    conn.execute(
        "INSERT INTO patients (patient_id, patient_code, name, created_at) VALUES (?, ?, ?, ?)",
        (patient_id, patient_code, name or "", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return patient_id, patient_code


def get_patient_by_code(patient_code: str) -> str | None:
    """
    Looks up a patient by their code. Returns patient_id if found, None if
    not -- deliberately does NOT auto-create on a miss (unlike the old
    phone-based version): a mistyped or unknown code should tell the user
    it wasn't found, not silently create a new blank patient record under
    that typo. Case-insensitive and whitespace-tolerant, since a patient
    reading a handwritten code back may not preserve exact casing.
    """
    normalized = patient_code.strip().upper()
    if not normalized:
        return None

    conn = _get_conn()
    row = conn.execute(
        "SELECT patient_id FROM patients WHERE patient_code = ?", (normalized,)
    ).fetchone()
    conn.close()
    return row["patient_id"] if row else None


def get_patient_sessions(patient_id: str) -> list[dict]:
    """
    Returns every session this patient has ever had, most recent first --
    used to show a returning patient "your past visits" instead of making
    them re-upload their report and X-ray findings from scratch.
    """
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT session_id, created_at, explanation_level FROM sessions
        WHERE patient_id = ?
        ORDER BY created_at DESC
        """,
        (patient_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_patient_id_for_session(session_id: str) -> str | None:
    """
    Reverse lookup: given a session_id, returns the patient_id it belongs
    to, or None if the session doesn't exist or is an anonymous session
    (patient_id was never set -- see create_session()'s docstring).

    Needed for the trend-comparison feature: the Q&A pipeline only ever
    receives session_id from the frontend (see AskRequest in
    module4_api.py), never patient_id directly. This is the one lookup
    that lets module4_pipeline.py find "which other sessions belong to
    this same person" starting from just the current session_id it
    already has.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT patient_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["patient_id"]


def create_session(explanation_level: str = "simple", patient_id: str | None = None) -> str:
    """
    Creates a new patient session and returns its session_id.

    explanation_level: "simple" (default) or "detailed" -- FE-4's
    knowledge-level-adaptation field. The patient sets this once at session
    start; generator.py reads it back per-question to pick which complexity
    instruction goes into the prompt. Invalid values fall back to "simple"
    rather than raising, so a malformed request can't break session
    creation -- the same "fail safe, not silent-wrong" pattern used
    elsewhere in this project (see live_kb.py's retry wrapper, Module 6's
    safety net).

    patient_id: optional -- links this session to a returning patient (see
    create_patient() / get_patient_by_code()). Left as None for an
    anonymous/one-off session, exactly like every session before this
    change behaved.
    """
    if explanation_level not in VALID_EXPLANATION_LEVELS:
        explanation_level = "simple"

    session_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (session_id, created_at, explanation_level, patient_id) VALUES (?, ?, ?, ?)",
        (session_id, datetime.now(timezone.utc).isoformat(), explanation_level, patient_id),
    )
    conn.commit()
    conn.close()
    return session_id


def session_exists(session_id: str) -> bool:
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row is not None


def get_explanation_level(session_id: str) -> str:
    """
    Returns this session's explanation_level ("simple"/"detailed").
    Defensive default: if the session somehow doesn't exist or the stored
    value is corrupted/unrecognized, returns "simple" rather than raising --
    generator.py calls this on every question, and a malformed value here
    should never be able to crash an answer request.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT explanation_level FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    if row is None or row["explanation_level"] not in VALID_EXPLANATION_LEVELS:
        return "simple"
    return row["explanation_level"]


def set_explanation_level(session_id: str, explanation_level: str) -> bool:
    """
    Updates an existing session's explanation_level -- lets a patient switch
    from "simple" to "detailed" (or back) mid-conversation without starting
    a new session. Returns False (no-op) on an invalid level or unknown
    session_id instead of raising, same defensive pattern as above.
    """
    if explanation_level not in VALID_EXPLANATION_LEVELS:
        return False
    if not session_exists(session_id):
        return False
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET explanation_level = ? WHERE session_id = ?",
        (explanation_level, session_id),
    )
    conn.commit()
    conn.close()
    return True


def log_turn(
    session_id: str, question: str, classification: str, answer: str, confidence: float | None = None
) -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO turns (session_id, question, classification, answer, created_at, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, question, classification, answer, datetime.now(timezone.utc).isoformat(), confidence),
    )
    conn.commit()
    conn.close()


def get_recent_turns(session_id: str, limit: int = 5) -> list[dict]:
    """
    Returns the most recent conversation turns for a session, oldest first,
    so they can be dropped straight into a prompt as conversation history
    (or restored into a frontend chat -- see /session/history).
    """
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT question, classification, answer, confidence FROM turns
        WHERE session_id = ?
        ORDER BY turn_id DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


init_db()


# ──────────────────────────────────────────────────────────────────────────────
# OFFLINE VERIFICATION — no network, no MedGemma/Gemini needed. Mirrors the
# pattern already used in Module 6 (interaction_checker.py's
# _offline_verification(), llm_safety.py's __main__ block): a permanent,
# runnable regression test for the FE-4 explanation_level pieces added this
# session, so a future edit can't silently break create_session()/
# get_explanation_level()/set_explanation_level() the way the original
# safety-net bug broke silently.
#
# Runs against a disposable temp database, NOT your real sessions.db --
# running this file directly never touches or adds rows to your actual
# session history.
# ──────────────────────────────────────────────────────────────────────────────
def _offline_verification() -> bool:
    import tempfile
    global SESSION_DB_PATH
    original_db_path = SESSION_DB_PATH
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    SESSION_DB_PATH = tmp_path

    passed = 0
    failed = 0

    def check(label, condition):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}")
        if condition:
            passed += 1
        else:
            failed += 1

    try:
        init_db()

        print("\n[TEST 1] Migration is idempotent -- calling init_db() twice doesn't error")
        init_db()
        check("second init_db() call succeeds without error", True)

        print("\n[TEST 2] create_session() defaults to 'simple'")
        sid = create_session()
        check("default level is 'simple'", get_explanation_level(sid) == "simple")

        print("\n[TEST 3] create_session(explanation_level='detailed') is honored")
        sid_d = create_session(explanation_level="detailed")
        check("stored level is 'detailed'", get_explanation_level(sid_d) == "detailed")

        print("\n[TEST 4] create_session() with an invalid level falls back to 'simple', not an error")
        sid_bad = create_session(explanation_level="extremely thorough please")
        check("invalid level falls back to 'simple'", get_explanation_level(sid_bad) == "simple")

        print("\n[TEST 5] set_explanation_level() updates an existing session")
        ok = set_explanation_level(sid, "detailed")
        check("set_explanation_level returns True on success", ok is True)
        check("level actually changed", get_explanation_level(sid) == "detailed")

        print("\n[TEST 6] set_explanation_level() with an invalid value is a safe no-op")
        prior = get_explanation_level(sid)
        ok_bad = set_explanation_level(sid, "super-duper-mode")
        check("returns False for an invalid level", ok_bad is False)
        check("value is unchanged, not corrupted", get_explanation_level(sid) == prior)

        print("\n[TEST 7] set_explanation_level() on an unknown session_id is a safe no-op")
        ok_unknown = set_explanation_level("not-a-real-session-id", "detailed")
        check("returns False for an unknown session_id", ok_unknown is False)

        print("\n[TEST 8] get_explanation_level() on an unknown session_id defaults to 'simple', doesn't crash")
        check("unknown session_id returns 'simple'", get_explanation_level("also-not-real") == "simple")

        print("\n[TEST 9] create_patient() creates a new patient with a real, non-empty code")
        pid1, code1 = create_patient(name="Test Patient")
        check("returns a non-empty patient_id", bool(pid1))
        check("returns a non-empty patient_code", bool(code1))
        check("patient_code has the expected PT- prefix", code1.startswith("PT-"))

        print("\n[TEST 10] get_patient_by_code() finds the patient by their real code, case/whitespace-insensitively")
        looked_up = get_patient_by_code(f"  {code1.lower()}  ")
        check("lookup by code (different case, extra whitespace) finds the same patient", looked_up == pid1)

        print("\n[TEST 11] Two sessions created for the same patient both show up in get_patient_sessions()")
        s1 = create_session(patient_id=pid1)
        s2 = create_session(patient_id=pid1, explanation_level="detailed")
        history = get_patient_sessions(pid1)
        history_ids = {row["session_id"] for row in history}
        check("both sessions are linked to this patient", {s1, s2}.issubset(history_ids))

        print("\n[TEST 12] Each create_patient() call makes a genuinely different patient, with no shared history")
        pid3, code3 = create_patient()
        check("different call gets a different patient_id", pid3 != pid1)
        check("different call gets a different patient_code", code3 != code1)
        check("new patient has no sessions yet", get_patient_sessions(pid3) == [])

        print("\n[TEST 12b] get_patient_by_code() on an unknown code returns None, does NOT silently create a patient")
        check("unknown code returns None", get_patient_by_code("PT-000000") is None)

        print("\n[TEST 13] An anonymous session (no patient_id) still works exactly as before")
        anon_sid = create_session()
        check("anonymous session creation still works", session_exists(anon_sid))

        print("\n[TEST 13b] get_patient_id_for_session() finds the right patient for a linked session")
        pid_link, _ = create_patient(name="Link Test Patient")
        linked_sid = create_session(patient_id=pid_link)
        check("reverse lookup returns the correct patient_id",
              get_patient_id_for_session(linked_sid) == pid_link)

        print("\n[TEST 13c] get_patient_id_for_session() returns None for an anonymous session")
        check("anonymous session has no patient_id",
              get_patient_id_for_session(anon_sid) is None)

        print("\n[TEST 13d] get_patient_id_for_session() returns None for an unknown session_id, doesn't crash")
        check("unknown session_id returns None",
              get_patient_id_for_session("not-a-real-session-id") is None)

        print("\n[TEST 14] log_turn() with a real confidence value stores and returns it correctly")
        conf_sid = create_session()
        log_turn(conf_sid, "Why do I have this?", "SESSION_GROUNDED", "Because X.", confidence=82.5)
        turns = get_recent_turns(conf_sid)
        check("one turn recorded", len(turns) == 1)
        check("confidence value round-trips correctly", turns[0]["confidence"] == 82.5)

        print("\n[TEST 15] log_turn() with confidence=None (decline path) stores NULL, not 0.0")
        decline_sid = create_session()
        log_turn(decline_sid, "What is X?", "GENERIC_KNOWLEDGE", "I can't answer that.")
        decline_turns = get_recent_turns(decline_sid)
        check("decline turn's confidence is None, not 0.0 or missing",
              decline_turns[0]["confidence"] is None)

    finally:
        SESSION_DB_PATH = original_db_path
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} offline verification tests passed.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    _offline_verification()
