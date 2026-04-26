import os
import requests
from config import DOWNLOADS_DIR, MAX_QUEUE_SIZE
from bot.db import (
    get_next_approved_clips,
    update_status,
    update_title,
    get_next_to_post,
    get_conn,
    now_utc,
)
from bot.titles import generate_title
from bot.overlay import add_overlay


def _overlay_path(clip_id):
    """Canonical path for a clip's processed overlay file."""
    return os.path.join(DOWNLOADS_DIR, f"{clip_id}_overlay.mp4")


def _download_clip(clip):
    """Download clip mp4 to downloads/. Returns local file path."""
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    raw_path = os.path.join(DOWNLOADS_DIR, f"{clip['clip_id']}.mp4")

    if os.path.exists(raw_path):
        print(f"[queue] Already downloaded: {clip['clip_id']}")
        return raw_path

    mp4_url = clip.get("mp4_url")
    if not mp4_url:
        raise ValueError(f"No mp4_url for clip {clip['clip_id']}")

    print(f"[queue] Downloading {clip['clip_id']}...")
    resp = requests.get(mp4_url, stream=True, timeout=60)
    resp.raise_for_status()

    with open(raw_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"[queue] Downloaded: {os.path.basename(raw_path)}")
    return raw_path


def fill_queue():
    """Process approved clips into the queue up to MAX_QUEUE_SIZE.

    Pipeline per clip: download → generate title → add overlay → mark queued.
    File paths flow through as return values — nothing stored in DB.
    """
    clips = get_next_approved_clips(MAX_QUEUE_SIZE)
    if not clips:
        print("[queue] No approved clips to fill queue")
        return

    print(f"[queue] Processing {len(clips)} clips into queue...")

    for clip in clips:
        try:
            raw_path = _download_clip(clip)

            title = generate_title(clip, raw_path)
            update_title(clip["clip_id"], title)

            overlay_path = add_overlay(raw_path, clip["streamer"])
            os.remove(raw_path)

            update_status(clip["clip_id"], "queued")  # sets queued_at automatically

        except Exception as e:
            print(f"[queue] ERROR processing {clip['clip_id']}: {e}")
            # Leave raw file if it exists — safe to retry next cycle


def post_next_queued():
    """Upload the oldest queued clip to YouTube, mark uploaded, clean up file."""
    from bot.youtube import upload_clip

    clip = get_next_to_post()
    if not clip:
        print("[queue] No queued clips to post")
        return

    overlay_path = _overlay_path(clip["clip_id"])

    if not os.path.exists(overlay_path):
        # File was lost (e.g. system restart after queue fill but before upload)
        print(f"[queue] Missing file for {clip['clip_id']} — reverting to approved for reprocessing")
        conn = get_conn()
        conn.execute(
            "UPDATE clips SET status = 'approved', queued_at = NULL WHERE clip_id = ?",
            (clip["clip_id"],)
        )
        conn.commit()
        conn.close()
        return

    try:
        video_id = upload_clip(clip, overlay_path)
        update_status(clip["clip_id"], "uploaded")
        os.remove(overlay_path)
        print(f"[queue] Uploaded and cleaned up: {clip['clip_id']} → {video_id}")
    except Exception as e:
        print(f"[queue] ERROR uploading {clip['clip_id']}: {e}")
