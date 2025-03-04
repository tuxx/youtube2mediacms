import subprocess
import json
import requests
from dateutil import parser as date_parser  # pip install python-dateutil

CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def extract_channel_id(yt_channel_str):
    """
    If yt_channel_str is a full URL, extract and return the channel id.
    Otherwise, assume it's already the channel id.
    """
    if yt_channel_str.startswith("http"):
        return yt_channel_str.rstrip("/").split("/")[-1]
    return yt_channel_str

def get_new_videos(yt_channel_id, yt_api_key, published_after):
    """
    Retrieves videos from the YouTube Data API for the given channel that were
    published after the given ISO 8601 timestamp (published_after).
    Returns a list of video dicts with keys from snippet and id.
    """
    api_url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": yt_api_key,
        "channelId": yt_channel_id,
        "part": "snippet,id",
        "order": "date",
        "maxResults": 50,
        "publishedAfter": published_after
    }
    videos = []
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        for item in items:
            if item["id"]["kind"] == "youtube#video":
                videos.append(item)
    except Exception as e:
        print(f"Error retrieving video info from YouTube API for channel {yt_channel_id}: {e}")
    return videos

def get_latest_mediacms_video_info(mediacms_url, token, mc_channel_id):
    """
    Retrieves the latest video info from Mediacms for the given channel.
    Uses the endpoint: {mediacms_url}/api/v1/media/?author={mc_channel_id}&show=latest
    Returns a tuple: (title, add_date)
    """
    api_url = f"{mediacms_url}/api/v1/media/?author={mc_channel_id}&show=latest"
    headers = {
        "accept": "application/json",
        "X-CSRFTOKEN": token
    }
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        results = data.get("results")
        if results and len(results) > 0:
            video = results[0]
            return video.get("title"), video.get("add_date")
        else:
            print(f"No media found for channel {mc_channel_id}")
    except Exception as e:
        print(f"Error retrieving Mediacms video for channel {mc_channel_id}: {e}")
    return None, None

def sync_channel(channel, mediacms_token, mediacms_url, yt_api_key):
    # Use the full URL from config for logging purposes.
    full_yt_channel_url = channel["yt_id"]
    # Extract the channel id for API calls.
    extracted_yt_channel_id = extract_channel_id(full_yt_channel_url)
    mc_channel_id = channel["mediacms_id"]
    channel_name = channel.get("name", full_yt_channel_url)

    print(f"Checking channel {channel_name}...")

    # Retrieve the last video info from Mediacms.
    mediacms_title, mediacms_published = get_latest_mediacms_video_info(mediacms_url, mediacms_token, mc_channel_id)

    # Use mediacms_published as the threshold (if available) or default to a very early date.
    if mediacms_published:
        published_after = mediacms_published  # expecting an ISO 8601 string
    else:
        published_after = "1970-01-01T00:00:00Z"

    new_videos = get_new_videos(extracted_yt_channel_id, yt_api_key, published_after)
    if not new_videos:
        print(f"No new videos for {channel_name}.")
        return

    # Build the list of video IDs for the new videos.
    video_ids = [video["id"]["videoId"] for video in new_videos]

    if video_ids:
        print(f"New videos detected for {channel_name}:")
        for vid in video_ids:
            print("  ", vid)
        cmd = [
            "docker", "run", "--rm",
            "tuxxness/youtube2mediacms:latest",
            "--video-ids"
        ] + video_ids + [
            "--mediacms-url", mediacms_url,
            "--token", mediacms_token
        ]
        print("Running command:", " ".join(cmd))
        subprocess.run(cmd)
    else:
        print(f"No new videos found for {channel_name} after filtering.")

def main():
    config = load_config()

    mediacms_config = config.get("mediacms", {})
    mediacms_token = mediacms_config.get("token")
    mediacms_url = mediacms_config.get("url")
    yt_api_key = config.get("yt_api_key")
    channels = config.get("channels", [])

    for channel in channels:
        sync_channel(channel, mediacms_token, mediacms_url, yt_api_key)

if __name__ == "__main__":
    main()

