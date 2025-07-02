"""
Remux an MKV to a QuickTime‑friendly MP4 (no video re‑encode).

The script performs three main tasks:

1. **Collect metadata** using *ffprobe* to discover the original codecs and
   duration of the file.
2. **Construct and run** an *ffmpeg* command that:
     • copies the video stream as‑is;
     • transcodes DTS audio to loss‑less ALAC (for Apple compatibility);
     • tags HEVC/H.265 video as **hvc1** so QuickTime can play it;
     • sets the `+faststart` flag so the MP4 can begin playback before
       finishing downloading.
3. **Monitor progress** by reading *ffmpeg*’s `-progress pipe:1` output and
   converting the timestamps to a human‑readable percentage that updates in
   place on the terminal.

Usage
-----
Simply run the file, pick an `.mkv` when the file‑chooser appears, and wait
until you see a green ✅.

The exit code is forwarded from *ffmpeg*, so you can use the script inside
other tooling.

Tested on macOS 14 / Python 3.12, ffmpeg 7.0.
"""

# ────────────────────────────────────────────────────────────────────────────────
# Standard library imports
# ────────────────────────────────────────────────────────────────────────────────
import os
import re
import subprocess
import sys
from tkinter import Tk
from tkinter.filedialog import askopenfilename

# ────────────────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────────────────

def pick_mkv() -> str:
    """Open a native file‑dialog and return the path to the chosen MKV.

    Returns an empty string if the user cancels.
    """
    Tk().withdraw()  # hide the tiny root window that Tk creates
    return askopenfilename(
        title="Select an MKV",
        filetypes=[("Matroska", "*.mkv")]
    )


def ffprobe_field(path: str, sel: str, field: str) -> str:
    """Query *ffprobe* for a **single** field of a single stream.

    Parameters
    ----------
    path : str
        Path to the media file.
    sel : str
        `-select_streams` value, e.g. "v:0" for the first video stream or
        "a:0" for the first audio stream.
    field : str
        Name of the field you wish to extract (e.g. "codec_name").

    Returns
    -------
    str
        The value reported by ffprobe (empty string if not present).
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", sel,
        "-show_entries", f"stream={field}",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    return subprocess.check_output(cmd, text=True).strip()


def get_duration(path: str) -> float:
    """Return the duration of *path* in seconds (float)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    return float(subprocess.check_output(cmd, text=True).strip())


def detect_audio_codec(path: str) -> str:
    """Detect the audio codec of the first audio stream (e.g. 'dts', 'aac')."""
    return ffprobe_field(path, "a:0", "codec_name")


def detect_video_codec(path: str) -> str:
    """Detect the video codec of the first video stream (e.g. 'hevc', 'h264')."""
    return ffprobe_field(path, "v:0", "codec_name")


def build_ffmpeg_cmd(src: str, dst: str, acodec: str, vcodec: str) -> list[str]:
    """Construct the ffmpeg command for the given inputs.

    The logic is:

    * Copy the video stream (`-c:v copy`).
    * If the audio codec is DTS, transcode it to ALAC (`-c:a alac`);
      otherwise copy the audio stream.
    * For HEVC, tag the four‑character‑code as *hvc1* so that Apple’s
      decoders recognise the stream.
    * Use `+faststart` so the moov atom is at the beginning of the file.
    * Ask ffmpeg to emit progress information to STDOUT (`-progress pipe:1`)
      while suppressing its usual "frame=..." spam (`-nostats`).

    Returns
    -------
    list[str]
        The argv list ready to be passed to subprocess.
    """
    audio_args = ["-c:a", "alac"] if acodec.lower() == "dts" else ["-c:a", "copy"]
    tag_args = ["-tag:v", "hvc1"] if vcodec.lower() in {"hevc", "h265"} else []

    return [
        "ffmpeg", "-y",  # overwrite output without asking
        "-i", src,
        "-c:v", "copy",
        *audio_args,
        "-movflags", "+faststart",
        *tag_args,
        "-progress", "pipe:1",  # emit key=value lines
        "-nostats",               # no per‑frame log spam
        dst,
    ]


# ────────────────────────────────────────────────────────────────────────────────
# High‑level orchestration
# ────────────────────────────────────────────────────────────────────────────────

def remux_with_progress(src: str) -> None:
    """Run ffmpeg and display an updating percentage until completion."""

    total_duration = get_duration(src)
    dst = os.path.splitext(src)[0] + ".mp4"

    # Detect codecs once up‑front so we can decide whether to transcode/tag.
    acodec = detect_audio_codec(src)
    vcodec = detect_video_codec(src)
    print(f"Audio: {acodec or 'unknown'} | Video: {vcodec or 'unknown'}")

    cmd = build_ffmpeg_cmd(src, dst, acodec, vcodec)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,  # <- read progress here
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,               # line‑buffered
    )

    # Pre‑compile regexes used to parse `ffmpeg -progress` output.
    # Example lines:
    #   out_time_ms=123456789
    #   out_time=00:02:03.456789
    re_us  = re.compile(r"out_time_ms=(\d+)")
    re_hms = re.compile(r"out_time=([\d:.]+)")
    last_pct = -1  # sentinel so that 0 % is printed immediately

    for line in proc.stdout:
        # Try micro‑seconds first (ffmpeg 4.4+). Fall back to h:m:s if absent.
        if (m := re_us.search(line)):
            done_seconds = int(m.group(1)) / 1_000_000  # µs → s
        elif (m := re_hms.search(line)):
            h, m_, s = map(float, m.group(1).split(":"))  # h, m, s.sss
            done_seconds = h * 3600 + m_ * 60 + s
        else:
            continue  # unrelated line

        pct = min(done_seconds / total_duration * 100, 100)
        if int(pct) != last_pct:  # update only on integer change to reduce flicker
            print(f"\rProgress: {pct:6.2f} %", end="", flush=True)
            last_pct = int(pct)

    # Wait for ffmpeg to exit and mirror its return code.
    proc.wait()
    status = "✅ Completed" if proc.returncode == 0 else "❌ Failed"
    print(f"\n{status}: {dst}")
    sys.exit(proc.returncode)


# ────────────────────────────────────────────────────────────────────────────────
# Script entry‑point
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    source_file = pick_mkv()
    if not source_file:
        sys.exit("No file selected.")
    if not source_file.lower().endswith(".mkv"):
        sys.exit("Please pick an MKV.")

    remux_with_progress(source_file)
