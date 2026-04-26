import os
import subprocess


def add_overlay(input_path, streamer_name):
    """Burn streamer name in bottom-left corner using ffmpeg drawtext.

    Returns the path to the new output file.
    Raises RuntimeError if ffmpeg exits non-zero.
    """
    base, ext = os.path.splitext(input_path)
    output_path = base + "_overlay" + ext

    # Strip characters that would break the drawtext filter string
    safe_name = streamer_name.replace("'", "").replace("\\", "").replace(":", "")

    drawtext = (
        f"drawtext=text='{safe_name}':"
        "fontcolor=white:"
        "fontsize=18:"
        "x=10:y=h-th-10:"
        "shadowcolor=black:shadowx=1:shadowy=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", drawtext,
        "-codec:a", "copy",
        output_path,
    ]

    print(f"[overlay] Burning overlay for '{streamer_name}'...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"[overlay] ffmpeg failed:\n{result.stderr[-500:]}")

    print(f"[overlay] Done: {os.path.basename(output_path)}")
    return output_path
