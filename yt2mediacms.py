#!/usr/bin/env python3
"""
YouTube to MediaCMS Sync Script

This script supports several modes:

1. Channel Sync:
   • --mode full: Download (or re-download) all videos from the YouTube channel.
     In full sync the oldest video is processed first (using --playlist-reverse).
   • --mode new: Use the YouTube API to determine which videos are new and download only those.
2. Update Channel Metadata Only:
   • --update-channel [CHANNEL_NAME]: Update only the MediaCMS channel metadata using the YouTube API.
     If a channel name is provided, only that channel (as defined in config) is updated.
     If omitted, metadata for all channels is updated.
3. Video IDs Mode:
   • --video-ids: Provide a list of YouTube video IDs to download and upload.
      In this mode, you must specify the target MediaCMS username with --mediacms-username.
      The script will search your config for a channel whose token (mediacms_token) corresponds to that username.
      
Additional options:
   • --delay: Delay (in seconds) between uploads (default: 5 seconds).
   • --keep-files: If provided, downloaded files will not be removed after upload.
   • --mediacms-url: Override the global MediaCMS URL from config.
   • --youtube-channel: (For channel sync modes) If provided, only operate on the channel (as defined in config "name") that matches.

⚠️ IMPORTANT: This script is for syncing your own channel(s) only.
Do not use it to copy copyrighted content.
"""

import os
import sys
import json
import time
import argparse
import logging
import requests
import xml.etree.ElementTree as ET
from subprocess import Popen, PIPE, STDOUT

import googleapiclient.discovery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('yt2mediacms')

# Default output directory for downloads
OUTPUT_DIR = "./youtube_downloads"
# Config file name
CONFIG_FILE = "config.json"

def load_config(config_file=CONFIG_FILE):
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    else:
        logger.error(f"Config file {config_file} not found.")
        sys.exit(1)


