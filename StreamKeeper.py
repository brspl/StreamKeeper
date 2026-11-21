import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PLATFORMS = {
    "twitch": "https://www.twitch.tv/{}",
    "kick": "https://kick.com/{}",
    "youtube": "https://www.youtube.com/@{}/live",
}

# streamlink stderr fragments that let us tell "offline" apart from
# "stream is live, but the requested quality does not exist"
NO_STREAMS_MARKERS = (
    "No playable streams",
    "does not appear to be live",
    "is offline",
)
QUALITY_MARKERS = (
    "could not be found",
    "Available streams",
)


def check_dependencies() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"ERROR: {tool} not found. Add ffmpeg's 'bin' folder to your PATH.")

    result = subprocess.run(
        [sys.executable, "-m", "streamlink", "--version"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"ERROR: streamlink not installed. Run: \"{sys.executable}\" -m pip install streamlink")


def safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", text).strip("_") or "stream"


def resolve_target(value: str, platform: str) -> tuple[str, str, bool]:
    """Return (url, label, is_vod). A VOD/archive URL is not expected to 'go live'."""
    value = value.strip()

    if value.startswith("@") and not value.startswith(("http://", "https://")):
        name = value[1:]
        return PLATFORMS["youtube"].format(name), safe_name(name), False

    if not value.startswith(("http://", "https://")):
        name = value.strip("/").lstrip("@")
        return PLATFORMS[platform].format(name), safe_name(name), False

    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [p for p in parsed.path.split("/") if p]

    if host == "youtu.be":
        video_id = parts[0] if parts else ""
        return f"https://www.youtube.com/watch?v={video_id}", safe_name(f"yt_{video_id}"), True

    if host.endswith("youtube.com"):
        if parts and parts[0] == "watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            return value, safe_name(f"yt_{video_id}"), True
        if len(parts) >= 2 and parts[0] == "live":
            return f"https://www.youtube.com/watch?v={parts[1]}", safe_name(f"yt_{parts[1]}"), True
        if parts and parts[-1] == "live":
            parts = parts[:-1]
        if parts:
            return f"https://www.youtube.com/{'/'.join(parts)}/live", safe_name(parts[-1].lstrip("@")), False
        sys.exit(f"ERROR: unrecognized YouTube address: {value}")

    if host.endswith(("twitch.tv", "kick.com")):
        clean = f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts)}"
        is_vod = any(p in ("videos", "video", "clips", "clip") for p in parts)
        label = parts[-1] if parts else host
        return clean, safe_name(label), is_vod

    label = f"{host.split('.')[0]}_{parts[-1]}" if parts else host
    return value, safe_name(label), True


def build_streamlink_cmd(url: str, quality: str, sl_args: list[str]) -> list[str]:
    return [sys.executable, "-m", "streamlink", "--stdout", *sl_args, url, quality]


def classify_failure(stderr: str) -> str:
    low = stderr.lower()
    if any(m.lower() in low for m in NO_STREAMS_MARKERS):
        return "offline"
    if any(m.lower() in low for m in QUALITY_MARKERS):
        return "quality"
    return "unknown"


def record(url: str, quality: str, ts_file: Path, sl_args: list[str],
           wait: int, is_vod: bool) -> bool:
    cmd = build_streamlink_cmd(url, quality, sl_args)
    if wait and not is_vod:
        # streamlink retries: poll every `wait` seconds until streams appear
        cmd = [sys.executable, "-m", "streamlink", "--stdout",
               "--retry-streams", str(wait), "--retry-max", "0",  # 0 = unlimited
               *sl_args, url, quality]
        print(f"Stream not live yet - waiting (checking every {wait}s, Ctrl+C to abort).")

    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
        "-i", "-",
        "-c", "copy",
        "-f", "mpegts", str(ts_file),
    ]

    print(f"Recording: {url} (quality: {quality})")
    print(f"Temporary file: {ts_file}")
    print("Press Ctrl+C to stop recording.\n")

    # stderr goes to a temp file rather than a pipe: we want streamlink's
    # diagnostics after it exits, but communicate() would fail (we hand
    # stdout to ffmpeg and close our copy), and a PIPE could deadlock once
    # its 64KB buffer fills during a long --wait.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as sl_err:
        streamlink = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=sl_err)
        ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=streamlink.stdout)
        streamlink.stdout.close()

        interrupted = False
        try:
            ffmpeg.wait()
        except KeyboardInterrupt:
            interrupted = True
            print("\nStopping recording... finishing file writes.")
            # stop the producer first: ffmpeg then sees EOF on stdin and
            # finalizes the file on its own, instead of sitting in wait()
            if streamlink.poll() is None:
                streamlink.terminate()
            try:
                streamlink.wait(timeout=5)
            except subprocess.TimeoutExpired:
                streamlink.kill()
                streamlink.wait()
            try:
                ffmpeg.wait(timeout=15)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                print("ffmpeg did not exit in time - terminating (file may be truncated).")
                ffmpeg.terminate()
                ffmpeg.wait()
        finally:
            if streamlink.poll() is None:
                streamlink.terminate()
            streamlink.wait()
            sl_err.seek(0)
            sl_stderr = sl_err.read()

    # If streamlink died on its own (e.g. offline / bad quality) it produces
    # no data and ffmpeg exits quickly with an empty file - explain why.
    if not interrupted and streamlink.returncode != 0:
        reason = classify_failure(sl_stderr or "")
        if reason == "offline":
            print("\nNo playable streams: the channel appears to be offline.")
        elif reason == "quality":
            print(f"\nThe stream is live, but quality '{quality}' is not available.")
            print("Available qualities were listed by streamlink above; try e.g. 'best' or '720p'.")
        else:
            tail = (sl_stderr or "").strip().splitlines()
            msg = tail[-1] if tail else f"exit code {streamlink.returncode}"
            print(f"\nstreamlink failed: {msg}")

    return ts_file.exists() and ts_file.stat().st_size > 0


