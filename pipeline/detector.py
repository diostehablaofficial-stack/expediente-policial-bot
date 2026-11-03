import json
import os
import sys
import subprocess
import requests
import xml.etree.ElementTree as ET

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

CHANNEL_URL = "https://www.youtube.com/@PoliceActivity/videos"
CHANNEL_ID = "UCXMYxKMh3prxnM_4kYZuB3g"
RSS_FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"

def get_processed_ids(history_file):
    if not os.path.exists(history_file):
        return set()
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            ids = set()
            for item in data:
                if isinstance(item, str):
                    ids.add(item)
                elif isinstance(item, dict) and "video_id" in item:
                    ids.add(item["video_id"])
            return ids
    except Exception as e:
        print(f"[Detector] Warning reading history: {e}")
        return set()

def fetch_channel_videos():
    """
    Fetches the latest videos using RSS feed, with fallback to yt-dlp flat-playlist.
    """
    videos = []
    
    # Method 1: RSS Feed (Fastest, lightest)
    try:
        print(f"[Detector] Fetching channel RSS feed from {RSS_FEED_URL}...")
        res = requests.get(RSS_FEED_URL, timeout=12)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "yt": "http://www.youtube.com/xml/schemas/2015"
            }
            for entry in root.findall("atom:entry", ns):
                vid = entry.find("yt:videoId", ns).text
                title = entry.find("atom:title", ns).text
                published = entry.find("atom:published", ns).text if entry.find("atom:published", ns) is not None else ""
                videos.append({
                    "id": vid,
                    "title": title,
                    "published": published,
                    "url": f"https://www.youtube.com/watch?v={vid}"
                })
            print(f"[Detector] Found {len(videos)} videos via RSS feed.")
            return videos
    except Exception as e:
        print(f"[Detector] RSS feed query failed: {e}. Falling back to yt-dlp...")

    return fetch_flat_playlist(limit=15)

def fetch_flat_playlist(limit=60):
    """
    Fetches up to `limit` entries using yt-dlp flat-playlist to ensure
    there is always a candidate available even when recent RSS items are already processed.
    """
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-single-json",
            "--playlist-end", str(limit),
            CHANNEL_URL
        ]
        out = subprocess.check_output(cmd).decode("utf-8", errors="ignore")
        data = json.loads(out)
        videos = []
        for e in data.get("entries", []):
            if e.get("id"):
                videos.append({
                    "id": e.get("id"),
                    "title": e.get("title"),
                    "duration": e.get("duration"),
                    "url": f"https://www.youtube.com/watch?v={e.get('id')}"
                })
        print(f"[Detector] Found {len(videos)} videos via yt-dlp flat playlist (depth={limit}).")
        return videos
    except Exception as e:
        print(f"[Detector] yt-dlp flat-playlist query failed: {e}")
        return []

def get_ytdlp_extractor_args():
    """
    Returns optimal extractor args for yt-dlp.
    When on Linux (e.g. GitHub Actions), connects to the local bgutil POT provider on 4416.
    """
    if os.name != "nt":
        return ["--extractor-args", "youtube:player_client=web,mweb,tv;youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416"]
    else:
        return ["--extractor-args", "youtube:player_client=tv,android,web"]

