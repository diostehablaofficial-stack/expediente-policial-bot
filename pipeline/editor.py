import os
import subprocess
import json
import sys
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
    end_sec = start_sec + duration_sec
    time_range = f"*{start_sec:.1f}-{end_sec:.1f}"
    print(f"[Editor] Downloading video section {time_range} from {video_url}...")
    
    extra_args = []
    if os.name != "nt":
        extra_args = ["--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416"]
    else:
        extra_args = ["--extractor-args", "youtube:player_client=tv,android"]
    
    # Method 1: Try direct section download
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-v",
        "--download-sections", time_range,
        "--no-check-certificates",
    ] + extra_args + [
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best/18",
        "--merge-output-format", "mp4",
        "--force-overwrites",
        "-o", output_mp4
    ]
    if os.path.exists("cookies.txt"):
        cmd.extend(["--cookies", "cookies.txt"])
    cmd.append(video_url)
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0 and os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 500000:
            print(f"[Editor] Video section downloaded directly: {output_mp4} ({os.path.getsize(output_mp4)/(1024*1024):.2f} MB)")
            return output_mp4
        else:
            print(f"[Editor] Section download notice:\n{proc.stderr}")
    except Exception as e:
        print(f"[Editor] Section download notice: {e}")

    # Method 2: Fallback - download whole video and slice precisely with ffmpeg
    print(f"[Editor] Downloading full video stream to cut precise slice...")
    full_temp = output_mp4 + ".full.mp4"
    cmd_full = [
        sys.executable, "-m", "yt_dlp",
        "-v",
        "--no-check-certificates",
    ] + extra_args + [
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best/18",
        "--merge-output-format", "mp4",
        "--force-overwrites",
        "-o", full_temp
    ]
    if os.path.exists("cookies.txt"):
        cmd_full.extend(["--cookies", "cookies.txt"])
    cmd_full.append(video_url)
    
    proc_full = subprocess.run(cmd_full, capture_output=True, text=True)
    if proc_full.returncode != 0:
        print(f"[Editor] Notice on full stream: {proc_full.stderr[:300]}")
        print(f"[Editor] Trying secondary fallback with android client (bypasses datacenter block)...")
        cmd_fallback = [
            sys.executable, "-m", "yt_dlp",
            "--no-check-certificates",
            "--extractor-args", "youtube:player_client=android",
            "-f", "best[height<=1080]/18/best",
            "--merge-output-format", "mp4",
            "--force-overwrites",
            "-o", full_temp,
            video_url
        ]
        proc_fb = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if proc_fb.returncode != 0:
            print(f"[Editor] Fallback STDERR:\n{proc_fb.stderr}")
            raise RuntimeError(f"yt-dlp failed completely:\n{proc_full.stderr}\n{proc_fb.stderr}")
        else:
            print(f"[Editor] Downloaded successfully via android client fallback!")
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
    - Safe-zone ASS subtitles (MarginV=390)
    - Audio ducking & mixing of bodycam and Spanish neural narration
    """
    print("[Editor] Starting master FFmpeg render pipeline...")
    
    # Escape path for FFmpeg filter if needed
    ass_escaped = ass_file.replace("\\", "/").replace(":", "\\:")
    fonts_escaped = fonts_dir.replace("\\", "/").replace(":", "\\:")
    
    filter_complex = (
        "[0:v]split[bg_in][fg_in];"
        "[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,scale=1080:1920:flags=lanczos[bg];"
        "[fg_in]scale=1080:608[fg];"
        "[bg][fg]overlay=0:656[vbase];"
        "[vbase]drawbox=x=0:y=654:w=1080:h=612:color=0xE52521:t=2[vframe];"
        "[vframe][1:v]overlay=40:320[vhead];"
        f"[vhead]ass='{ass_escaped}':fontsdir='{fonts_escaped}'[vout];"
        "[0:a]volume=0.60[bg_pre];"
        "[2:a]asplit=2[sc_in][narr_main];"
        "[bg_pre][sc_in]sidechaincompress=threshold=0.025:ratio=14:attack=40:release=400:mix=1[bg_ducked];"
        "[narr_main]volume=1.60[narr_loud];"
        "[bg_ducked][narr_loud]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_clip,
        "-i", header_png,
        "-i", narration_wav,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "320k",
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
    """
    teaser_segment = os.path.join(work_dir, "teaser_segment.mp4")
    filter_complex = (
        "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,scale=1080:1920:flags=lanczos[bg];"
        "[0:v]scale=1080:608[fg];"
        "[bg][fg]overlay=0:656[vbase];"
        "[vbase]drawbox=x=0:y=654:w=1080:h=612:color=0xE52521:t=2[vframe];"
        "[vframe][1:v]overlay=40:320[vout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(teaser_start),
        "-t", str(teaser_duration),
        "-i", raw_clip,
        "-i", teaser_pill_png,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a",
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
    return output_mp4
