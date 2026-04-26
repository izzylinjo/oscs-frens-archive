import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.db import init_db
from bot.twitch import fetch_all_new_clips
from bot.discord_bot import bot, post_clip_for_review
from bot.queue import fill_queue, post_next_queued
from config import DISCORD_BOT_TOKEN, DISCORD_CLIP_REVIEW_CHANNEL_ID


async def twitch_fetch_job():
    """Fetch new clips and post them to #clip-review."""
    print("[main] Twitch fetch triggered")
    clips = await asyncio.to_thread(fetch_all_new_clips)

    channel = bot.get_channel(DISCORD_CLIP_REVIEW_CHANNEL_ID)
    if not channel:
        print("[main] ERROR: #clip-review channel not found — clips saved to DB only")
        return

    for clip in clips:
        await post_clip_for_review(channel, clip)

    print(f"[main] {len(clips)} new clips posted to Discord")


async def queue_cycle_job():
    """Fill queue with approved clips, then post the next queued clip."""
    print("[main] Queue cycle triggered")
    await asyncio.to_thread(fill_queue, bot)
    await asyncio.to_thread(post_next_queued)


async def main():
    init_db()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(twitch_fetch_job, "cron", hour="0,12", minute=0)
    scheduler.add_job(queue_cycle_job, "interval", minutes=30)
    scheduler.start()
    print("[main] Scheduler running. Starting Discord bot...")

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
