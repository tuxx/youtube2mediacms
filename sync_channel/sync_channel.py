import feedparser
import subprocess
import json
import os
import requests
from dateutil import parser as date_parser 

CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def get_latest_video_info(yt_channel_id):
    """
    Retrieves the latest video from the YouTube channel's RSS feed.
    Returns a tuple: (video_id, published, title)
    """
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={yt_channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.entries:
        latest_entry = feed.entries[0]
        video_id = latest_entry.yt_videoid
        published = latest_entry.published  # e.g. "2023-03-07T15:30:00Z"
        title = latest_entry.title
        return video_id, published, title
    return None, None, None

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
        if response.status_code == 200:
            data = response.json()
            results = data.get("results")
            if results and len(results) > 0:
                video = results[0]
                return video.get("title"), video.get("add_date")
        else:
            print(f"Error querying Mediacms for channel {mc_channel_id}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error retrieving Mediacms video for channel {mc_channel_id}: {e}")
    return None, None

def sync_channel(channel, mediacms_token, mediacms_url, yt_api_key):
    yt_channel_id = channel["yt_id"]
    mc_channel_id = channel["mediacms_id"]
    channel_name = channel.get("name", yt_channel_id)
    
    print(f"Checking channel {channel_name}...")
    
    yt_video_id, yt_published, yt_title = get_latest_video_info(yt_channel_id)
    if not yt_title:
        print(f"Could not retrieve YouTube info for channel {yt_channel_id}")
        return

    mediacms_title, mediacms_published = get_latest_mediacms_video_info(mediacms_url, mediacms_token, mc_channel_id)
    
    # Compare the latest video titles. If they differ (or if Mediacms has no video), assume a new video is available.
    if mediacms_title != yt_title:
        print(f"New video detected for {channel_name}.")
        # Use the Mediacms add_date if available; otherwise, default to a very early date.
        since_arg = mediacms_published if mediacms_published is not None else "1970-01-01T00:00:00Z"
        cmd = [
            "docker", "run", "--rm",
            "tuxxness/youtube2mediacms:latest",
            "--since", since_arg,
            "--yt-channel", yt_channel_id,
            "--mediacms-channel", mc_channel_id,
            "--token", mediacms_token,
            "--mediacms_url", mediacms_url,
            "--yt-api-key", yt_api_key
        ]
        print("Running command:", " ".join(cmd))
        subprocess.run(cmd)
    else:
        print(f"No new video for {channel_name}. Latest video title matches: {yt_title}")

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
