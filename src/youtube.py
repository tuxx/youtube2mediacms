import logging
import subprocess
import os
import json
import time
from subprocess import Popen, PIPE, STDOUT
from .constants import OUTPUT_DIR
import googleapiclient.discovery

logger = logging.getLogger('yt2mediacms')

def extract_channel_id(yt_channel_url):
    if "youtube.com/channel/" in yt_channel_url:
        parts = yt_channel_url.rstrip("/").split("/channel/")
        if len(parts) == 2:
            return parts[1]
    return yt_channel_url.rstrip("/").split("/")[-1]

def fetch_videos_with_api(channel_id, api_key, published_after=None, max_results=50, order="date", fetch_all=False):
    """
    Get videos using YouTube API including both regular videos and shorts.
    Returns a list of dictionaries with video details.
    
    Parameters:
    - channel_id: The YouTube channel ID
    - api_key: YouTube API key
    - published_after: Only fetch videos published after this date (ISO 8601 format)
    - max_results: Maximum number of results per request
    - order: Order of results ("date", "title", "viewCount", "rating")
    - fetch_all: If True, fetches all videos by making multiple requests
    
    Returns:
    - List of dictionaries with video details
    """

    logger.info(f"Fetching videos via YouTube API for channel: {channel_id}")
    
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
        
        # Prepare search parameters
        search_params = {
            "part": "snippet",
            "channelId": channel_id,
            "order": order,
            "maxResults": max_results,
            "type": "video"
        }
        
        # Add publishedAfter if available
        if published_after:
            search_params["publishedAfter"] = published_after
            logger.info(f"Only fetching videos published after: {published_after}")
        
        all_entries = []
        next_page_token = None
        total_fetched = 0
        
        # Loop to fetch all pages if fetch_all is True
        while True:
            if next_page_token:
                search_params["pageToken"] = next_page_token
            
            logger.info(f"Making YouTube API request (page token: {next_page_token})")
            request = youtube.search().list(**search_params)
            response = request.execute()
            
            # Log response info for debugging
            items = response.get("items", [])
            logger.info(f"API response has {len(items)} items")
            
            # Process videos from this page
            for item in items:
                snippet = item.get("snippet", {})
                all_entries.append({
                    "title": snippet.get("title", ""),
                    "video_id": item.get("id", {}).get("videoId", ""),
                    "published": snippet.get("publishedAt", "")
                })
            
            total_fetched += len(items)
            
            # Check if there are more pages
            next_page_token = response.get("nextPageToken")
            
            # Break if no more pages or we're not fetching all
            if not next_page_token or not fetch_all:
                break
            
            # Avoid hitting API limits
            time.sleep(1)
        
        logger.info(f"Found {total_fetched} videos (including shorts) using YouTube API")
        
        # Sort by publish date (oldest first)
        all_entries.sort(key=lambda x: x.get("published", ""))
        
        return all_entries
    except Exception as e:
        logger.error(f"Error fetching videos from YouTube API: {e}")
        return []

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

def download_youtube_videos_with_callback(urls, output_dir=OUTPUT_DIR, upload_queue=None):
    """
    Enhanced version of download_youtube_videos that detects when individual 
    videos are completed and adds them to the upload queue.
    """
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
    
    if isinstance(urls, list):
        cmd.extend(urls)
    else:
        cmd.extend(["--playlist-reverse", urls])
    
    logger.info(f"Running yt-dlp command: {' '.join(cmd)}")

    process = Popen(cmd, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, universal_newlines=True)

    current_video = None
    completed_files = []

    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        if not line:
            continue
            
        # Detect when a video download starts
        if "[download]" in line and "Destination:" in line:
            parts = line.split("Destination: ")
            if len(parts) > 1:
                current_video = parts[1].strip()
                logger.info(f"Started downloading: {current_video}")
                
        # Detect when a video is finished downloading and processing
        if "[ffmpeg] Merging formats into" in line and current_video:
            video_path = line.split("[ffmpeg] Merging formats into ")[-1].strip('"')
            logger.info(f"Finished downloading and processing: {video_path}")
            
            # Add to upload queue if it's an mp4 file
            if video_path.endswith('.mp4') and upload_queue is not None:
                logger.info(f"Adding to upload queue: {video_path}")
                upload_queue.put({
                    'video_path': video_path,
                    'attempt': 1,
                    'max_attempts': 5,  # Maximum number of metadata check attempts
                    'timestamp': time.time()  # When this video was added to the queue
                })
                completed_files.append(video_path)
            
            current_video = None
            
        # Log as in the original function
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

    return completed_files

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

def check_metadata_ready(video_file):
    """
    Check if the metadata JSON file for a video exists and is valid.
    Returns (success, metadata) tuple.
    """
    json_file = video_file.rsplit(".", 1)[0] + ".info.json"
    
    # Check if the JSON file exists
    if not os.path.exists(json_file):
        logger.debug(f"Metadata file not found yet: {json_file}")
        return False, None
        
    # Try to read and parse the JSON file
    try:
        with open(json_file, "r") as f:
            metadata = json.load(f)
            
        # Verify that it has the expected fields
        required_fields = ["title"]
        if all(field in metadata for field in required_fields):
            return True, get_video_metadata(json_file)
        else:
            logger.debug(f"Metadata file incomplete: {json_file}")
            return False, None
            
    except (json.JSONDecodeError, IOError) as e:
        logger.debug(f"Error reading metadata file: {e}")
        return False, None
