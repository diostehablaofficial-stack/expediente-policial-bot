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
            # data can be list of strings or list of dicts
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

    # Method 2: yt-dlp flat playlist
    try:
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-single-json",
            "--playlist-end", "10",
            CHANNEL_URL
        ]
        out = subprocess.check_output(cmd).decode("utf-8", errors="ignore")
        data = json.loads(out)
        for e in data.get("entries", []):
            videos.append({
                "id": e.get("id"),
                "title": e.get("title"),
                "duration": e.get("duration"),
                "url": f"https://www.youtube.com/watch?v={e.get('id')}"
            })
        print(f"[Detector] Found {len(videos)} videos via yt-dlp.")
        return videos
    except Exception as e:
        print(f"[Detector] yt-dlp flat-playlist query failed: {e}")
        return []

def get_video_details(video_url, basic_info=None):
    """
    Retrieves full video details (chapters, full description, duration) via yt-dlp.
    Falls back gracefully if YouTube player challenge fails.
    """
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--skip-download",
        "--no-check-certificates",
        "--extractor-args", "youtube:player_client=android,ios;youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416",
    ]

    if os.path.exists("cookies.txt"):
        cmd.extend(["--cookies", "cookies.txt"])
    cmd.append(video_url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            data["url"] = f"https://www.youtube.com/watch?v={data.get('id', '')}"
            return data

        else:
            print(f"[Detector] yt-dlp dump-json warning/error: {proc.stderr.strip()[:300]}")
    except Exception as e:
        print(f"[Detector] dump-json exception: {e}")
        
    # Graceful fallback: return basic_info augmented with defaults
    print("[Detector] Using fallback video details structure.")
    fallback = basic_info.copy() if basic_info else {}
    fallback["id"] = fallback.get("id") or video_url.split("v=")[-1]
    fallback["title"] = fallback.get("title") or "Intervención Policial de Alto Riesgo"
    fallback["duration"] = fallback.get("duration") or 180
    fallback["chapters"] = []
    fallback["description"] = f"{fallback.get('title')} — Video de archivo policial oficial de dominio público."
    fallback["url"] = video_url
    return fallback

def find_next_candidate(history_file):
    """
    Checks channel videos against processed history and returns the first unprocessed candidate.
    """
    processed = get_processed_ids(history_file)
    print(f"[Detector] Loaded {len(processed)} previously processed cases/videos.")
    
    videos = fetch_channel_videos()
    if not videos:
        print("[Detector] No videos retrieved from channel.")
        return None
        
    for v in videos:
        vid = v["id"]
        # Check if video id or case tag matching video id is in processed set
        if vid in processed:
            continue
        # Also check if any processed key contains this video id
        already_done = any(vid in str(p) for p in processed)
        if already_done:
            continue
            
        print(f"[Detector] Found new candidate video: {v['title']} (ID: {vid})")
        details = get_video_details(v["url"], basic_info=v)
        return details
        
    print("[Detector] All recent videos have already been processed.")
    return None


if __name__ == "__main__":
    hist = os.path.join(os.path.dirname(__file__), "..", "data", "processed_history.json")
    cand = find_next_candidate(hist)
    if cand:
        print("Candidate ready:", cand.get("title"))
    else:
        print("No candidates found.")
