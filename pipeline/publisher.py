import os
import time
import json
import requests
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def upload_to_temp_sh(file_path):
    """
    Fast direct public CDN upload via temp.sh (supports large files, zero auth needed).
    """
    print(f"[Publisher] Uploading {file_path} to temp.sh...")
    with open(file_path, "rb") as f:
        filename = os.path.basename(file_path)
        r = requests.post("https://temp.sh/upload", files={"file": (filename, f)}, timeout=120)
        if r.status_code == 200:
            url = r.text.strip()
            print(f"[Publisher] Upload successful! Public URL: {url}")
            return url
        else:
            raise RuntimeError(f"temp.sh upload failed with status {r.status_code}: {r.text}")

def upload_to_github_release(file_path, tag_name, repo_name, token):
    """
    Creates a GitHub Release and attaches the MP4 asset.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    # 1. Create Release
    rel_url = f"https://api.github.com/repos/{repo_name}/releases"
    payload = {
        "tag_name": tag_name,
        "name": f"Expediente Policial {tag_name}",
        "body": f"Automated generation asset for {tag_name}",
        "draft": False,
        "prerelease": False
    }
    r = requests.post(rel_url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub release creation failed: {r.status_code} - {r.text}")
    rel_data = r.json()
    upload_url_tmpl = rel_data.get("upload_url", "")
    upload_url = upload_url_tmpl.split("{")[0]
    
    # 2. Upload Asset
    filename = os.path.basename(file_path)
    upload_target = f"{upload_url}?name={filename}"
    headers["Content-Type"] = "video/mp4"
    with open(file_path, "rb") as f:
        r_asset = requests.post(upload_target, headers=headers, data=f, timeout=300)
        if r_asset.status_code not in (200, 201):
            raise RuntimeError(f"Asset upload failed: {r_asset.status_code} - {r_asset.text}")
        asset_data = r_asset.json()
        download_url = asset_data.get("browser_download_url")
        print(f"[Publisher] GitHub Release asset uploaded: {download_url}")
        return download_url

def get_public_video_url(file_path, case_code):
    """
    Tries GitHub Release if public repo; falls back to fast direct CDN temp.sh.
    """
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "diostehablaofficial-stack/expediente-policial-bot")
    
    if token and repo:
        try:
            # Check if repo is public
            r = requests.get(f"https://api.github.com/repos/{repo}", headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200 and not r.json().get("private"):
                tag = f"{case_code}_{int(time.time())}"
                return upload_to_github_release(file_path, tag, repo, token)
        except Exception as e:
            print(f"[Publisher] GitHub Release attempt notice: {e}")
            
    # Fallback to high-speed public CDN
    return upload_to_temp_sh(file_path)

def publish_to_buffer_youtube(video_url, title, description, channel_id, token, mode="addToQueue"):
    """
    Publishes / queues YouTube Short via Buffer GraphQL API.
    """
    print(f"[Publisher] Sending video to Buffer GraphQL API (Channel: {channel_id})...")
    endpoint = "https://api.buffer.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    mutation = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
            status
          }
        }
        ... on InvalidInputError {
          message
        }
        ... on UnexpectedError {
          message
        }
        ... on LimitReachedError {
          message
        }
        ... on UnauthorizedError {
          message
        }
      }
    }
    """
    
    # YouTube Short title constraint: max 100 chars
    yt_title = title if len(title) <= 100 else title[:97] + "..."
    
    variables = {
        "input": {
            "channelId": channel_id,
            "mode": mode,
            "schedulingType": "automatic",
            "needsApproval": False,
            "text": description,
            "assets": [
                {
                    "video": {
                        "url": video_url
                    }
                }
            ],
            "metadata": {
                "youtube": {
                    "title": yt_title,
                    "categoryId": "25",
                    "privacy": "public",
                    "madeForKids": False
                }
            }

        }
    }
    
    res = requests.post(endpoint, headers=headers, json={"query": mutation, "variables": variables}, timeout=30)
    data = res.json()
    
    if "errors" in data:
        raise RuntimeError(f"Buffer GraphQL Error: {data['errors']}")
        
    post_result = data.get("data", {}).get("createPost", {})
    if "post" in post_result:
        post_id = post_result["post"]["id"]
        status = post_result["post"]["status"]
        print(f"[Publisher] Buffer Post created successfully! ID: {post_id}, Status: {status}")
        return post_result
    else:
        raise RuntimeError(f"Buffer API Error response: {post_result}")

