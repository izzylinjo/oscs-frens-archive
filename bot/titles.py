import base64
import requests
from config import GEMINI_API_KEY, GEMINI_MODEL

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        print("[titles] Loading Whisper small model on GPU...")
        _whisper_model = whisper.load_model("small", device="cuda")
    return _whisper_model


def _transcribe(video_path):
    model = _get_whisper_model()
    result = model.transcribe(video_path, language="en")
    return result["text"].strip()


def _get_thumbnail_b64(clip):
    """Download clip thumbnail and return as base64, or None if unavailable."""
    mp4_url = clip.get("mp4_url")
    if not mp4_url:
        return None
    thumbnail_url = mp4_url.replace(".mp4", "-preview-480x272.jpg")
    try:
        resp = requests.get(thumbnail_url, timeout=10)
        if resp.ok and "image" in resp.headers.get("content-type", ""):
            return base64.b64encode(resp.content).decode("utf-8")
    except Exception:
        pass
    return None


def _ask_gemini(prompt, image_b64=None):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    parts = []
    if image_b64:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": image_b64,
            }
        })
    parts.append({"text": prompt})

    resp = requests.post(
        url,
        json={"contents": [{"parts": parts}]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_titles(clip, local_path):
    """Return 3 title options for a clip as a list of strings.

    Sends the clip thumbnail + transcript to Gemini for visual + audio context.
    Falls back to [original_title] if transcript is empty and thumbnail unavailable.
    """
    print(f"[titles] Transcribing {clip['clip_id']}...")
    transcript = _transcribe(local_path)

    image_b64 = _get_thumbnail_b64(clip)
    if image_b64:
        print("[titles] Thumbnail fetched — sending to Gemini with transcript")
    else:
        print("[titles] No thumbnail available — text only")

    if not transcript and not image_b64:
        print("[titles] No transcript or thumbnail — using original title")
        return [clip["title"]]

    if transcript:
        print(f"[titles] Transcript ({len(transcript)} chars): {transcript[:80]}...")

    prompt = f"""You are writing YouTube Shorts titles for clips from OSCS, a group of friends who stream together and constantly roast each other. The clips are funny because of the streamers' personalities, reactions, and group dynamics — not because of the game they're playing.

Streamer: {clip['streamer']}
Original Twitch title: {clip['title']}
Audio transcript: {transcript if transcript else "(no clear audio)"}

{'I have also provided a screenshot from the clip so you can see what is happening visually.' if image_b64 else ''}

First, in 2-3 sentences, describe what is actually happening in this clip — the situation, the vibe, who might be involved, and what makes it funny or interesting. Consider the audio and the visual together.

Then, write 3 different YouTube Shorts titles based on your understanding of the moment.

Title rules:
- Under 60 characters, but shorter is almost always better — 2 to 6 words often beats a full sentence
- Think meme caption, not YouTube description — don't explain the joke, just name the vibe
- Focus on the streamer's reaction, personality, or the moment — NOT the game
- Do NOT use: "Check out", "Watch", "This", "When", "You won't believe"
- Do NOT mention the game name unless it genuinely makes the title better
- Each title must be meaningfully different from the others — vary the angle, not just the wording
- If it needs explaining, it's too long

Reply in this exact format:
SITUATION: (your 2-3 sentence description)
1. Title one here
2. Title two here
3. Title three here

No extra text, no quotes."""

    raw = _ask_gemini(prompt, image_b64=image_b64)

    # Extract and log the situation analysis
    for line in raw.splitlines():
        if line.strip().startswith("SITUATION:"):
            print(f"[titles] Situation: {line.strip()[len('SITUATION:'):].strip()}")
            break

    titles = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and ". " in line:
            title = line.split(". ", 1)[1].strip().strip('"').strip("'")
            if len(title) > 60:
                title = title[:57] + "..."
            titles.append(title)

    if len(titles) != 3:
        print(f"[titles] WARNING: expected 3 titles, got {len(titles)} — padding with original")
        while len(titles) < 3:
            titles.append(clip["title"])

    print(f"[titles] Generated {len(titles)} options:")
    for i, t in enumerate(titles, 1):
        print(f"  {i}. {t}")

    return titles
