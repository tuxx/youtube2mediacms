import subprocess
import json
import requests
from dateutil import parser as date_parser  # pip install python-dateutil

CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def get_latest_video_info(yt_channel_id, yt_api_key):
    """
    Retrieves the latest video from the YouTube Data API for the given channel.
    Returns a tuple: (video_id, published, title)
    This method returns Shorts as well as regular videos.
    """
    api_url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": yt_api_key,
        "channelId": yt_channel_id,
        "part": "snippet,id",
        "order": "date",
        "maxResults": 1
    }
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if items:
            latest_item = items[0]
            if latest_item["id"]["kind"] == "youtube#video":
                video_id = latest_item["id"]["videoId"]
                published = latest_item["snippet"]["publishedAt"]
                title = latest_item["snippet"]["title"]
                return video_id, published, title
        else:
            print(f"No items found for channel {yt_channel_id}")
    except Exception as e:
        print(f"Error retrieving video info from YouTube API for channel {yt_channel_id}: {e}")
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

def format_since_date(date_str):
    """
    Convert a date string (e.g. "2025-03-02T17:47:12.768543Z") to the YYYYMMDD format.
    If the conversion fails, return a default of "19700101".
    """
    try:
        dt = date_parser.parse(date_str)
        return dt.strftime("%Y%m%d")
    except Exception as e:
        print(f"Error parsing date '{date_str}': {e}")
        return "19700101"

def sync_channel(channel, mediacms_token, mediacms_url, yt_api_key):
    yt_channel_id = channel["yt_id"]
    mc_channel_id = channel["mediacms_id"]
    channel_name = channel.get("name", yt_channel_id)
    
    print(f"Checking channel {channel_name}...")
    
    yt_video_id, yt_published, yt_title = get_latest_video_info(yt_channel_id, yt_api_key)
    if not yt_title:
        print(f"Could not retrieve YouTube info for channel {yt_channel_id}")
        return

    mediacms_title, mediacms_published = get_latest_mediacms_video_info(mediacms_url, mediacms_token, mc_channel_id)
    
    # Compare the latest video titles. If they differ (or if Mediacms has no video), assume a new video is available.
    if mediacms_title != yt_title:
        print(f"New video detected for {channel_name}.")
        # Format the Mediacms add_date as YYYYMMDD; default to "19700101" if no date is available.
        since_arg = format_since_date(mediacms_published) if mediacms_published else "19700101"
        cmd = [
            "docker", "run", "--rm",
            "tuxxness/youtube2mediacms:latest",
            "--channel", yt_channel_id,
            "--mediacms-url", mediacms_url,
            "--token", mediacms_token,
            "--yt-api-key", yt_api_key,
            "--since", since_arg
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

