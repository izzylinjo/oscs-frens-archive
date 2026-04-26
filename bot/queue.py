import os
import subprocess
from config import DOWNLOADS_DIR, MAX_QUEUE_SIZE
from bot.db import (
    get_next_approved_clips,
    update_status,
    update_title,
    update_title_options,
    get_next_to_post,
    get_conn,
    now_utc,
)
from bot.titles import generate_titles
from bot.overlay import add_overlay


def _overlay_path(clip_id):
    """Canonical path for a clip's processed overlay file."""
    return os.path.join(DOWNLOADS_DIR, f"{clip_id}_overlay.mp4")


def _download_clip(clip):
    """Download clip mp4 to downloads/ using yt-dlp. Returns local file path."""
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    raw_path = os.path.join(DOWNLOADS_DIR, f"{clip['clip_id']}.mp4")

    if os.path.exists(raw_path):
        print(f"[queue] Already downloaded: {clip['clip_id']}")
        return raw_path

    print(f"[queue] Downloading {clip['clip_id']}...")
    result = subprocess.run(
        ["yt-dlp", "--output", raw_path, "--merge-output-format", "mp4", "--force-overwrites", clip["clip_url"]],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"[queue] yt-dlp failed:\n{result.stderr[-500:]}")

    print(f"[queue] Downloaded: {os.path.basename(raw_path)}")
    return raw_path


def fill_queue(discord_bot=None):
    """Process approved clips: download → Whisper → overlay → generate titles → post for final approval.

    Clips land in 'awaiting_title' status until the user picks a title in Discord.
    discord_bot is the discord.Client instance — needed to post to #clip-final-approval.
    """
    clips = get_next_approved_clips(MAX_QUEUE_SIZE)
    if not clips:
        print("[queue] No approved clips to process")
        return

    print(f"[queue] Processing {len(clips)} clips...")

    for clip in clips:
        try:
            raw_path = _download_clip(clip)

            titles = generate_titles(clip, raw_path)
            update_title_options(clip["clip_id"], titles)
            update_title(clip["clip_id"], titles[0])  # set title[0] as working default

            overlay_path = add_overlay(raw_path, clip["streamer"])
            os.remove(raw_path)

            update_status(clip["clip_id"], "awaiting_title")

            if discord_bot:
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    _post_for_final_approval(discord_bot, clip, titles),
                    discord_bot.loop,
                )

        except Exception as e:
            print(f"[queue] ERROR processing {clip['clip_id']}: {e}")


async def _post_for_final_approval(bot, clip, titles):
    """Post a clip to #clip-final-approval with title options."""
    from config import DISCORD_CLIP_FINAL_APPROVAL_CHANNEL_ID
    from bot.discord_bot import post_for_final_approval

    channel = bot.get_channel(DISCORD_CLIP_FINAL_APPROVAL_CHANNEL_ID)
    if not channel:
        print("[queue] ERROR: #clip-final-approval channel not found")
        return

    await post_for_final_approval(channel, clip, titles)


def post_next_queued():
    """Upload the oldest queued clip to YouTube, mark uploaded, clean up file."""
    from bot.youtube import upload_clip

    clip = get_next_to_post()
    if not clip:
        print("[queue] No queued clips to post")
        return

    overlay_path = _overlay_path(clip["clip_id"])

    if not os.path.exists(overlay_path):
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