def get_mediacms_username(mediacms_url, token):
    """
    Fetch the MediaCMS username via the /api/v1/whoami endpoint.
    The returned JSON includes a 'username' field.
    """
    whoami_url = f"{mediacms_url.rstrip('/')}/api/v1/whoami"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(whoami_url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            username = data.get("username")
            logger.info(f"Retrieved MediaCMS username: {username}")
            return username
        else:
            logger.error(f"Failed to get MediaCMS username: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exception while fetching MediaCMS username: {e}")
        return None


def get_latest_mediacms_video_info(mediacms_url, token):
    """
    Retrieves the latest video info from MediaCMS for the authenticated user.
    The username is determined via the /api/v1/whoami endpoint.
    Returns a tuple: (title, add_date) or (None, None) if none found.
    """
    username = get_mediacms_username(mediacms_url, token)
    if not username:
        logger.error("Could not determine MediaCMS username.")
        return None, None

    api_url = f"{mediacms_url.rstrip('/')}/api/v1/media/?author={username}&show=latest"
    headers = {
        "accept": "application/json",
        "Authorization": f"Token {token}"
    }
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        results = data.get("results")
        if results and len(results) > 0:
            video = results[0]
            return video.get("title"), video.get("add_date")
        else:
            logger.info(f"No MediaCMS videos found for user {username}")
    except Exception as e:
        logger.error(f"Error retrieving MediaCMS video info for user {username}: {e}")
    return None, None


def extract_channel_id(yt_channel_url):
    if "youtube.com/channel/" in yt_channel_url:
        parts = yt_channel_url.rstrip("/").split("/channel/")
        if len(parts) == 2:
            return parts[1]
    return yt_channel_url.rstrip("/").split("/")[-1]


def fetch_videos_with_api(channel_id, api_key, published_after=None, max_results=50):
    """
    Get videos using YouTube API including both regular videos and shorts.
    Returns a list of dictionaries with video details.
    """
    logger.info(f"Fetching videos via YouTube API for channel: {channel_id}")
    
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
        
        # Prepare search parameters
        search_params = {
            "part": "snippet",
            "channelId": channel_id,
            "order": "date",
            "maxResults": max_results,
            "type": "video"
        }
        
        # Add publishedAfter if available
        if published_after:
            search_params["publishedAfter"] = published_after
            logger.info(f"Only fetching videos published after: {published_after}")
        
        request = youtube.search().list(**search_params)
        response = request.execute()
        
        # Log response info for debugging
        logger.debug(f"API response has {len(response.get('items', []))} items")
        
        entries = []
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            entries.append({
                "title": snippet.get("title", ""),
                "video_id": item.get("id", {}).get("videoId", ""),
                "published": snippet.get("publishedAt", "")
            })
        
        logger.info(f"Found {len(entries)} videos (including shorts) using YouTube API")
        return entries
    except Exception as e:
        logger.error(f"Error fetching videos from YouTube API: {e}")
        return []


def download_youtube_videos(urls, output_dir=OUTPUT_DIR, since_date=None):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")

    cmd = [
        "yt-dlp",
        "--ignore-errors",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--postprocessor-args", "-c copy",
        "--write-info-json",
        "--write-thumbnail",
        "--restrict-filenames",
        "--progress",
        "--no-colors",
        "-o", f"{output_dir}/%(upload_date)s-%(title)s-%(id)s.%(ext)s"
    ]
    if since_date:
        cmd.extend(["--dateafter", since_date])
    # When a channel URL is provided (not a list), use --playlist-reverse to download oldest first.
    if isinstance(urls, list):
        cmd.extend(urls)
    else:
        cmd.extend(["--playlist-reverse", urls])
    logger.info(f"Running yt-dlp command: {' '.join(cmd)}")

    process = Popen(cmd, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, universal_newlines=True)

    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        if line:
            if "[download]" in line or "[ExtractAudio]" in line or "[ffmpeg]" in line:
                if "ETA" in line or "Destination" in line or "100%" in line:
                    logger.info(line)
            elif "ERROR:" in line:
                logger.error(line)
            else:
                logger.debug(line)

    process.stdout.close()
    return_code = process.wait()
    if return_code != 0:
        logger.error(f"yt-dlp exited with code {return_code}")

    video_files = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.endswith('.mp4')]
    video_files.sort()  # Assumes filename starts with YYYYMMDD so that sorting is oldest first.
    logger.info(f"Downloaded {len(video_files)} videos")
    return video_files


def get_video_metadata(json_file):
    """Extract relevant metadata from yt-dlp JSON file."""
    try:
        with open(json_file, "r") as f:
            data = json.load(f)

        upload_date = data.get("upload_date", "")
        if upload_date and len(upload_date) == 8:
            formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        else:
            formatted_date = ""

        metadata = {
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "upload_date": formatted_date,
            "original_upload_date": upload_date,
            "duration": data.get("duration", 0),
            "view_count": data.get("view_count", 0)
        }

        logger.debug(f"Extracted metadata for video: {metadata['title']}")
        return metadata
    except Exception as e:
        logger.error(f"Error reading metadata from {json_file}: {e}")
        return {}

