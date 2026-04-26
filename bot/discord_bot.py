import discord
import re
import requests
from config import (
    DISCORD_BOT_TOKEN,
    DISCORD_USER_ID,
    DISCORD_CLIP_REVIEW_CHANNEL_ID,
    DISCORD_CLIP_INBOX_CHANNEL_ID,
    TWITCH_CLIENT_ID,
)
from bot.db import (
    init_db,
    insert_clip,
    update_status,
    update_discord_message,
    get_clip_by_message_id,
    get_approved_clips,
)
from bot.twitch import get_access_token, _mp4_url

# ============================================================
# Bot setup
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guild_messages = True

bot = discord.Client(intents=intents)

APPROVE_EMOJI = "✅"
REJECT_EMOJI  = "❌"

TWITCH_CLIP_PATTERN = re.compile(
    r"https?://(?:www\.)?twitch\.tv/\w+/clip/[\w-]+"
)

# ============================================================
# Helpers
# ============================================================

def build_embed(clip):
    """Build a Discord embed for a clip review message."""
    embed = discord.Embed(
        title=clip["title"],
        url=clip["clip_url"],
        color=0x9146FF,  # Twitch purple
    )
    embed.add_field(name="Streamer", value=clip["streamer"], inline=True)
    embed.add_field(name="Views",    value=f"{clip['view_count']:,}", inline=True)
    embed.add_field(name="Duration", value=f"{clip['duration']}s", inline=True)
    embed.set_footer(text=f"clip_id: {clip['clip_id']} | React ✅ approve  ❌ reject  or reply to set custom title")
    return embed


async def post_clip_for_review(channel, clip):
    """Post a single clip embed to #clip-review and store message ID in DB."""
    embed = build_embed(clip)
    msg = await channel.send(embed=embed)
    await msg.add_reaction(APPROVE_EMOJI)
    await msg.add_reaction(REJECT_EMOJI)
    update_discord_message(clip["clip_id"], msg.id, channel.id)
    print(f"[discord] Posted for review: {clip['clip_id']} ({clip['streamer']})")


async def fetch_twitch_clip_metadata(clip_url):
    """Fetch clip metadata from Twitch API given a clip URL.
    Returns a clip dict matching DB schema, or None if not found.
    """
    # Extract clip ID from URL
    match = re.search(r"/clip/([\w-]+)", clip_url)
    if not match:
        return None
    clip_slug = match.group(1)

    token = get_access_token()
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }
    resp = requests.get(
        "https://api.twitch.tv/helix/clips",
        headers=headers,
        params={"id": clip_slug},
    )
    if not resp.ok:
        return None

    data = resp.json().get("data", [])
    if not data:
        return None

    clip = data[0]
    return {
        "clip_id":    clip["id"],
        "title":      clip["title"],
        "streamer":   clip["broadcaster_name"].lower(),
        "clip_url":   clip["url"],
        "mp4_url":    _mp4_url(clip.get("thumbnail_url", "")),
        "duration":   clip.get("duration", 0),
        "view_count": clip["view_count"],
        "created_at": clip["created_at"],
    }


# ============================================================
# Events
# ============================================================

@bot.event
async def on_ready():
    print(f"[discord] Logged in as {bot.user}")
    init_db()

    review_channel = bot.get_channel(DISCORD_CLIP_REVIEW_CHANNEL_ID)
    if not review_channel:
        print("[discord] ERROR: Could not find #clip-review channel — check DISCORD_CLIP_REVIEW_CHANNEL_ID")
        return

    # Post all fetched clips that haven't been sent to Discord yet
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM clips WHERE status = 'fetched' AND discord_message_id IS NULL"
    ).fetchall()
    conn.close()

    clips = [dict(r) for r in rows]
    if not clips:
        print("[discord] No new clips to post for review")
    else:
        print(f"[discord] Posting {len(clips)} clips for review...")
        for clip in clips:
            await post_clip_for_review(review_channel, clip)

    print("[discord] Ready")


@bot.event
async def on_raw_reaction_add(payload):
    """Handle ✅ / ❌ reactions on clip review messages."""
    # Ignore bot's own reactions
    if payload.user_id == bot.user.id:
        return

    # Only handle reactions in #clip-review
    if payload.channel_id != DISCORD_CLIP_REVIEW_CHANNEL_ID:
        return

    emoji = str(payload.emoji)
    if emoji not in (APPROVE_EMOJI, REJECT_EMOJI):
        return

    clip = get_clip_by_message_id(payload.message_id)
    if not clip:
        return

    if emoji == APPROVE_EMOJI:
        update_status(clip["clip_id"], "approved")
        print(f"[discord] APPROVED: {clip['clip_id']} ({clip['streamer']})")
    elif emoji == REJECT_EMOJI:
        update_status(clip["clip_id"], "rejected")
        print(f"[discord] REJECTED: {clip['clip_id']} ({clip['streamer']})")


@bot.event
async def on_message(message):
    """Handle two cases:
    1. Reply to a clip embed → use as custom title + approve
    2. Twitch clip URL in #clip-inbox → ingest and post for review
    """
    # Ignore bot's own messages
    if message.author.id == bot.user.id:
        return

    # ── Case 1: Reply to a clip embed in #clip-review ──
    if (
        message.channel.id == DISCORD_CLIP_REVIEW_CHANNEL_ID
        and message.reference is not None
    ):
        ref_id = message.reference.message_id
        clip = get_clip_by_message_id(ref_id)
        if clip:
            new_title = message.content.strip()
            if new_title:
                # Update title in DB then approve
                import sqlite3
                from config import DB_PATH
                from bot.db import now_utc
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE clips SET title = ?, status = 'approved', approved_at = ? WHERE clip_id = ?",
                    (new_title, now_utc(), clip["clip_id"])
                )
                conn.commit()
                conn.close()
                await message.add_reaction("👍")
                print(f"[discord] APPROVED with custom title: {clip['clip_id']} → '{new_title}'")
        return

    # ── Case 2: Twitch clip URL dropped in #clip-inbox ──
    if message.channel.id != DISCORD_CLIP_INBOX_CHANNEL_ID:
        return

    urls = TWITCH_CLIP_PATTERN.findall(message.content)
    if not urls:
        return

    review_channel = bot.get_channel(DISCORD_CLIP_REVIEW_CHANNEL_ID)
    if not review_channel:
        return

    for url in urls:
        await message.add_reaction("⏳")
        clip = await fetch_twitch_clip_metadata(url)
        if not clip:
            await message.add_reaction("❓")
            print(f"[discord] Could not fetch metadata for: {url}")
            continue

        insert_clip(clip)

        # Fetch the just-inserted clip to get full row
        import sqlite3
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM clips WHERE clip_id = ?", (clip["clip_id"],)
        ).fetchone()
        conn.close()

        if row:
            await post_clip_for_review(review_channel, dict(row))
            await message.add_reaction("✅")


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
