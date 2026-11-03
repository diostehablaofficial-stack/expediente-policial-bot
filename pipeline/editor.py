import os
import subprocess
import json
import sys
import struct
import shutil
from PIL import Image, ImageDraw, ImageFont

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def find_font(font_name, font_dir):
    """
    Looks for font in local fonts directory first, then Windows fonts, then fallback.
    """
    candidates = [
        os.path.join(font_dir, font_name),
        os.path.join(font_dir, font_name.lower()),
        os.path.join("C:\\Windows\\Fonts", font_name),
        os.path.join("C:\\Windows\\Fonts", font_name.lower()),
        f"/usr/share/fonts/truetype/{font_name}",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def check_has_audio(file_path):
    """
    Checks if a media file has an audio stream.
    """
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            file_path
        ]
        out = subprocess.check_output(cmd).decode().strip()
        return bool(out)
    except Exception:
        return False

def verify_voice_and_audio(output_mp4, min_rms=200.0):
    """
    Automated safeguard: Validates that the rendered video has a healthy,
    audible audio stream where voice and sound are clearly present.
    Raises RuntimeError if video is silent or audio is missing.
    """
    if not os.path.exists(output_mp4) or os.path.getsize(output_mp4) < 100000:
        raise RuntimeError(f"[AudioGuard] Output file missing or too small: {output_mp4}")
        
    cmd = [
        "ffmpeg", "-y", "-ss", "4.0", "-t", "8.0",
        "-i", output_mp4,
        "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw, _ = proc.communicate()
    if not raw or len(raw) < 1000:
        raise RuntimeError(f"[AudioGuard] Failed to read audio stream from {output_mp4}!")
        
    samples = struct.unpack(f"<{len(raw)//2}h", raw)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    peak = max(abs(s) for s in samples)
    print(f"[AudioGuard] Audio verification passed: RMS={rms:.1f}, Peak={peak} (Threshold: {min_rms})")
    if rms < min_rms:
        raise RuntimeError(f"[AudioGuard] CRITICAL: Video audio stream is silent or near-inaudible (RMS: {rms:.1f} < {min_rms})!")

def generate_header_card(badge_sub, badge_title, output_png, fonts_dir):
    """
    Generates the top pill header banner matching EXP 001-007.
    Size: 1000x170, transparent background, red border, blinking REC dot, yellow title.
    """
    header_img = Image.new("RGBA", (1000, 170), (0, 0, 0, 0))
    draw = ImageDraw.Draw(header_img)
    
    impact_path = find_font("Impact.ttf", fonts_dir)
    arial_path = find_font("ariblk.ttf", fonts_dir) or find_font("arialbd.ttf", fonts_dir)
    
    try:
        font_sub = ImageFont.truetype(arial_path, 25) if arial_path else ImageFont.load_default()
        font_title = ImageFont.truetype(impact_path, 64) if impact_path else ImageFont.load_default()
    except Exception as e:
        print(f"[Editor] Font load warning: {e}. Using default fonts.")
        font_sub = ImageFont.load_default()
        font_title = ImageFont.load_default()

    # Outer pill
    draw.rounded_rectangle([0, 0, 1000, 170], radius=16, fill=(15, 20, 28, 235), outline=(220, 38, 38, 255), width=3)
    # Red REC dot
    draw.ellipse([30, 26, 54, 50], fill=(239, 68, 68, 255))
    # Subtitle
    draw.text((68, 22), badge_sub.upper(), font=font_sub, fill=(255, 255, 255, 255))
    # Title (Impact Yellow)
    draw.text((30, 68), badge_title.upper(), font=font_title, fill=(255, 230, 0, 255))
    
    header_img.save(output_png)
    print(f"[Editor] Header card PNG created: {output_png}")

def generate_teaser_pill(output_png, fonts_dir):
    """
    Generates high-impact cold open teaser badge: 'A CONTINUACIÓN...'
    """
    impact_path = find_font("Impact.ttf", fonts_dir)
    arial_path = find_font("ariblk.ttf", fonts_dir) or find_font("arialbd.ttf", fonts_dir)
    try:
        font_sub = ImageFont.truetype(arial_path, 26) if arial_path else ImageFont.load_default()
        font_title = ImageFont.truetype(impact_path, 74) if impact_path else ImageFont.load_default()
    except Exception as e:
        print(f"[Editor] Font load warning in teaser: {e}. Using default.")
        font_sub = ImageFont.load_default()
        font_title = ImageFont.load_default()

    img = Image.new("RGBA", (1000, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, 1000, 180], radius=20, fill=(15, 20, 28, 245), outline=(220, 38, 38, 255), width=4)
    draw.ellipse([34, 28, 62, 56], fill=(239, 68, 68, 255))
    draw.text((78, 24), "ANTICIPO EXCLUSIVO | CASO REAL", font=font_sub, fill=(255, 255, 255, 255))
    draw.text((34, 72), "A CONTINUACIÓN...", font=font_title, fill=(255, 230, 0, 255))
    img.save(output_png)
    print(f"[Editor] Teaser pill generated: {output_png}")

def download_video_slice(video_url, start_sec, duration_sec, output_mp4):
    """
    Downloads high-quality video segment using yt-dlp with PO Token provider on Linux or tv,android on Windows.
    """
    start_sec = max(0.0, float(start_sec))
    duration_sec = max(30.0, float(duration_sec))
    end_sec = start_sec + duration_sec
    time_range = f"*{start_sec:.1f}-{end_sec:.1f}"
    print(f"[Editor] Downloading video section {time_range} from {video_url}...")
    
    extra_args = []
    if os.path.exists("cookies.txt"):
        extra_args.extend(["--cookies", "cookies.txt"])
    if os.name != "nt":
        extra_args.extend([
            "--extractor-args", "youtube:player_client=mweb,tv,web",
            "--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416"
        ])
    else:
        extra_args.extend(["--extractor-args", "youtube:player_client=tv,android,web"])
    
    # Method 1: Try direct section download
    ytdlp_bin = shutil.which("yt-dlp") or "yt-dlp"
    cmd = [
        ytdlp_bin,
        "-v",
        "--remote-components", "ejs:github",
        "--download-sections", time_range,
        "--no-check-certificates",
    ] + extra_args + [
        "-f", "18/best[height<=1080]/bestvideo[height<=1080]+bestaudio/best",
        "--merge-output-format", "mp4",
        "--force-overwrites",
        "-o", output_mp4,
        video_url
    ]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0 and os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 500000 and check_has_audio(output_mp4):
            print(f"[Editor] Video section downloaded directly with audio: {output_mp4} ({os.path.getsize(output_mp4)/(1024*1024):.2f} MB)")
            return output_mp4
        else:
            print(f"[Editor] Section download incomplete or missing audio. Moving to robust stream download...")
    except Exception as e:
        print(f"[Editor] Section download notice: {e}")

    # Method 2: Fallback - download whole video and slice precisely with ffmpeg
    print(f"[Editor] Downloading video stream to cut precise slice...")
    full_temp = output_mp4 + ".full.mp4"
    cmd_full = [
        ytdlp_bin,
        "-v",
        "--remote-components", "ejs:github",
        "--no-check-certificates",
    ] + extra_args + [
        "-f", "18/best[height<=1080]/bestvideo[height<=1080]+bestaudio/best",
        "--merge-output-format", "mp4",
        "--force-overwrites",
        "-o", full_temp,
        video_url
    ]
    
    proc_full = subprocess.run(cmd_full, capture_output=True, text=True)
    if proc_full.returncode != 0:
        print(f"[Editor] Notice on stream: {proc_full.stderr[:300]}")
        print(f"[Editor] Trying secondary fallback with ios/android clients...")
        cmd_fallback = [
            ytdlp_bin,
            "--no-check-certificates",
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player_client=android,ios,tv",
            "-f", "18/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "--force-overwrites",
        ]
        if os.path.exists("cookies.txt"):
            cmd_fallback.extend(["--cookies", "cookies.txt"])
        cmd_fallback.extend(["-o", full_temp, video_url])
        
        proc_fb = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if proc_fb.returncode != 0:
            print(f"[Editor] Fallback STDERR:\n{proc_fb.stderr}")
            raise RuntimeError(f"yt-dlp failed completely:\n{proc_full.stderr}\n{proc_fb.stderr}")
        else:
            print(f"[Editor] Downloaded successfully via client fallback!")
    print(f"[Editor] Cutting slice from {start_sec:.1f}s for {duration_sec:.1f}s...")
    cmd_cut = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", full_temp,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
        output_mp4
    ]
    subprocess.run(cmd_cut, check=True)
    if os.path.exists(full_temp):
        os.remove(full_temp)
        
    print(f"[Editor] Video segment cut successfully: {output_mp4}")
    return output_mp4