def upload_to_mediacms(video_file, mediacms_url, token, metadata=None, cleanup=True):
    """Upload a video to MediaCMS instance and set the original publish date."""
    upload_url = f"{mediacms_url.rstrip('/')}/api/v1/media/"
    headers = {"Authorization": f"Token {token}"}

    if metadata is None:
        metadata = {}

    if 'title' not in metadata:
        metadata['title'] = os.path.basename(video_file).split('.')[0]

    file_size = os.path.getsize(video_file)
    file_size_mb = file_size / (1024 * 1024)
    file_size_human = f"{file_size_mb:.2f} MB"

    # Calculate timeout based on file size
    timeout = min(30 + file_size_mb, 3600)
    logger.info(f"Uploading {metadata['title']} ({file_size_human}) to MediaCMS (timeout: {timeout:.0f}s)...")

    # Prepare data for upload
    data = {
        'title': metadata.get('title', ''),
        'description': metadata.get('description', ''),
    }

    # Add tags if available
    if metadata.get('tags'):
        data['tags'] = ','.join(metadata.get('tags', []))

    # Set publication date if available
    if metadata.get('upload_date'):
        data['publication_date'] = metadata['upload_date']

    try:
        # Open files for upload
        with open(video_file, 'rb') as f:
            files = {'media_file': (os.path.basename(video_file), f, 'video/mp4')}
            
            # Include thumbnail if available
            thumbnail_path = video_file.rsplit('.', 1)[0] + '.jpg'
            thumbnail_file = None
            if os.path.exists(thumbnail_path):
                logger.info(f"Including thumbnail: {thumbnail_path}")
                thumbnail_file = open(thumbnail_path, 'rb')
                files['thumbnail'] = thumbnail_file

            logger.info(f"Starting upload to {upload_url}...")
            start_time = time.time()
            
            # Regular upload with multipart/form-data
            response = requests.post(
                upload_url, 
                headers=headers, 
                data=data, 
                files=files, 
                timeout=timeout
            )
            
            # Close thumbnail if opened
            if thumbnail_file:
                thumbnail_file.close()
                
            elapsed = time.time() - start_time
            upload_speed_mb = file_size_mb / elapsed if elapsed > 0 else 0
            logger.info(f"Upload completed in {elapsed:.1f} seconds ({upload_speed_mb:.2f} MB/s)")
                
    except Exception as e:
        logger.error(f"Exception during upload: {e}")
        return False

    if response.status_code in (200, 201):
        logger.info(f"Successfully uploaded {metadata['title']}")

        if cleanup:
            clean_up_files(video_file)

        return True
    else:
        logger.error(f"Failed to upload {metadata['title']}: {response.status_code}")
        logger.error(response.text)
        return False

def clean_up_files(video_file):
    """Remove the video file and associated metadata files."""
    try:
        os.remove(video_file)
        logger.info(f"Removed video file: {video_file}")

        json_file = video_file.rsplit('.', 1)[0] + '.info.json'
        if os.path.exists(json_file):
            os.remove(json_file)
            logger.info(f"Removed metadata file: {json_file}")

        thumbnail_file = video_file.rsplit('.', 1)[0] + '.jpg'
        if os.path.exists(thumbnail_file):
            os.remove(thumbnail_file)
            logger.info(f"Removed thumbnail file: {thumbnail_file}")

    except Exception as e:
        logger.error(f"Error during file cleanup: {e}")


def get_channel_info_youtube_api(channel_id, api_key):
    logger.info(f"Fetching channel information via YouTube API: {channel_id}")

    if not channel_id:
        logger.error("Channel ID is None. Cannot fetch channel information.")
        return None

    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    try:
        request = youtube.channels().list(part="snippet", id=channel_id)
        response = request.execute()

        if "items" not in response or not response["items"]:
            logger.error("No channel information found.")
            return None

        item = response["items"][0]
        snippet = item["snippet"]
        channel_data = {
            'channel_id': item['id'],
            'channel_name': snippet['title'],
            'channel_description': snippet['description'],
            'channel_image_url': snippet['thumbnails']['default']['url'],
            'channel_url': f"https://www.youtube.com/channel/{item['id']}"
        }

        logger.debug(f"Retrieved channel data: {channel_data}")
        logger.info(f"Successfully retrieved channel info for: {channel_data['channel_name']}")
        return channel_data

    except Exception as e:
        logger.error(f"Exception while fetching channel info: {str(e)}")
        return None


