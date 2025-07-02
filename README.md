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