def render_short_vertical(raw_clip, header_png, narration_wav, ass_file, fonts_dir, output_mp4):
    """
    Renders 9:16 vertical Short using unified Expediente Policial visual composition:
    - 1080x1920 canvas
    - Motion-blurred scaled background (boxblur=10:2)
    - Centered crisp 1080x608 action video
    - 2px red frame border (0xE52521)
    - Top header pill at y=320
    - Safe-zone ASS subtitles (MarginV=320)
    - Guaranteed audible Spanish neural voiceover with dynamic bodycam ducking:
      - Uses asplit=2 so narration pad is never consumed/dropped
      - Enforces stereo fltp 48kHz alignment on all audio streams
      - Uses amix with dropout_transition=0:normalize=0 to prevent volume halving
    """
    print("[Editor] Starting master FFmpeg render pipeline...")
    
    ass_escaped = ass_file.replace("\\", "/").replace(":", "\\:")
    fonts_escaped = fonts_dir.replace("\\", "/").replace(":", "\\:")
    
    has_audio = check_has_audio(raw_clip)
    
    # Video composition chains
    v_chains = [
        "[0:v]split[bg_in][fg_in]",
        "[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,scale=1080:1920:flags=lanczos[bg]",
        "[fg_in]scale=1080:608[fg]",
        "[bg][fg]overlay=0:656[vbase]",
        "[vbase]drawbox=x=0:y=654:w=1080:h=612:color=0xE52521:t=2[vframe]",
        "[vframe][1:v]overlay=40:320[vhead]",
        f"[vhead]ass='{ass_escaped}':fontsdir='{fonts_escaped}'[vout]"
    ]
    
    # Audio mixing chains
    if has_audio:
        a_chains = [
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=0.35[bg_pre]",
            "[2:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asplit=2[sc_in][narr_main]",
            "[bg_pre][sc_in]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=250[bg_ducked]",
            "[narr_main]volume=1.80[narr_loud]",
            "[bg_ducked][narr_loud]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        ]
    else:
        a_chains = [
            "[2:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=1.80[aout]"
        ]
        
    filter_complex = ";".join(v_chains + a_chains)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_clip,
        "-i", header_png,
        "-i", narration_wav,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_mp4
    ]
    
    subprocess.run(cmd, check=True)
    size_mb = os.path.getsize(output_mp4) / (1024 * 1024)
    print(f"[Editor] Render complete! Saved to {output_mp4} ({size_mb:.2f} MB)")
    return output_mp4