def update_mediacms_channel(mediacms_url, token, channel_info):
    """
    Update the MediaCMS channel (user profile) using a POST request.
    This function sends a multipart/form-data request with:
      - a "name" field (set to the YouTube channel's name),
      - a "description" field, and
      - a "logo" field using the image fetched from the YouTube channel metadata.
    """
    username = get_mediacms_username(mediacms_url, token)
    if not username:
        logger.error("Could not determine MediaCMS username for update.")
        return False

    logger.info("Updating MediaCMS channel with YouTube channel information...")
    update_url = f"{mediacms_url.rstrip('/')}/api/v1/users/{username}"

    headers = {
        "Authorization": f"Token {token}",
        "accept": "application/json"
    }

    description_value = channel_info.get("channel_description", "")

    # Prepare multipart fields
    files = {
        "name": (None, channel_info.get("channel_name", "")),
        "description": (None, description_value)
    }

    # Fetch the logo image from YouTube metadata
    logo_url = channel_info.get("channel_image_url", "")
    if logo_url:
        try:
            logo_response = requests.get(logo_url, timeout=30)
            if logo_response.status_code == 200:
                logo_content = logo_response.content
                logo_filename = "logo.jpg"  # Adjust extension if needed
                logo_mime = logo_response.headers.get("Content-Type", "image/jpeg")
                logger.info("Fetched logo image from YouTube metadata.")
                files["logo"] = (logo_filename, logo_content, logo_mime)
            else:
                logger.warning(f"Failed to fetch logo from {logo_url}: {logo_response.status_code}")
        except Exception as e:
            logger.error(f"Exception fetching logo: {e}")

    logger.debug(f"Requesting URL: {update_url} with headers: {headers} and files: {list(files.keys())}")

    try:
        response = requests.post(
            update_url,
            headers=headers,
            files=files,
            timeout=30
        )

        if 'logo' in files and hasattr(files['logo'][1], 'close'):
            files['logo'][1].close()

        if response.status_code in (200, 201):
            logger.info("Successfully updated MediaCMS channel with YouTube channel information")
            return True
        else:
            logger.error(f"Failed to update MediaCMS channel: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.Timeout:
        logger.error("Timeout while connecting to MediaCMS API")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to MediaCMS API: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating channel: {e}")
        return False


def update_channel_metadata(channel, mediacms_url, youtube_api_key):
    """Update channel metadata using YouTube API data"""
    yt_channel_url = channel.get("url")
    token = channel.get("mediacms_token")
    channel_name = channel.get("name", "Unknown Channel")
    
    if not yt_channel_url or not token:
        logger.error(f"Channel configuration missing 'url' or 'mediacms_token' for {channel_name}.")
        return False
    
    logger.info(f"Updating metadata for channel {channel_name}")
    channel_id = extract_channel_id(yt_channel_url)
    
    # Log the channel ID for debugging
    logger.info(f"Extracted channel ID: {channel_id}")
    
    channel_info = get_channel_info_youtube_api(channel_id, youtube_api_key)
    if channel_info:
        logger.info(f"Successfully fetched info for {channel_info.get('channel_name', 'Unknown')} channel")
        success = update_mediacms_channel(mediacms_url, token, channel_info)
        if success:
            logger.info(f"Successfully updated MediaCMS channel metadata for {channel_name}")
            return True
        else:
            logger.error(f"Failed to update MediaCMS channel metadata for {channel_name}")
            return False
    else:
        logger.error(f"Could not fetch channel info for {channel_name}")
        return False


def sync_channel_new(channel, mediacms_url, delay, keep_files, youtube_api_key):
    yt_channel_url = channel.get("url")
    token = channel.get("mediacms_token")
    channel_id = extract_channel_id(yt_channel_url)
    channel_name = channel.get("name", "Unknown Channel")
    if not yt_channel_url or not token:
        logger.error("Channel configuration missing 'url' or 'mediacms_token'.")
        return

    logger.info(f"Syncing new videos for channel {channel_name} (ID: {channel_id})")

    # Get the latest video info from MediaCMS (just like in the original sync_channel.py)
    last_title, last_date = get_latest_mediacms_video_info(mediacms_url, token)
    if last_title is not None:
        logger.info(f"Latest MediaCMS video title: {last_title}")
        if last_date:
            logger.info(f"Latest MediaCMS video date: {last_date}")
    else:
        logger.info("No previous MediaCMS video found; will fetch recent videos only.")

    # Use last_date as the threshold for the YouTube API (just like in the original sync_channel.py)
    # If no date is available, use a recent date to avoid downloading the entire channel history
    published_after = last_date if last_date else "2020-01-01T00:00:00Z"
    
    # Get videos from YouTube API that were published after the last_date
    videos = fetch_videos_with_api(channel_id, youtube_api_key, published_after)

    if not videos:
        logger.info(f"No new videos found for channel {channel_name} since {published_after}.")
        return

    logger.info(f"Found {len(videos)} new videos published after {published_after}")
    
    # Extract video IDs from the YouTube API response
    new_video_ids = []
    for video in videos:
        new_video_ids.append(video["video_id"])
    
    logger.info(f"Processing {len(new_video_ids)} videos from YouTube API")
    
    # Sort video IDs chronologically (oldest first) for upload
    # This matches what the original sync_channel.py did
    new_video_ids.reverse()
    logger.info(f"New video IDs to sync: {new_video_ids}")
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in new_video_ids]
    video_files = download_youtube_videos(video_urls, OUTPUT_DIR)
    if not video_files:
        logger.warning("No videos downloaded.")
        return

    for video_file in video_files:
        json_file = video_file.rsplit(".", 1)[0] + ".info.json"
        metadata = get_video_metadata(json_file) if os.path.exists(json_file) else {}
        upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)


