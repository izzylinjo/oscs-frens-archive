import sqlite3
import os
from datetime import datetime, timezone
from config import DB_PATH, MAX_QUEUE_SIZE

# ============================================================
# Connection
# ============================================================

def get_conn():
    """Get a database connection. Creates db directory if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


def now_utc():
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# Init
# ============================================================

def init_db():
    """Create tables and indexes if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS clips (
            clip_id             TEXT PRIMARY KEY,
            title               TEXT,
            custom_title        TEXT,
            streamer            TEXT,
            clip_url            TEXT,
            mp4_url             TEXT,
            duration            REAL,
            view_count          INTEGER,
            created_at          TEXT,
            fetched_at          TEXT,
            approved_at         TEXT,
            queued_at           TEXT,
            uploaded_at         TEXT,
            status              TEXT DEFAULT 'fetched',
            priority            INTEGER DEFAULT 0,
            youtube_views       INTEGER DEFAULT 0,
            discord_message_id  TEXT,
            discord_channel_id  TEXT
        );

        CREATE TABLE IF NOT EXISTS streamers (
            username        TEXT PRIMARY KEY,
            last_checked_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_clips_status
            ON clips(status);

        CREATE INDEX IF NOT EXISTS idx_clips_created_at
            ON clips(created_at);

        CREATE INDEX IF NOT EXISTS idx_clips_streamer
            ON clips(streamer);
    """)

    # Migrate existing databases that predate these columns
    for col, col_type in [
        ("custom_title", "TEXT"),
        ("queued_at", "TEXT"),
        ("title_options", "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE clips ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()
    print("[db] Database initialized")


# ============================================================
# Clip operations
# ============================================================

def clip_exists(clip_id):
    """Return True if this Twitch clip ID is already in the DB."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM clips WHERE clip_id = ?", (clip_id,)
    ).fetchone()
    conn.close()
    return row is not None


def insert_clip(clip):
    """Insert a new clip with status 'fetched'.
    clip must be a dict with keys matching the clips table.
    Silently skips if clip_id already exists (deduplication).
    """
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO clips (
                clip_id, title, streamer, clip_url, mp4_url,
                duration, view_count, created_at, fetched_at, status
            ) VALUES (
                :clip_id, :title, :streamer, :clip_url, :mp4_url,
                :duration, :view_count, :created_at, :fetched_at, 'fetched'
            )
        """, {
            "clip_id":    clip["clip_id"],
            "title":      clip["title"],
            "streamer":   clip["streamer"],
            "clip_url":   clip["clip_url"],
            "mp4_url":    clip.get("mp4_url"),
            "duration":   clip.get("duration", 0),
            "view_count": clip.get("view_count", 0),
            "created_at": clip.get("created_at"),
            "fetched_at": now_utc(),
        })
        conn.commit()
        print(f"[db] Inserted clip: {clip['clip_id']} ({clip['streamer']})")
    except sqlite3.IntegrityError:
        print(f"[db] Skipping duplicate clip: {clip['clip_id']}")
    finally:
        conn.close()


def update_status(clip_id, status):
    """Update clip status. Automatically sets timestamps.
    Valid statuses: fetched, approved, rejected, queued, uploaded
    Only queue.py should set status to 'queued'.
    """
    valid = {"fetched", "approved", "rejected", "awaiting_title", "queued", "uploaded"}
    if status not in valid:
        raise ValueError(f"[db] Invalid status '{status}'. Must be one of: {valid}")

    timestamp_field = None
    if status == "approved":
        timestamp_field = "approved_at"
    elif status == "queued":
        timestamp_field = "queued_at"
    elif status == "uploaded":
        timestamp_field = "uploaded_at"

    conn = get_conn()
    if timestamp_field:
        conn.execute(
            f"UPDATE clips SET status = ?, {timestamp_field} = ? WHERE clip_id = ?",
            (status, now_utc(), clip_id)
        )
    else:
        conn.execute(
            "UPDATE clips SET status = ? WHERE clip_id = ?",
            (status, clip_id)
        )
    conn.commit()
    conn.close()
    print(f"[db] Clip {clip_id} → {status}")


def update_discord_message(clip_id, message_id, channel_id):
    """Store the Discord message ID and channel ID for a clip."""
    conn = get_conn()
    conn.execute(
        "UPDATE clips SET discord_message_id = ?, discord_channel_id = ? WHERE clip_id = ?",
        (str(message_id), str(channel_id), clip_id)
    )
    conn.commit()
    conn.close()


def get_clip_by_message_id(discord_message_id):
    """Look up a clip by its Discord message ID. Used to map reactions to DB rows."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM clips WHERE discord_message_id = ?",
        (str(discord_message_id),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_approved_clips(limit=None, order_by="priority DESC, approved_at ASC"):
    """Get approved clips not yet queued, ordered by priority then approval time."""
    conn = get_conn()
    query = f"SELECT * FROM clips WHERE status = 'approved' ORDER BY {order_by}"
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_next_approved_clips(limit):
    """Get next approved clips to move into the queue, respecting MAX_QUEUE_SIZE."""
    current_queue = get_queue_size()
    slots = MAX_QUEUE_SIZE - current_queue
    if slots <= 0:
        print(f"[db] Queue full ({current_queue}/{MAX_QUEUE_SIZE}) — no slots available")
        return []
    actual_limit = min(limit, slots)
    return get_approved_clips(limit=actual_limit)


def get_queue_size():
    """Return number of clips currently in 'queued' status."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM clips WHERE status = 'queued'"
    ).fetchone()
    conn.close()
    return row[0]


def update_title(clip_id, title):
    """Update the working title for a clip (used after Gemini generation)."""
    conn = get_conn()
    conn.execute("UPDATE clips SET title = ? WHERE clip_id = ?", (title, clip_id))
    conn.commit()
    conn.close()


def update_title_options(clip_id, titles):
    """Store the 3 Gemini-generated title options as a JSON array."""
    import json
    conn = get_conn()
    conn.execute("UPDATE clips SET title_options = ? WHERE clip_id = ?", (json.dumps(titles), clip_id))
    conn.commit()
    conn.close()


def get_next_to_post():
    """Return the oldest queued clip ready to upload, or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM clips WHERE status = 'queued' ORDER BY queued_at ASC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ============================================================
# Streamer tracking
# ============================================================

def get_last_checked(username):
    """Get the last_checked_at timestamp for a streamer.
    Returns None if streamer has never been checked.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT last_checked_at FROM streamers WHERE username = ?",
        (username.lower(),)
    ).fetchone()
    conn.close()
    return row["last_checked_at"] if row else None


def update_last_checked(username, last_clip_created_at):
    """Update last_checked_at for a streamer.
    Uses max(clip.created_at) not now() to prevent gaps on API failure.
    """
    conn = get_conn()
    conn.execute("""
        INSERT INTO streamers (username, last_checked_at)
        VALUES (?, ?)
        ON CONFLICT(username) DO UPDATE SET last_checked_at = excluded.last_checked_at
    """, (username.lower(), last_clip_created_at))
    conn.commit()
    conn.close()
    print(f"[db] Updated last_checked_at for {username}: {last_clip_created_at}")


# ============================================================
# Self-check — run directly to verify DB sets up correctly
# ============================================================

if __name__ == "__main__":
    init_db()
    print(f"[db] DB path: {DB_PATH}")
    print(f"[db] Queue size: {get_queue_size()}/{MAX_QUEUE_SIZE}")
    print("[db] All checks passed")
