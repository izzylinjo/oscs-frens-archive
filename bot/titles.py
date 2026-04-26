import requests
from config import GEMINI_API_KEY, GEMINI_MODEL

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        print("[titles] Loading Whisper base model...")
        _whisper_model = whisper.load_model("base")
    return _whisper_model


def _transcribe(video_path):
    model = _get_whisper_model()
    result = model.transcribe(video_path)
    return result["text"].strip()


def _ask_gemini(prompt):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    resp = requests.post(
        url,
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    # First line only, strip surrounding quotes
    return raw.strip().splitlines()[0].strip().strip('"').strip("'")


def generate_title(clip, local_path):
    """Return the best title for a clip.

    Returns custom_title immediately if set by the reviewer.
    Otherwise transcribes with Whisper and generates a title via Gemini.
    Falls back to the original Twitch title if transcript is empty.
    """
    if clip.get("custom_title"):
        print(f"[titles] Using custom title: {clip['custom_title']}")
        return clip["custom_title"]

    print(f"[titles] Transcribing {clip['clip_id']}...")
    transcript = _transcribe(local_path)

    if not transcript:
        print(f"[titles] Empty transcript — keeping original title")
        return clip["title"]

    print(f"[titles] Transcript ({len(transcript)} chars): {transcript[:80]}...")

    prompt = f"""Write a YouTube Shorts title for a Twitch gaming clip.

Streamer: {clip['streamer']}
Original title: {clip['title']}
Transcript: {transcript}

Rules:
- Under 60 characters
- Sparks curiosity, does NOT use clickbait phrases
- Feels natural, like something a fan would say
- Do NOT start with "Check out", "Watch", "This", or "When"
- Include the streamer name only if it genuinely improves the title

Reply with ONLY the title. No quotes, no explanation."""

    title = _ask_gemini(prompt)

    if len(title) > 60:
        title = title[:57] + "..."

    print(f"[titles] Generated: {title}")
    return title
