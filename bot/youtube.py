import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from config import YOUTUBE_CLIENT_SECRETS_FILE, STREAMER_SOCIALS, BASE_DIR

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = os.path.join(BASE_DIR, "youtube_token.json")


def _get_credentials():
    """Return valid OAuth2 credentials, refreshing or re-authorizing as needed."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def _build_description(clip):
    streamer = clip["streamer"].lower()
    socials = STREAMER_SOCIALS.get(streamer, {})

    lines = [f"Clip from {clip['streamer']}'s stream.", ""]

    for platform, label in [
        ("twitch",  "Twitch"),
        ("twitter", "Twitter"),
        ("tiktok",  "TikTok"),
        ("youtube", "YouTube"),
    ]:
        link = socials.get(platform, "")
        if link:
            lines.append(f"{label}: {link}")

    lines += ["", "#Shorts #Gaming #Twitch"]
    return "\n".join(lines)


def upload_clip(clip, video_path):
    """Upload a clip to YouTube Shorts. Returns the YouTube video ID."""
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    title = (clip["title"][:92] + " #Shorts") if len(clip["title"]) > 92 else clip["title"] + " #Shorts"
    description = _build_description(clip)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["Shorts", "Gaming", "Twitch", clip["streamer"]],
            "categoryId": "20",  # Gaming
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    print(f"[youtube] Uploading: {title}")
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[youtube] {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"[youtube] Done: https://youtube.com/shorts/{video_id}")
    return video_id
