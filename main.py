import os
import sys
import json
import time
import shutil

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from pipeline.detector import find_next_candidate
from pipeline.analyzer import analyze_video
from pipeline.narrator import process_narration
from pipeline.editor import generate_header_card, generate_teaser_pill, download_video_slice, render_short_vertical, render_teaser_and_concat
from pipeline.publisher import publish_case

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORK_DIR = os.path.join(BASE_DIR, "work")
HISTORY_FILE = os.path.join(DATA_DIR, "processed_history.json")

def update_history(history_file, case_info):
    data = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
            
    updated = False
    for i, item in enumerate(data):
        if isinstance(item, dict) and (item.get("case_code") == case_info.get("case_code") or item.get("video_id") == case_info.get("video_id")):
            data[i] = case_info
            updated = True
            break
    if not updated:
        data.append(case_info)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[Main] Updated history saved to {history_file}")

def run_pipeline():
    print("=" * 60)
    print("🚀 EXPEDIENTE POLICIAL - AUTOMATED BOT PIPELINE")
    print("=" * 60)
    
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(FONTS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    
    # 1. Detect candidate
    print("\n[Step 1/5] Detecting latest unprocessed video from @PoliceActivity...")
    candidate = find_next_candidate(HISTORY_FILE)
    if not candidate:
        print("[Main] ✨ No new videos to process. Channel is 100% up to date!")
        return True
        
    print(f"[Main] Selected candidate: {candidate.get('title')} ({candidate.get('id')})")
    
    # 2. Analyze & build metadata
    print("\n[Step 2/5] Analyzing case & generating True Crime Spanish metadata...")
    metadata = analyze_video(candidate, HISTORY_FILE)
    case_code = metadata["case_code"]
    
    # 3. Generate Narration & Subtitles
    print("\n[Step 3/5] Synthesizing Spanish neural voiceover and ASS subtitles...")
    case_work_dir = os.path.join(WORK_DIR, case_code)
    os.makedirs(case_work_dir, exist_ok=True)
    narr_res = process_narration(metadata, case_work_dir)
    ass_file = narr_res["ass_file"]
    narr_wav = narr_res["narration_wav"]
    
    # 4. Download and Edit Short
    print("\n[Step 4/5] Downloading segment and rendering vertical 9:16 Short...")
    header_png = os.path.join(case_work_dir, "header.png")
    generate_header_card(metadata["badge_sub"], metadata["badge_title"], header_png, FONTS_DIR)
    
    raw_clip_mp4 = os.path.join(case_work_dir, "raw_slice.mp4")
    video_url = metadata.get("video_url") or candidate.get("url") or f"https://www.youtube.com/watch?v={candidate['id']}"
    download_video_slice(
        video_url,
        metadata["slice_start"],
        metadata["slice_duration"],
        raw_clip_mp4
    )

    # 4a. Render main vertical story segment with dynamic audio ducking & subtitles
    main_segment_mp4 = os.path.join(case_work_dir, "main_segment.mp4")
    render_short_vertical(
        raw_clip_mp4,
        header_png,
        narr_wav,
        ass_file,
        FONTS_DIR,
        main_segment_mp4
    )

    # 4b. Generate Cold Open Teaser ('A CONTINUACIÓN...') and join at start
    teaser_pill_png = os.path.join(case_work_dir, "teaser_pill.png")
    generate_teaser_pill(teaser_pill_png, FONTS_DIR)
    
    output_mp4 = os.path.join(OUTPUT_DIR, f"{case_code}_Short_Vertical.mp4")
    teaser_start = metadata.get("teaser_start", 25.0)
    teaser_dur = metadata.get("teaser_duration", 3.5)
    render_teaser_and_concat(
        raw_clip_mp4,
        teaser_start,
        teaser_dur,
        teaser_pill_png,
        main_segment_mp4,
        output_mp4,
        case_work_dir
    )

    # Save a local copy to user's Shorts folder if running on local Windows machine
    local_shorts_dir = r"C:\Users\Vanes\Downloads\Expediente Policial\Shorts"
    if os.path.exists(local_shorts_dir):
        try:
            clean_badge = "".join(c for c in metadata.get('badge_title', '') if c.isalnum() or c in (' ', '_')).rstrip()
            local_target = os.path.join(local_shorts_dir, f"{case_code}_{clean_badge.replace(' ', '_')}_Vertical.mp4")
            shutil.copyfile(output_mp4, local_target)
            print(f"[Main] Saved copy to local Shorts folder: {local_target}")
        except Exception as e:
            print(f"[Main] Notice copying to local folder: {e}")
    
    # 5. Upload & Publish
    print("\n[Step 5/5] Uploading and publishing video across platforms...")
    pub_info = publish_case(output_mp4, metadata)
    
    # 6. Update history
    case_record = {
        "case_code": case_code,
        "video_id": candidate["id"],
        "original_title": candidate.get("title"),
        "spanish_title": metadata["spanish_title"],
        "video_url": pub_info.get("video_url"),
        "youtube_url": pub_info.get("youtube_url"),
        "buffer_post_id": pub_info.get("buffer_post_id"),
        "instagram_reel_id": pub_info.get("instagram_reel_id"),
        "instagram_url": pub_info.get("instagram_url"),
        "facebook_video_id": pub_info.get("facebook_video_id"),
        "facebook_url": pub_info.get("facebook_url"),
        "status": "published",
        "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    update_history(HISTORY_FILE, case_record)
    
    # Clean temporary work files to conserve runner disk space
    try:
        shutil.rmtree(case_work_dir, ignore_errors=True)
    except Exception:
        pass
        
    print("\n" + "=" * 60)
    print(f"🎉 SUCCESFULLY CREATED AND PUBLISHED {case_code}!")
    print(f"Title: {metadata['spanish_title']}")
    print(f"Public Asset URL: {pub_info.get('video_url')}")
    if pub_info.get("youtube_url"):
        print(f"YouTube Shorts: {pub_info.get('youtube_url')}")
    if pub_info.get("instagram_url"):
        print(f"Instagram Reel: {pub_info.get('instagram_url')}")
    if pub_info.get("facebook_url"):
        print(f"Facebook Page: {pub_info.get('facebook_url')}")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = run_pipeline()
    if not success:
        sys.exit(1)
