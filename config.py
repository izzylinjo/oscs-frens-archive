import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Validate required keys — crashes loudly if anything missing
# ============================================================
REQUIRED = [
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "GEMINI_API_KEY",
    "DISCORD_BOT_TOKEN",
    "DISCORD_USER_ID",
]

missing = [key for key in REQUIRED if not os.getenv(key)]
if missing:
    raise EnvironmentError(
        f"\n\nMissing required environment variables:\n"
        + "\n".join(f"  - {k}" for k in missing)
        + "\n\nFill these in your .env file before running the bot.\n"
    )

# ============================================================
# Twitch
# ============================================================
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

# All streamers to track — add or remove anytime
STREAMERS = [
    # OSCS core
    "youngbasedgo",
    "yugi2x",
    "redify",
    "bigmonraph",
    "sunnys",
    "santipulgaz",
    "arky",
    "Nosiiree",
    "1jdab1",
    # Friends
    "bonnie",
    "aoizami",
]

# How many top clips to fetch per streamer per stream
CLIPS_PER_STREAMER = 3

# Hours to wait after a stream ends before fetching clips
POLL_DELAY_HOURS = 3

# ============================================================
# Gemini
# ============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ============================================================
# Discord
# ============================================================
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_USER_ID = int(os.getenv("DISCORD_USER_ID"))

# ============================================================
# YouTube
# ============================================================
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv(
    "YOUTUBE_CLIENT_SECRETS_FILE", "client_secrets.json"
)

# ============================================================
# Queue / posting
# ============================================================
# Minutes between each YouTube Short post
POST_STAGGER_MINUTES = 30

# ============================================================
# Paths
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
DB_PATH = os.path.join(BASE_DIR, "db", "clips.db")

# ============================================================
# Quick self-check — run this file directly to verify config
# ============================================================
if __name__ == "__main__":
    print("Config OK")
    print(f"  Tracking {len(STREAMERS)} streamers")
    print(f"  Clips per streamer: {CLIPS_PER_STREAMER}")
    print(f"  Poll delay: {POLL_DELAY_HOURS} hours after stream ends")
    print(f"  Post stagger: {POST_STAGGER_MINUTES} minutes between posts")
    print(f"  Downloads dir: {DOWNLOADS_DIR}")
    print(f"  DB path: {DB_PATH}")
