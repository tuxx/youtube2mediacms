import logging
import time
import os
from .constants import OUTPUT_DIR

logger = logging.getLogger('yt2mediacms')

# Import functions from other modules
from .youtube import (
    extract_channel_id, 
    fetch_videos_with_api, 
    get_channel_info_youtube_api, 
    download_youtube_videos,
    get_video_metadata
)
from .mediacms import (
    get_latest_mediacms_video_info, 
    update_mediacms_channel,
    upload_to_mediacms
)
from .download import DownloadManager
from .upload import UploadManager
from .tui import is_tui_enabled

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
    """
    Syncs only new videos by comparing with what's already in MediaCMS.
    """
    yt_channel_url = channel.get("url")
    token = channel.get("mediacms_token")
    channel_id = extract_channel_id(yt_channel_url)
    channel_name = channel.get("name", "Unknown Channel")
    
    if not yt_channel_url or not token:
        logger.error("Channel configuration missing 'url' or 'mediacms_token'.")
        return
    
    # API key is now required
    if not youtube_api_key:
        logger.error("YouTube API key is required for channel sync.")
        return

    logger.info(f"Syncing new videos for channel {channel_name} (ID: {channel_id})")

    # Get the latest video info from MediaCMS
    last_title, last_date = get_latest_mediacms_video_info(mediacms_url, token)
    if last_title is not None:
        logger.info(f"Latest MediaCMS video title: {last_title}")
        if last_date:
            logger.info(f"Latest MediaCMS video date: {last_date}")
    else:
        logger.info("No previous MediaCMS video found; will fetch recent videos only.")

    # Use last_date as the threshold for the YouTube API
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
        success, _ = upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)

def sync_channel_full(channel, mediacms_url, delay, keep_files, youtube_api_key):
    """
    Performs a full channel sync using the YouTube API.
    Fetches ALL videos from the channel, starting with the oldest.
    """
    yt_channel_url = channel.get("url")
    token = channel.get("mediacms_token")
    channel_name = channel.get("name", "Unknown Channel")
    
    if not yt_channel_url or not token:
        logger.error("Channel configuration missing 'url' or 'mediacms_token'.")
        return
    
    # API key is now required
    if not youtube_api_key:
        logger.error("YouTube API key is required for channel sync.")
        return

    logger.info(f"Performing full sync for channel {channel_name} ({yt_channel_url})")
    
    # Extract channel ID
    channel_id = extract_channel_id(yt_channel_url)
    
    # Fetch all videos, sorted by date (oldest first)
    videos = fetch_videos_with_api(
        channel_id, 
        youtube_api_key,
        order="date",
        fetch_all=True  # Get all videos, not just first 50
    )
    
    if not videos:
        logger.warning(f"No videos found for channel {channel_name} via API.")
        return
        
    logger.info(f"Found {len(videos)} videos via API.")
    
    # Sort by published date (oldest first)
    videos.sort(key=lambda x: x.get("published", ""))
    
    # Extract video IDs
    video_ids = [video["video_id"] for video in videos]
    
    # Create video URLs for yt-dlp
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    
    # Download videos (in the order provided - oldest first)
    video_files = download_youtube_videos(video_urls, OUTPUT_DIR)
    
    if not video_files:
        logger.warning("No videos downloaded in full mode.")
        return

    for video_file in video_files:
        json_file = video_file.rsplit(".", 1)[0] + ".info.json"
        metadata = get_video_metadata(json_file) if os.path.exists(json_file) else {}
        success, _ = upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)

def sync_channel_improved(channel, mediacms_url, delay, keep_files, youtube_api_key, 
                          download_workers=1, upload_workers=1, wait_for_encoding=True):
    """
    Enhanced channel sync with separate download and upload threads,
    and optional encoding status tracking.
    """
    yt_channel_url = channel.get("url")
    token = channel.get("mediacms_token")
    channel_name = channel.get("name", "Unknown Channel")
    
    if not yt_channel_url or not token:
        logger.error("Channel configuration missing 'url' or 'mediacms_token'.")
        return
    
    # API key is now required
    if not youtube_api_key:
        logger.error("YouTube API key is required for channel sync.")
        return

    logger.info(f"Performing improved sync for channel {channel_name} ({yt_channel_url})")
    logger.info(f"Using {download_workers} download worker(s) and {upload_workers} upload worker(s)")
    logger.info(f"Wait for encoding: {wait_for_encoding}")
    
    # Set up the upload manager first
    upload_manager = UploadManager(
        mediacms_url, 
        token, 
        keep_files=keep_files, 
        num_workers=upload_workers,
        wait_for_encoding=wait_for_encoding,
        delay=delay
    )
    
    if not upload_manager.start():
        logger.error("Failed to start upload manager. Aborting.")
        return
    
    # Optionally start the encoding status monitor for TUI mode
    if is_tui_enabled():
        upload_manager.monitor_encoding_status(interval=delay)
    
    # Callback function for when a video is downloaded
    def download_callback(video_file, metadata):
        upload_manager.add_video(video_file, metadata)
    
    # Set up the download manager
    download_manager = DownloadManager(
        output_dir=OUTPUT_DIR,
        num_workers=download_workers,
        callback=download_callback
    )
    
    # Start the download workers
    download_manager.start()
    
    # Use YouTube API to get ALL video IDs (not just the most recent 50)
    channel_id = extract_channel_id(yt_channel_url)
    videos = fetch_videos_with_api(
        channel_id, 
        youtube_api_key, 
        fetch_all=True  # Get ALL videos, not just the most recent 50
    )
    
    # Sort videos by publish date (oldest first)
    videos.sort(key=lambda x: x.get("published", ""))
    video_ids = [v["video_id"] for v in videos]
    
    logger.info(f"Found {len(video_ids)} videos to process via API")
    
    # Queue all videos for download
    download_manager.add_videos(video_ids)
    
    # Signal that all videos have been added to the queue
    download_manager.mark_completed()
    
    # Wait for all downloads to complete
    download_manager.wait()
    logger.info("All downloads completed")
    
    # Wait for all uploads to complete
    upload_manager.wait()
    logger.info("All uploads completed")
    
    logger.info(f"Channel sync completed for {channel_name}")

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
        success, _ = upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)