def sync_channel_full(channel, mediacms_url, delay, keep_files):
    yt_channel_url = channel.get("url")
    token = channel.get("mediacms_token")
    channel_name = channel.get("name", "Unknown Channel")
    if not yt_channel_url or not token:
        logger.error("Channel configuration missing 'url' or 'mediacms_token'.")
        return

    logger.info(f"Performing full sync for channel {channel_name} ({yt_channel_url})")
    
    # For full sync, we use the channel URL and --playlist-reverse to download the oldest video first.
    video_files = download_youtube_videos(yt_channel_url, OUTPUT_DIR)
    if not video_files:
        logger.warning("No videos downloaded in full mode.")
        return

    for video_file in video_files:
        json_file = video_file.rsplit(".", 1)[0] + ".info.json"
        metadata = get_video_metadata(json_file) if os.path.exists(json_file) else {}
        upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)


def sync_video_ids(video_ids, mediacms_url, token, delay, keep_files):
    logger.info(f"Syncing video IDs: {video_ids}")
    username = get_mediacms_username(mediacms_url, token)
    if username:
        logger.info(f"Target MediaCMS user: {username}")
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    video_files = download_youtube_videos(video_urls, OUTPUT_DIR)
    if not video_files:
        logger.warning("No videos downloaded in video-ids mode.")
        return
    for video_file in video_files:
        json_file = video_file.rsplit(".", 1)[0] + ".info.json"
        metadata = get_video_metadata(json_file) if os.path.exists(json_file) else {}
        upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)


def find_token_for_username(channels, mediacms_url, target_username):
    """
    Iterates over channels in config and returns the mediacms_token
    for the first channel whose whoami matches target_username.
    """
    for channel in channels:
        token = channel.get("mediacms_token")
        if token:
            username = get_mediacms_username(mediacms_url, token)
            if username and username.lower() == target_username.lower():
                return token
    return None


