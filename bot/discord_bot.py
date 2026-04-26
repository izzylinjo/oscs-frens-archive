import discord
import re
import json
import requests
from config import (
    DISCORD_BOT_TOKEN,
    DISCORD_USER_ID,
    DISCORD_CLIP_REVIEW_CHANNEL_ID,
    DISCORD_CLIP_INBOX_CHANNEL_ID,
    DISCORD_CLIP_FINAL_APPROVAL_CHANNEL_ID,
    TWITCH_CLIENT_ID,
)
from bot.db import (
    init_db,
    insert_clip,
    update_status,
    update_title,
    update_discord_message,
    get_clip_by_message_id,
    get_conn,
    now_utc,
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
TITLE_EMOJIS  = ["1️⃣", "2️⃣", "3️⃣"]

TWITCH_CLIP_PATTERN = re.compile(
    r"https?://(?:www\.)?twitch\.tv/\w+/clip/[\w-]+"
)

# ============================================================
# Helpers — #clip-review
# ============================================================

def build_review_embed(clip):
    embed = discord.Embed(
        title=clip["title"],
        url=clip["clip_url"],
        color=0x9146FF,
    )
    embed.add_field(name="Streamer", value=clip["streamer"], inline=True)
    embed.add_field(name="Views",    value=f"{clip['view_count']:,}", inline=True)
    embed.add_field(name="Duration", value=f"{clip['duration']}s", inline=True)
    embed.set_footer(text=f"clip_id: {clip['clip_id']} | React ✅ approve  ❌ reject  or reply to set custom title")
    return embed


async def post_clip_for_review(channel, clip):
    embed = build_review_embed(clip)
    msg = await channel.send(embed=embed)
    await msg.add_reaction(APPROVE_EMOJI)
    await msg.add_reaction(REJECT_EMOJI)
    update_discord_message(clip["clip_id"], msg.id, channel.id)
    print(f"[discord] Posted for review: {clip['clip_id']} ({clip['streamer']})")


# ============================================================
# Helpers — #clip-final-approval
# ============================================================

def build_final_approval_embed(clip, titles):
    embed = discord.Embed(
        title=f"🎬 {clip['streamer']} — ready to post",
        url=clip["clip_url"],
        color=0xF4900C,
    )
    embed.add_field(name="Duration", value=f"{clip['duration']}s", inline=True)
    embed.add_field(name="Views",    value=f"{clip['view_count']:,}", inline=True)
    embed.add_field(name="​",   value="​", inline=True)

    options = "\n".join(f"{TITLE_EMOJIS[i]} {t}" for i, t in enumerate(titles))
    embed.add_field(name="Title options", value=options, inline=False)
    embed.set_footer(text=f"clip_id: {clip['clip_id']} | React 1️⃣2️⃣3️⃣ to pick · reply to set custom · ❌ to reject")
    return embed


async def post_for_final_approval(channel, clip, titles):
    embed = build_final_approval_embed(clip, titles)
    msg = await channel.send(embed=embed)
    for emoji in TITLE_EMOJIS:
        await msg.add_reaction(emoji)
    await msg.add_reaction(REJECT_EMOJI)
    update_discord_message(clip["clip_id"], msg.id, channel.id)
    print(f"[discord] Posted for final approval: {clip['clip_id']} ({clip['streamer']})")


# ============================================================
# Twitch metadata fetch (for #clip-inbox)
# ============================================================

async def fetch_twitch_clip_metadata(clip_url):
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
        print("[discord] ERROR: Could not find #clip-review channel")
        return

    from config import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM clips WHERE status = 'fetched' AND discord_message_id IS NULL"
    ).fetchall()
    conn.close()

    clips = [dict(r) for r in rows]
    if clips:
        print(f"[discord] Posting {len(clips)} clips for review...")
        for clip in clips:
            await post_clip_for_review(review_channel, clip)
    else:
        print("[discord] No new clips to post for review")

    print("[discord] Ready")


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    emoji = str(payload.emoji)

    # ── #clip-review: approve / reject ──
    if payload.channel_id == DISCORD_CLIP_REVIEW_CHANNEL_ID:
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

    # ── #clip-final-approval: pick title / reject ──
    elif payload.channel_id == DISCORD_CLIP_FINAL_APPROVAL_CHANNEL_ID:
        if emoji not in TITLE_EMOJIS and emoji != REJECT_EMOJI:
            return
        clip = get_clip_by_message_id(payload.message_id)
        if not clip or clip["status"] != "awaiting_title":
            return

        if emoji == REJECT_EMOJI:
            update_status(clip["clip_id"], "rejected")
            print(f"[discord] FINAL REJECTED: {clip['clip_id']}")
            return

        # Pick the title by index
        idx = TITLE_EMOJIS.index(emoji)
        titles = json.loads(clip["title_options"]) if clip.get("title_options") else []
        if idx < len(titles):
            chosen = titles[idx]
            update_title(clip["clip_id"], chosen)
            update_status(clip["clip_id"], "queued")
            print(f"[discord] TITLE SELECTED ({emoji}): '{chosen}' — {clip['clip_id']}")


@bot.event
async def on_message(message):
    if message.author.id == bot.user.id:
        return

    # ── Reply in #clip-review → custom title + approve ──
    if (
        message.channel.id == DISCORD_CLIP_REVIEW_CHANNEL_ID
        and message.reference is not None
    ):
        clip = get_clip_by_message_id(message.reference.message_id)
        if clip:
            new_title = message.content.strip()
            if new_title:
                conn = get_conn()
                conn.execute(
                    "UPDATE clips SET custom_title = ?, title = ?, status = 'approved', approved_at = ? WHERE clip_id = ?",
                    (new_title, new_title, now_utc(), clip["clip_id"])
                )
                conn.commit()
                conn.close()
                await message.add_reaction("👍")
                print(f"[discord] APPROVED with custom title: {clip['clip_id']} → '{new_title}'")
        return

    # ── Reply in #clip-final-approval → custom title + queue ──
    if (
        message.channel.id == DISCORD_CLIP_FINAL_APPROVAL_CHANNEL_ID
        and message.reference is not None
    ):
        clip = get_clip_by_message_id(message.reference.message_id)
        if clip and clip["status"] == "awaiting_title":
            new_title = message.content.strip()
            if new_title:
                if len(new_title) > 60:
                    new_title = new_title[:57] + "..."
                conn = get_conn()
                conn.execute(
                    "UPDATE clips SET custom_title = ?, title = ?, status = 'queued', queued_at = ? WHERE clip_id = ?",
                    (new_title, new_title, now_utc(), clip["clip_id"])
                )
                conn.commit()
                conn.close()
                await message.add_reaction("👍")
                print(f"[discord] CUSTOM TITLE + QUEUED: {clip['clip_id']} → '{new_title}'")
        return

    # ── Twitch clip URL in #clip-inbox → ingest ──
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

        from config import DB_PATH
        import sqlite3
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
