import time
import requests
from bot.db import clip_exists, get_last_checked, update_last_checked, insert_clip
from datetime import datetime, timezone
from config import (
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    STREAMERS,
    CLIPS_PER_STREAMER,
)
from bot.db import clip_exists, get_last_checked, update_last_checked

# ============================================================
# Token cache — refreshed only when expired
# ============================================================

_token_cache = {
    "access_token": None,
    "expires_at": 0,
}


def get_access_token():
    """Return a valid access token, refreshing only if expired."""
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }
    resp = _request_with_retry("POST", url, params=params, use_auth=False)
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data["expires_in"]
    print("[twitch] Token refreshed")
    return _token_cache["access_token"]


def get_headers():
    return {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {get_access_token()}",
    }


# ============================================================
# Retry wrapper
# ============================================================

def _request_with_retry(method, url, use_auth=True, **kwargs):
    """Make an HTTP request with 3 attempts and exponential backoff."""
    headers = get_headers() if use_auth else {}
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))

    last_error = None
    for attempt in range(3):
        try:
            resp = requests.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_error = e
            wait = 2 ** attempt
            print(f"[twitch] Request failed (attempt {attempt + 1}/3): {e} — retrying in {wait}s")
            time.sleep(wait)

    raise RuntimeError(f"[twitch] All 3 attempts failed: {last_error}")


# ============================================================
# Streamer lookup
# ============================================================

def get_user_ids(usernames):
    """Convert list of usernames to {username: user_id} dict.
    Logs a warning for any username not found — does not crash.
    """
    url = "https://api.twitch.tv/helix/users"
    params = [("login", name.lower()) for name in usernames]
    resp = _request_with_retry("GET", url, params=params)

    found = {}
    for user in resp.json().get("data", []):
        found[user["login"]] = user["id"]

    for name in usernames:
        if name.lower() not in found:
            print(f"[twitch] WARNING: '{name}' not found on Twitch — skipping")

    return found


# ============================================================
# MP4 URL helper
# ============================================================

def _mp4_url(thumbnail_url):
    """Derive direct MP4 URL from Twitch clip thumbnail URL."""
    if not thumbnail_url:
        return None
    return thumbnail_url.replace("-preview-480x272.jpg", ".mp4")


# ============================================================
# Clip fetching for a single streamer
# ============================================================

def fetch_clips_for_streamer(username, user_id):
    """Fetch new clips for one streamer since last_checked_at.

    Returns (new_clips, skipped_count):
        new_clips     — list of clip dicts matching DB schema
        skipped_count — number of duplicates skipped
    """
    last_checked = get_last_checked(username)

    url = "https://api.twitch.tv/helix/clips"
    params = {
        "broadcaster_id": user_id,
        "first": 20,  # fetch more than we need so we can filter + sort properly
    }
    if last_checked:
        params["started_at"] = last_checked

    resp = _request_with_retry("GET", url, params=params)
    raw_clips = resp.json().get("data", [])

    if not raw_clips:
        print(f"[{username}] no new clips")
        return [], 0

    # Filter: only clips created after last_checked_at
    if last_checked:
        raw_clips = [
            c for c in raw_clips
            if c["created_at"] > last_checked
        ]

    # Sort by view count descending AFTER filtering
    raw_clips.sort(key=lambda c: c["view_count"], reverse=True)

    # Take buffer beyond CLIPS_PER_STREAMER to account for dedup losses
    raw_clips = raw_clips[:CLIPS_PER_STREAMER * 2]

    new_clips = []
    skipped = 0
    for clip in raw_clips:
        if clip_exists(clip["id"]):
            skipped += 1
            continue
        clip_dict = {
            "clip_id":    clip["id"],
            "title":      clip["title"],
            "streamer":   username,
            "clip_url":   clip["url"],
            "mp4_url":    _mp4_url(clip.get("thumbnail_url", "")),
            "duration":   clip.get("duration", 0),
            "view_count": clip["view_count"],
            "created_at": clip["created_at"],
        }
        insert_clip(clip_dict)
        new_clips.append(clip_dict)
        if len(new_clips) >= CLIPS_PER_STREAMER:
            break

    # Only update last_checked_at if we found new clips
    # Use max(created_at) from deduped results, not raw API response
    if new_clips:
        max_created_at = max(c["created_at"] for c in new_clips)
        update_last_checked(username, max_created_at)

    print(f"[{username}] {len(new_clips)} new clips ({skipped} skipped duplicates)")
    return new_clips, skipped


# ============================================================
# Main fetch — call this from other modules
# ============================================================

def fetch_all_new_clips():
    """Fetch new clips for all streamers in config.
    Returns a flat list of clip dicts sorted by view count descending.
    """
    print("[twitch] Starting clip fetch for all streamers...")
    user_map = get_user_ids(STREAMERS)

    all_new_clips = []
    for username, user_id in user_map.items():
        try:
            clips, _ = fetch_clips_for_streamer(username, user_id)
            all_new_clips.extend(clips)
        except Exception as e:
            print(f"[{username}] ERROR during fetch: {e}")

    # Final sort by view count across all streamers
    all_new_clips.sort(key=lambda c: c["view_count"], reverse=True)
    print(f"[twitch] Done. {len(all_new_clips)} total new clips fetched.")
    return all_new_clips


# ============================================================
# Self-check — run directly to verify it works
# ============================================================

if __name__ == "__main__":
    from bot.db import init_db
    init_db()
    clips = fetch_all_new_clips()
    if not clips:
        print("\nNo new clips found — streamers may not have posted recently.")
    else:
        print(f"\n--- {len(clips)} new clips ---")
        for clip in clips:
            print(f"  [{clip['view_count']} views] {clip['streamer']}: {clip['title']}")
            print(f"    {clip['clip_url']}")