def render_teaser_and_concat(raw_clip, teaser_start, teaser_duration, teaser_pill_png, main_mp4, output_mp4, work_dir):
    """
    Renders Cold Open Teaser with 'A CONTINUACIÓN...' and joins it seamlessly before the main video.
    Strictly preserves audio format, sample rate (48000Hz), and channels (stereo) across concat.
    """
    teaser_segment = os.path.join(work_dir, "teaser_segment.mp4")
    has_audio = check_has_audio(raw_clip)
    
    v_chains = [
        "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,scale=1080:1920:flags=lanczos[bg]",
        "[0:v]scale=1080:608[fg]",
        "[bg][fg]overlay=0:656[vbase]",
        "[vbase]drawbox=x=0:y=654:w=1080:h=612:color=0xE52521:t=2[vframe]",
        "[vframe][1:v]overlay=40:320[vout]"
    ]
    
    if has_audio:
        a_chains = [
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=1.0[aout]"
        ]
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(teaser_start),
            "-t", str(teaser_duration),
            "-i", raw_clip,
            "-i", teaser_pill_png,
            "-filter_complex", ";".join(v_chains + a_chains),
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
            teaser_segment
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(teaser_start),
            "-t", str(teaser_duration),
            "-i", raw_clip,
            "-i", teaser_pill_png,
            "-f", "lavfi", "-t", str(teaser_duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex", ";".join(v_chains),
            "-map", "[vout]",
            "-map", "2:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
            teaser_segment
        ]
        
    subprocess.run(cmd, check=True)
    
    concat_txt = os.path.join(work_dir, "concat_final.txt")
    abs_teaser = os.path.abspath(teaser_segment).replace("\\", "/")
    abs_main = os.path.abspath(main_mp4).replace("\\", "/")
    with open(concat_txt, "w", encoding="utf-8") as f:
        f.write(f"file '{abs_teaser}'\n")
        f.write(f"file '{abs_main}'\n")
        
    cmd_cat = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", "-movflags", "+faststart", output_mp4]
    subprocess.run(cmd_cat, check=True)
    size_mb = os.path.getsize(output_mp4) / (1024 * 1024)
    print(f"[Editor] Master Short with Teaser generated: {output_mp4} ({size_mb:.2f} MB)")
    
    # Automated safety audit on final audio output
    verify_voice_and_audio(output_mp4)
    return output_mp4