def probe_audio_codec(ts_file: Path) -> str:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name", "-of",
        "default=noprint_wrappers=1:nokey=1", str(ts_file),
    ]
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def remux_to_mp4(ts_file: Path, mp4_file: Path) -> bool:
    print(f"\nConverting to MP4: {mp4_file}")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(ts_file),
        "-c", "copy",
        "-dn",
        "-movflags", "+faststart",
    ]
    # aac_adtstoasc is only valid for AAC audio; applying it to other codecs
    # (mp3, opus...) makes ffmpeg fail or produce broken files
    if probe_audio_codec(ts_file) == "aac":
        cmd += ["-bsf:a", "aac_adtstoasc"]
    cmd.append(str(mp4_file))
    return subprocess.run(cmd).returncode == 0


def validate_mp4(mp4_file: Path) -> bool:
    """Decode-check the container: catches files truncated by a forced stop."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(mp4_file), "-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def unique_path(directory: Path, label: str, ext: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    candidate = directory / f"{label}_{stamp}{ext}"
    n = 1
    while candidate.exists():
        candidate = directory / f"{label}_{stamp}_{n}{ext}"
        n += 1
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record live streams (Twitch, YouTube, Kick and other streamlink-supported sites) to MP4.")
    parser.add_argument("target",
                        help="stream URL (any site supported by streamlink), a YouTube @handle, "
                             "or a bare channel name (see --platform)")
    parser.add_argument("--platform", choices=list(PLATFORMS), default="twitch",
                        help="platform for bare channel names (default: twitch)")
    parser.add_argument("--quality", default="best",
                        help="best, worst, 1080p60, 720p60, 480p, audio_only... (default: best)")
    parser.add_argument("--output-dir", default="recordings",
                        help="directory for .ts recordings (default: ./recordings)")
    parser.add_argument("--mp4-dir", default=None,
                        help="separate directory for finished MP4 files (default: same as --output-dir)")
    parser.add_argument("--no-convert", action="store_true",
                        help="keep only the .ts file, skip MP4 conversion")
    parser.add_argument("--keep-ts", action="store_true",
                        help="don't delete the .ts file after a successful conversion")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                        help="if the stream is offline, wait and retry every SECONDS until it goes live "
                             "(0 = fail immediately)")
    parser.add_argument("--twitch-ads", action="store_true",
                        help="keep Twitch ads in the recording (by default --twitch-disable-ads is passed)")
    parser.add_argument("--sl-arg", action="append", default=[], metavar="ARG",
                        help="extra argument passed to streamlink, repeatable, "
                             "e.g. --sl-arg=--http-cookie --sl-arg=name=value")
    args = parser.parse_args()

    check_dependencies()

    url, label, is_vod = resolve_target(args.target, args.platform)

    sl_args = list(args.sl_arg)
    if "twitch.tv" in url and not args.twitch_ads:
        sl_args.append("--twitch-disable-ads")

    ts_dir = Path(args.output_dir)
    mp4_dir = Path(args.mp4_dir) if args.mp4_dir else ts_dir
    ts_dir.mkdir(parents=True, exist_ok=True)
    mp4_dir.mkdir(parents=True, exist_ok=True)

    ts_file = unique_path(ts_dir, label, ".ts")
    mp4_file = unique_path(mp4_dir, label, ".mp4")

    if not record(url, args.quality, ts_file, sl_args, args.wait, is_vod):
        ts_file.unlink(missing_ok=True)
        sys.exit("\nNothing was recorded.")

    size_mb = ts_file.stat().st_size / 1024 / 1024
    print(f"\nRecording saved: {ts_file} ({size_mb:.1f} MB)")

    if args.no_convert:
        return

    if not remux_to_mp4(ts_file, mp4_file):
        print(f"Conversion failed. The original recording is kept at: {ts_file}")
        sys.exit(1)

    if not validate_mp4(mp4_file):
        print(f"WARNING: {mp4_file} failed an integrity check - it was probably")
        print(f"interrupted mid-write. The .ts source is kept alongside it.")
        sys.exit(1)

    print(f"Done: {mp4_file}")
    if not args.keep_ts:
        ts_file.unlink()
        print("ts file deleted.")


if __name__ == "__main__":
    main()
    