def publish_to_meta(video_url, caption, access_token, ig_user_id=None, fb_page_id=None):
    """
    Publishes to Instagram Reels and Facebook Page via Meta Graph API.
    """
    results = {}
    # Instagram Reels
    if ig_user_id:
        print(f"[Publisher] Creating Instagram Reel container for user {ig_user_id}...")
        init_url = f"https://graph.facebook.com/v21.0/{ig_user_id}/media"
        params = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token
        }
        r = requests.post(init_url, data=params, timeout=30)
        if r.status_code == 200:
            container_id = r.json().get("id")
            print(f"[Publisher] Instagram container created: {container_id}. Waiting for processing...")
            # Poll status
            for _ in range(20):
                time.sleep(10)
                status_url = f"https://graph.facebook.com/v21.0/{container_id}?fields=status_code&access_token={access_token}"
                s_res = requests.get(status_url).json()
                status = s_res.get("status_code")
                if status == "FINISHED":
                    # Publish
                    pub_url = f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish"
                    p_res = requests.post(pub_url, data={"creation_id": container_id, "access_token": access_token}).json()
                    results["instagram"] = p_res
                    print(f"[Publisher] Instagram Reel published! ID: {p_res.get('id')}")
                    break
                elif status == "ERROR":
                    print(f"[Publisher] Instagram video processing error: {s_res}")
                    break
        else:
            print(f"[Publisher] Instagram upload initiation failed: {r.status_code} - {r.text}")

    # Facebook Page Video
    if fb_page_id:
        print(f"[Publisher] Publishing video to Facebook Page {fb_page_id}...")
        fb_url = f"https://graph.facebook.com/v21.0/{fb_page_id}/videos"
        fb_params = {
            "file_url": video_url,
            "description": caption,
            "access_token": access_token
        }
        r_fb = requests.post(fb_url, data=fb_params, timeout=30)
        results["facebook"] = r_fb.json()
        print(f"[Publisher] Facebook video response: {r_fb.json()}")

    return results

def publish_case(video_file, metadata):
    """
    Main publisher coordinator:
    1. Uploads video to high-speed public CDN / release.
    2. Publishes to YouTube via Buffer.
    3. Publishes to Meta (Instagram/Facebook) if token is configured.
    """
    case_code = metadata.get("case_code", "EXP_CASE")
    title = metadata.get("spanish_title", "Expediente Policial")
    desc = metadata.get("seo_description", "")
    
    # 1. Get public URL
    video_url = get_public_video_url(video_file, case_code)
    
    # 2. Buffer YouTube
    buf_token = os.environ.get("BUFFER_TOKEN")
    buf_channel = os.environ.get("BUFFER_CHANNEL_ID")
    
    if buf_token and buf_channel:
        try:
            publish_to_buffer_youtube(video_url, title, desc, buf_channel, buf_token)
        except Exception as e:
            print(f"[Publisher] Buffer publishing failed: {e}")
            raise
    else:
        print("[Publisher] BUFFER_TOKEN or BUFFER_CHANNEL_ID missing in environment. Skipping YouTube upload.")

    # 3. Meta (Instagram / Facebook)
    meta_token = os.environ.get("META_ACCESS_TOKEN")
    ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID")
    fb_id = os.environ.get("FB_PAGE_ID")
    
    if meta_token and (ig_id or fb_id):
        try:
            publish_to_meta(video_url, desc, meta_token, ig_user_id=ig_id, fb_page_id=fb_id)
        except Exception as e:
            print(f"[Publisher] Meta publishing error: {e}")
    else:
        print("[Publisher] META_ACCESS_TOKEN not configured yet. (Staged for Meta upload when token is provided).")

    return video_url
