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
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_titles(clip, local_path):
    """Return 3 title options for a clip as a list of strings.

    Transcribes with Whisper, then asks Gemini for 3 distinct options.
    Falls back to [original_title] (list of one) if transcript is empty.
    """
    print(f"[titles] Transcribing {clip['clip_id']}...")
    transcript = _transcribe(local_path)

    if not transcript:
        print("[titles] Empty transcript — using original title as only option")
        return [clip["title"]]

    print(f"[titles] Transcript ({len(transcript)} chars): {transcript[:80]}...")

    prompt = f"""Write 3 different YouTube Shorts titles for a Twitch gaming clip.

Streamer: {clip['streamer']}
Original title: {clip['title']}
Transcript: {transcript}

Rules for each title:
- Under 60 characters
- Sparks curiosity, does NOT use clickbait phrases
- Feels natural, like something a fan would say
- Do NOT start with "Check out", "Watch", "This", or "When"
- Include the streamer name only if it genuinely improves the title
- Each title must be meaningfully different from the others

Reply with EXACTLY 3 titles, one per line, numbered like:
1. Title one here
2. Title two here
3. Title three here

No extra text, no quotes."""

    raw = _ask_gemini(prompt)

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