def get_video_details(video_url, basic_info=None):
    """
    Retrieves full video details (chapters, full description, duration) via yt-dlp.
    Validates that the video streams are accessible. Returns None if video is blocked/requires login.
    """
    def run_dump(use_cookies=True):
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--dump-json",
            "--skip-download",
            "--no-check-certificates",
            "--remote-components", "ejs:github",
        ]
        if use_cookies and os.path.exists("cookies.txt"):
            cmd.extend(["--cookies", "cookies.txt"])
        cmd.extend(get_ytdlp_extractor_args())
        cmd.append(video_url)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=35)

    try:
        proc = run_dump(use_cookies=True)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            data["url"] = f"https://www.youtube.com/watch?v={data.get('id', '')}"
            return data
            
        stderr_msg = proc.stderr.strip()
        print(f"[Detector] dump-json notice: {stderr_msg[:250]}")
        
        # If cookies were invalid, remove cookies.txt and retry immediately with PO Token provider
        if os.path.exists("cookies.txt") and any(b in stderr_msg for b in ["no longer valid", "not a bot", "LOGIN_REQUIRED"]):
            print("[Detector] Stale cookies detected. Removing cookies.txt and retrying with PO Token provider...")
            try:
                os.remove("cookies.txt")
            except Exception:
                pass
            proc = run_dump(use_cookies=False)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                data["url"] = f"https://www.youtube.com/watch?v={data.get('id', '')}"
                return data
                
        # Secondary fallback: try client rotation with POT provider
        cmd_fb = [
            sys.executable, "-m", "yt_dlp",
            "--dump-json",
            "--skip-download",
            "--no-check-certificates",
            "--remote-components", "ejs:github",
        ] + get_ytdlp_extractor_args() + [video_url]
        proc_fb = subprocess.run(cmd_fb, capture_output=True, text=True, timeout=35)
        if proc_fb.returncode == 0 and proc_fb.stdout.strip():
            data = json.loads(proc_fb.stdout)
            data["url"] = f"https://www.youtube.com/watch?v={data.get('id', '')}"
            return data
        else:
            print(f"[Detector] Secondary fallback notice: {proc_fb.stderr.strip()[:250]}")

        if "Sign in to confirm you’re not a bot" in stderr_msg or "Sign in to confirm you're not a bot" in stderr_msg or "LOGIN_REQUIRED" in stderr_msg:
            print(f"[Detector] Video {video_url} requires login/bot verification. Skipping.")
            return None
    except Exception as e:
        print(f"[Detector] dump-json exception: {e}")
        
    return None

def find_next_candidate(history_file):
    """
    Checks channel videos against processed history and returns the first unprocessed accessible candidate.
    Guarantees 2 daily uploads: checks newest RSS feed first, and expands to channel backlog if needed.
    """
    processed = get_processed_ids(history_file)
    print(f"[Detector] Loaded {len(processed)} previously processed cases/videos.")
    
    videos = fetch_channel_videos()
    if not videos:
        print("[Detector] No videos retrieved from channel.")
        return None
        
    # Phase 1: Check newest videos from RSS/recent
    for v in videos:
        vid = v["id"]
        if vid in processed or any(vid in str(p) for p in processed):
            continue
            
        print(f"[Detector] Testing candidate video: {v['title']} (ID: {vid})...")
        details = get_video_details(v["url"], basic_info=v)
        if details:
            print(f"[Detector] Valid candidate confirmed: {v['title']} (ID: {vid})")
            return details
        else:
            print(f"[Detector] Candidate {vid} is not immediately accessible in current environment. Checking next...")

    # Phase 2: If all newest entries are processed, expand catalog depth to 60
    # to guarantee a fresh high-impact video is always published twice a day
    print("[Detector] Recent videos already processed. Expanding search into channel backlog (depth=60)...")
    expanded_videos = fetch_flat_playlist(limit=60)
    for v in expanded_videos:
        vid = v["id"]
        if vid in processed or any(vid in str(p) for p in processed):
            continue
            
        print(f"[Detector] Testing catalog candidate: {v['title']} (ID: {vid})...")
        details = get_video_details(v["url"], basic_info=v)
        if details:
            print(f"[Detector] Valid backlog candidate confirmed: {v['title']} (ID: {vid})")
            return details
        else:
            print(f"[Detector] Candidate {vid} is not accessible. Checking next...")
            
    print("[Detector] All scanned candidates have been processed.")
    return None

if __name__ == "__main__":
    hist = os.path.join(os.path.dirname(__file__), "..", "data", "processed_history.json")
    cand = find_next_candidate(hist)
    if cand:
        print("Candidate ready:", cand.get("title"))
    else:
        print("No candidates found.")