def main():
    parser = argparse.ArgumentParser(description="Sync YouTube channel(s) to MediaCMS")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--video-ids", nargs='+', help="List of YouTube video IDs to download and upload")
    group.add_argument("--update-channel", nargs="?", const=True, default=False,
                       help="Update MediaCMS channel metadata. Optionally specify a channel name (as defined in config) to update only that channel. If omitted, updates all channels.")

    parser.add_argument("--mode", choices=["new", "full"], default="new",
                        help="For channel sync: 'new' uses YouTube API (default), 'full' downloads all videos")
    parser.add_argument("--config", default=CONFIG_FILE, help="Path to configuration JSON file")
    parser.add_argument("--mediacms-url", help="Override MediaCMS URL from config")
    parser.add_argument("--delay", type=int, default=5, help="Delay (in seconds) between uploads")
    parser.add_argument("--keep-files", action="store_true", help="Keep downloaded files after upload")
    # For video IDs mode, require --mediacms-username instead of --mediacms-token
    parser.add_argument("--mediacms-username", help="Target MediaCMS username for video-ids mode")
    parser.add_argument("--youtube-channel", help="Operate only on the channel with this name (as defined in config 'name')")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--log-file", help="Log to specified file in addition to console")
    
    # Show help if no arguments are provided
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {args.log_file}")

    config = load_config(args.config)
    mediacms_url = args.mediacms_url if args.mediacms_url else config.get("mediacms_url")
    if not mediacms_url:
        logger.error("MediaCMS URL must be provided via config or command line.")
        sys.exit(1)

    youtube_config = config.get("youtube", {})
    channels = youtube_config.get("channels", [])

    # If --youtube-channel is provided (and we're not in update-channel mode with argument), filter channels.
    if args.youtube_channel and not args.update_channel:
        channels = [c for c in channels if c.get("name", "").lower() == args.youtube_channel.lower()]
        if not channels:
            logger.error(f"No channel with name '{args.youtube_channel}' found in configuration.")
            sys.exit(1)

    # Video IDs mode
    if args.video_ids:
        if not args.mediacms_username:
            logger.error("For --video-ids mode, you must specify --mediacms-username.")
            sys.exit(1)
        token = find_token_for_username(channels, mediacms_url, args.mediacms_username)
        if not token:
            logger.error(f"No channel in config with MediaCMS username '{args.mediacms_username}' was found.")
            sys.exit(1)
        sync_video_ids(args.video_ids, mediacms_url, token, args.delay, args.keep_files)
        sys.exit(0)

    # Update channel metadata only mode
    if args.update_channel:
        if isinstance(args.update_channel, str):
            channels = [c for c in channels if c.get("name", "").lower() == args.update_channel.lower()]
            if not channels:
                logger.error(f"No channel with name '{args.update_channel}' found in configuration.")
                sys.exit(1)
        if not channels:
            logger.error("No channels defined in configuration for update-channel mode.")
            sys.exit(1)
        youtube_api_key = youtube_config.get("api_key")
        if not youtube_api_key:
            logger.error("YouTube API key is required for updating channel metadata (set in config['youtube']['api_key']).")
            sys.exit(1)
        for channel in channels:
            update_channel_metadata(channel, mediacms_url, youtube_api_key)
        sys.exit(0)

    # Before running sync modes, update channel metadata if API key is available
    if not args.update_channel:  # Don't do this if we're already in update_channel mode
        youtube_api_key = youtube_config.get("api_key")
        if youtube_api_key:
            logger.info("Found YouTube API key in config, will update channel metadata before syncing videos")
            for channel in channels:
                update_channel_metadata(channel, mediacms_url, youtube_api_key)
        else:
            logger.warning("No YouTube API key found in config, channel metadata will not be updated")

    # Default: channel sync mode.
    if not channels:
        logger.error("No channels defined in configuration.")
        sys.exit(1)
    logger.info(f"Running in {args.mode} mode for {len(channels)} channel(s).")
    for channel in channels:
        if args.mode == "new":
            sync_channel_new(channel, mediacms_url, args.delay, args.keep_files, youtube_config.get("api_key"))
        elif args.mode == "full":
            sync_channel_full(channel, mediacms_url, args.delay, args.keep_files)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
