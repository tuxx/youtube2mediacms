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
   • --delay: Delay (in seconds) between uploads or encoding status checks.
   • --keep-files: If provided, downloaded files will not be removed after upload.
   • --mediacms-url: Override the global MediaCMS URL from config.
   • --youtube-channel: (For channel sync modes) If provided, only operate on the channel (as defined in config "name") that matches.
   • --download-workers: Number of parallel download worker threads.
   • --upload-workers: Number of parallel upload worker threads.
   • --wait-for-encoding: Wait for each video to finish encoding before uploading the next one.
   • --no-wait-for-encoding: Don't wait for videos to finish encoding before uploading more.
   • --tui: Enable text-based user interface with live status updates.

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
import threading
import queue
import concurrent.futures
import subprocess
import shutil
from subprocess import Popen, PIPE, STDOUT
from collections import deque
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

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

# Global helper function to safely check if TUI is enabled
def is_tui_enabled():
    """Safely check if TUI is enabled"""
    return 'tui_manager' in globals() and hasattr(tui_manager, 'live') and tui_manager.live is not None

# Initialize TUI function
def initialize_tui():
    """
    Complete replacement for the TUI initialization system.
    This ensures clean output with no duplicates.
    """
    if not RICH_AVAILABLE:
        print("Rich library not installed. Install it with: pip install rich")
        return False

    # Setup for Docker container environment
    import os
    in_container = os.environ.get('CONTAINER', '') == 'docker' or os.path.exists('/.dockerenv')
    if in_container:
        print("Running in Docker container. Enabling TUI with container optimizations.")
        os.environ['TERM'] = os.environ.get('TERM', 'xterm-256color')
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        os.environ['COLORTERM'] = 'truecolor'

    try:
        # Completely disable standard logging output
        import logging
        root_logger = logging.getLogger()
        
        # Store original handlers and level for restoration later
        original_handlers = root_logger.handlers.copy()
        original_level = root_logger.level
        
        # Remove all handlers and set level to ERROR to suppress console output
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create a brand new TUIManager instance to avoid any state issues
        from rich.console import Console
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        
        class CleanTUIManager:
            def __init__(self):
                self.console = Console(highlight=False)
                self.live = None
                self.enabled = False
                self.stats = {
                    "videos_downloaded": 0,
                    "videos_uploaded": 0,
                    "videos_encoding": 0,
                    "videos_encoded": 0,
                    "start_time": datetime.now(),
                    "download_threads": {},
                    "upload_threads": {},
                    "recent_logs": []
                }
                self.lock = threading.Lock()
            
            def is_enabled(self):
                """Check if TUI is enabled"""
                return self.enabled
                
            def start(self):
                """Start the TUI display"""
                self.layout = self.generate_layout()
                self.live = Live(self.layout, refresh_per_second=2, console=self.console)
                self.live.start()
                self.enabled = True
                return self
                
            def stop(self):
                """Stop the TUI display"""
                if self.live:
                    self.live.stop()
                    self.enabled = False
            
            def log(self, message, level="INFO"):
                """Add a log entry"""
                with self.lock:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.stats["recent_logs"].append((timestamp, level, message))
                    # Keep only the most recent 10 logs
                    if len(self.stats["recent_logs"]) > 10:
                        self.stats["recent_logs"].pop(0)
                    
                    # Update the live display
                    if self.live:
                        self.live.update(self.generate_layout())
            
            def update_download_thread(self, thread_id, status, video_id=None):
                """Update the status of a download thread"""
                with self.lock:
                    self.stats["download_threads"][thread_id] = {
                        "status": status,
                        "video_id": video_id,
                        "updated_at": datetime.now()
                    }
                    
                    if status == "completed" and video_id:
                        self.stats["videos_downloaded"] += 1
                    
                    if self.live:
                        self.live.update(self.generate_layout())
            
            def update_upload_thread(self, thread_id, status, video_id=None, encoding_status=None):
                """Update the status of an upload thread"""
                with self.lock:
                    self.stats["upload_threads"][thread_id] = {
                        "status": status,
                        "video_id": video_id,
                        "updated_at": datetime.now(),
                        "encoding_status": encoding_status
                    }
                    
                    if status == "uploaded" and video_id:
                        self.stats["videos_uploaded"] += 1
                        self.stats["videos_encoding"] += 1
                    
                    if encoding_status == "success" and video_id:
                        self.stats["videos_encoded"] += 1
                        self.stats["videos_encoding"] = max(0, self.stats["videos_encoding"] - 1)
                    
                    if self.live:
                        self.live.update(self.generate_layout())
            
            def generate_layout(self):
                """Generate the complete TUI layout"""
                # Create a main table for the entire layout
                layout_table = Table.grid(expand=True)
                layout_table.add_column("Main")
                
                # Add the header with stats
                duration = datetime.now() - self.stats["start_time"]
                duration_str = str(duration).split('.')[0]  # Remove microseconds
                
                header = Table.grid(expand=True)
                header.add_column("Stats", justify="center", ratio=1)
                header.add_column("Timing", justify="center", ratio=1)
                
                # Create formatted text elements for stats instead of a string with markup
                from rich.text import Text
                stats_text = Text()
                stats_text.append("Downloaded: ", style="bold green")
                stats_text.append(str(self.stats['videos_downloaded']))
                stats_text.append(" | ")
                stats_text.append("Uploaded: ", style="bold blue")
                stats_text.append(str(self.stats['videos_uploaded']))
                stats_text.append(" | ")
                stats_text.append("Encoding: ", style="bold yellow")
                stats_text.append(str(self.stats['videos_encoding']))
                stats_text.append(" | ")
                stats_text.append("Completed: ", style="bold green")
                stats_text.append(str(self.stats['videos_encoded']))
                
                timing_text = Text()
                timing_text.append("Running time: ", style="bold")
                timing_text.append(duration_str)
                
                header.add_row(stats_text, timing_text)
    
                # Create the download threads table
                download_table = Table(
                    title="Download Threads",
                    expand=True,
                    border_style="blue"
                )
                download_table.add_column("Thread ID")
                download_table.add_column("Status")
                download_table.add_column("Video")
                download_table.add_column("Last Update")
                
                for thread_id, info in self.stats["download_threads"].items():
                    # Format time as HH:MM:SS
                    update_time = info["updated_at"].strftime("%H:%M:%S")
                    status_color = "green" if info["status"] == "completed" else "yellow"
                    
                    download_table.add_row(
                        f"{thread_id}",
                        f"[{status_color}]{info['status']}[/{status_color}]",
                        f"{info['video_id'] or ''}",
                        f"{update_time}"
                    )
                
                # Create the upload threads table
                upload_table = Table(
                    title="Upload/Encoding Threads",
                    expand=True,
                    border_style="green"
                )
                upload_table.add_column("Thread ID")
                upload_table.add_column("Status")
                upload_table.add_column("Video")
                upload_table.add_column("Encoding")
                upload_table.add_column("Last Update")
                
                for thread_id, info in self.stats["upload_threads"].items():
                    # Format time as HH:MM:SS
                    update_time = info["updated_at"].strftime("%H:%M:%S")
                    
                    # Set status color based on current status
                    status_color = "yellow"
                    if info["status"] == "uploaded":
                        status_color = "green"
                    elif info["status"] == "waiting":
                        status_color = "blue"
                    
                    # Set encoding status color
                    encoding_color = "yellow"
                    if info["encoding_status"] == "success":
                        encoding_color = "green"
                    elif info["encoding_status"] == "fail":
                        encoding_color = "red"
                    
                    upload_table.add_row(
                        f"{thread_id}",
                        f"[{status_color}]{info['status']}[/{status_color}]",
                        f"{info['video_id'] or ''}",
                        f"[{encoding_color}]{info['encoding_status'] or ''}[/{encoding_color}]",
                        f"{update_time}"
                    )
                
                # Create recent logs panel
                logs_table = Table(
                    expand=True,
                    show_header=False,
                    box=None
                )
                logs_table.add_column("Time", style="dim", width=10)
                logs_table.add_column("Level", width=10)
                logs_table.add_column("Message", ratio=1)
                
                for timestamp, level, message in self.stats["recent_logs"]:
                    level_color = "white"
                    if level == "INFO":
                        level_color = "blue"
                    elif level == "WARNING":
                        level_color = "yellow"
                    elif level == "ERROR":
                        level_color = "red"
                    
                    logs_table.add_row(
                        timestamp,
                        f"[{level_color}]{level}[/{level_color}]",
                        message
                    )
                
                logs_panel = Panel(
                    logs_table,
                    title="Recent Logs",
                    border_style="yellow"
                )
                
                # Add all components to the layout
                layout_table.add_row(Panel(header, title="YouTube to MediaCMS Sync", border_style="green"))
                layout_table.add_row(download_table)
                layout_table.add_row(upload_table)
                layout_table.add_row(logs_panel)
                
                return layout_table
        
        # Create and initialize a new TUI manager
        tui = CleanTUIManager().start()
        
        # Create custom logging methods that use the TUI
        def tui_info(msg, *args, **kwargs):
            if args or kwargs:
                try:
                    msg = msg % args
                except:
                    pass
            tui.log(msg, "INFO")
            
        def tui_error(msg, *args, **kwargs):
            if args or kwargs:
                try:
                    msg = msg % args
                except:
                    pass
            tui.log(msg, "ERROR")
            
        def tui_warning(msg, *args, **kwargs):
            if args or kwargs:
                try:
                    msg = msg % args
                except:
                    pass
            tui.log(msg, "WARNING")
            
        def tui_debug(msg, *args, **kwargs):
            # Skip debug messages in TUI
            pass
        
        # Replace the global logger functions
        logger.info = tui_info
        logger.error = tui_error
        logger.warning = tui_warning
        logger.debug = tui_debug
        
        # Set modified logger in global scope
        global tui_manager
        tui_manager = tui
        
        # Store original state for cleanup
        tui_manager.original_handlers = original_handlers
        tui_manager.original_level = original_level
        
        return True
        
    except Exception as e:
        print(f"Error initializing TUI: {str(e)}")
        return False

def cleanup_tui():
    """Clean up the TUI and restore original logging"""
    if 'tui_manager' in globals() and hasattr(tui_manager, 'stop'):
        try:
            # Stop the live display
            tui_manager.stop()
            
            # Restore the original logging configuration
            root_logger = logging.getLogger()
            
            if hasattr(tui_manager, 'original_handlers'):
                # First remove any current handlers
                for handler in root_logger.handlers[:]:
                    root_logger.removeHandler(handler)
                
                # Then restore original handlers
                for handler in tui_manager.original_handlers:
                    root_logger.addHandler(handler)
            
            if hasattr(tui_manager, 'original_level'):
                root_logger.setLevel(tui_manager.original_level)
            
        except Exception as e:
            print(f"Error cleaning up TUI: {str(e)}")

# Replace the enable_tui function
def enable_tui():
    return initialize_tui()

# Replace the disable_tui function
def disable_tui():
    cleanup_tui()


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


def check_encoding_status(mediacms_url, token, username):
    """
    Check the encoding status of recently uploaded videos.
    Returns a dictionary with counts of videos in each encoding status.
    """
    api_url = f"{mediacms_url.rstrip('/')}/api/v1/media?author={username}&show=latest"
    headers = {
        "accept": "application/json",
        "Authorization": f"Token {token}"
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.error(f"Failed to get encoding status: {response.status_code} - {response.text}")
            return None
            
        data = response.json()
        
        # Count videos by encoding status
        status_counts = {
            "pending": 0,
            "running": 0,
            "fail": 0,
            "success": 0
        }
        
        for video in data.get("results", []):
            encoding_status = video.get("encoding_status")
            if encoding_status in status_counts:
                status_counts[encoding_status] += 1
        
        logger.debug(f"Encoding status counts: {status_counts}")
        return status_counts
    except Exception as e:
        logger.error(f"Error checking encoding status: {e}")
        return None


def check_video_encoding_status(mediacms_url, token, friendly_token):
    """
    Check the encoding status of a specific video by its friendly_token.
    
    Returns:
    - str: The encoding status ("pending", "running", "fail", "success") or None if not found
    """
    api_url = f"{mediacms_url.rstrip('/')}/api/v1/media/{friendly_token}"
    headers = {
        "accept": "application/json",
        "Authorization": f"Token {token}"
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.error(f"Failed to get video status: {response.status_code} - {response.text}")
            return None
            
        data = response.json()
        return data.get("encoding_status")
    except Exception as e:
        logger.error(f"Error checking video encoding status: {e}")
        return None


def extract_friendly_token_from_response(response):
    """
    Extract the friendly_token from a MediaCMS upload response.
    """
    try:
        if response.status_code in (200, 201):
            data = response.json()
            return data.get("friendly_token")
    except Exception as e:
        logger.error(f"Error extracting friendly_token: {e}")
    return None


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
            
            # Extract friendly_token for tracking encoding status
            friendly_token = extract_friendly_token_from_response(response)
            
    except Exception as e:
        logger.error(f"Exception during upload: {e}")
        return False, None

    if response.status_code in (200, 201):
        logger.info(f"Successfully uploaded {metadata['title']}")

        if cleanup:
            clean_up_files(video_file)

        return True, friendly_token
    else:
        logger.error(f"Failed to upload {metadata['title']}: {response.status_code}")
        logger.error(response.text)
        return False, None


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
        success, _ = upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
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
        success, _ = upload_to_mediacms(video_file, mediacms_url, token, metadata, cleanup=(not keep_files))
        time.sleep(delay)


class DownloadManager:
    """
    Manages video downloads using multiple worker threads.
    """
    def __init__(self, output_dir=OUTPUT_DIR, num_workers=1, callback=None):
        self.output_dir = output_dir
        self.num_workers = num_workers
        self.queue = queue.Queue()
        self.callback = callback  # Function to call when a video is downloaded
        self.workers = []
        self.completed = threading.Event()
        self.processed_videos = 0
        self.lock = threading.Lock()
        
        # Ensure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logger.info(f"Created output directory: {self.output_dir}")
    
    def start(self):
        """Start the download worker threads"""
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._download_worker,
                args=(i+1,),
                daemon=True
            )
            self.workers.append(worker)
            worker.start()
            logger.info(f"Started download worker {i+1}")
    
    def add_video(self, video_id):
        """Add a video ID to the download queue"""
        self.queue.put(video_id)
        
    def add_videos(self, video_ids):
        """Add multiple video IDs to the queue"""
        for vid in video_ids:
            self.add_video(vid)
    
    def mark_completed(self):
        """Signal that all videos have been added to the queue"""
        self.completed.set()
    
    def wait(self):
        """Wait for all workers to complete"""
        for worker in self.workers:
            worker.join()
    
    def _download_worker(self, worker_id):
        """Worker thread function for downloading videos"""
        thread_name = f"Download-{worker_id}"
        
        if is_tui_enabled():
            tui_manager.update_download_thread(thread_name, "started")
        
        while not (self.completed.is_set() and self.queue.empty()):
            try:
                # Get a video from the queue with timeout
                try:
                    video_id = self.queue.get(timeout=5)
                except queue.Empty:
                    continue
                
                # Update TUI status
                if is_tui_enabled():
                    tui_manager.update_download_thread(
                        thread_name, 
                        "downloading", 
                        video_id
                    )
                
                # Download the video
                logger.info(f"{thread_name}: Downloading video ID: {video_id}")
                
                # Create a temporary directory for this video
                temp_dir = os.path.join(self.output_dir, video_id)
                os.makedirs(temp_dir, exist_ok=True)
                
                # Prepare download command
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                cmd = [
                    "yt-dlp",
                    "--ignore-errors",
                    "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "--postprocessor-args", "-c copy",
                    "--write-info-json",
                    "--write-thumbnail",
                    "--restrict-filenames",
                    "--no-colors",
                    "-o", f"{temp_dir}/%(upload_date)s-%(title)s-%(id)s.%(ext)s",
                    video_url
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    logger.error(f"{thread_name}: Failed to download {video_id}: {result.stderr}")
                    
                    if is_tui_enabled():
                        tui_manager.update_download_thread(
                            thread_name, 
                            "failed", 
                            video_id
                        )
                        
                    self.queue.task_done()
                    continue
                
                # Find the downloaded MP4 file
                mp4_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
                if not mp4_files:
                    logger.error(f"{thread_name}: No MP4 file found after download for {video_id}")
                    
                    if is_tui_enabled():
                        tui_manager.update_download_thread(
                            thread_name, 
                            "failed", 
                            video_id
                        )
                        
                    self.queue.task_done()
                    continue
                
                video_file = os.path.join(temp_dir, mp4_files[0])
                
                # Check and wait for the metadata file
                metadata = self._wait_for_metadata(video_file)
                
                logger.info(f"{thread_name}: Successfully downloaded {video_id}")
                
                if is_tui_enabled():
                    tui_manager.update_download_thread(
                        thread_name, 
                        "completed", 
                        video_id
                    )
                
                # Increment processed count
                with self.lock:
                    self.processed_videos += 1
                
                # Call the callback if provided
                if self.callback:
                    self.callback(video_file, metadata)
                
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"{thread_name}: Error downloading video: {e}")
                
                if is_tui_enabled():
                    tui_manager.update_download_thread(
                        thread_name, 
                        "error", 
                        video_id if 'video_id' in locals() else None
                    )
                
                # Mark task as done if it failed
                try:
                    self.queue.task_done()
                except:
                    pass
    
    def _wait_for_metadata(self, video_file, max_attempts=5):
        """Wait for the metadata file to be fully written and return it"""
        json_file = video_file.rsplit(".", 1)[0] + ".info.json"
        
        for attempt in range(1, max_attempts + 1):
            if os.path.exists(json_file):
                try:
                    metadata = get_video_metadata(json_file)
                    if metadata and 'title' in metadata:
                        return metadata
                except json.JSONDecodeError:
                    logger.debug(f"Metadata file not fully written yet: {json_file}")
            
            if attempt < max_attempts:
                logger.debug(f"Metadata not ready, attempt {attempt}/{max_attempts}. Waiting...")
                time.sleep(2 * attempt)  # Increasing backoff
                
        logger.warning(f"Could not get metadata after {max_attempts} attempts, using empty metadata")
        return {}


class UploadManager:
    """
    Manages video uploads with encoding status tracking
    """
    def __init__(self, mediacms_url, token, keep_files=False, num_workers=1, wait_for_encoding=True, delay=5):
        self.mediacms_url = mediacms_url
        self.token = token
        self.keep_files = keep_files
        self.num_workers = num_workers
        self.wait_for_encoding = wait_for_encoding
        self.delay = delay
        self.username = None
        self.queue = queue.Queue()
        self.workers = []
        self.lock = threading.Lock()
        
        # Track most recently uploaded videos per thread (friendly_token)
        self.last_uploads = {}
        
        # Number of completed uploads
        self.completed_uploads = 0
    
    def start(self):
        """Start the upload worker threads"""
        # Get the MediaCMS username first
        self.username = get_mediacms_username(self.mediacms_url, self.token)
        if not self.username:
            logger.error("Could not determine MediaCMS username for upload manager")
            return False
        
        logger.info(f"Starting {self.num_workers} upload worker(s) for user: {self.username}")
        
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._upload_worker,
                args=(i+1,),
                daemon=True
            )
            self.workers.append(worker)
            worker.start()
            logger.info(f"Started upload worker {i+1}")
            
        return True
    
    def add_video(self, video_file, metadata=None):
        """Add a video to the upload queue"""
        self.queue.put({
            'video_file': video_file,
            'metadata': metadata or {}
        })
    
    def wait(self):
        """Wait for all uploads to complete"""
        self.queue.join()
        logger.info(f"All uploads completed. Total: {self.completed_uploads}")
    
    def _upload_worker(self, worker_id):
        """Worker thread function for uploading videos"""
        thread_name = f"Upload-{worker_id}"
        last_token = None
        
        if is_tui_enabled():
            tui_manager.update_upload_thread(thread_name, "started")
        
        while True:
            try:
                # Before getting a new video, check if we need to wait for encoding
                if self.wait_for_encoding and last_token:
                    # Check if the previous upload is done encoding
                    encoding_status = check_video_encoding_status(
                        self.mediacms_url, 
                        self.token, 
                        last_token
                    )
                    
                    if is_tui_enabled():
                        tui_manager.update_upload_thread(
                            thread_name,
                            "waiting",
                            video_id=None,
                            encoding_status=encoding_status
                        )
                    
                    if encoding_status not in ["success", "fail"]:
                        # Still encoding, wait and check again
                        logger.info(f"{thread_name}: Waiting for video {last_token} to finish encoding (status: {encoding_status})")
                        time.sleep(self.delay)
                        continue
                    
                    logger.info(f"{thread_name}: Previous video {last_token} encoding {encoding_status}")
                    last_token = None
                
                # Get a video from the queue with timeout
                try:
                    video_item = self.queue.get(timeout=5)
                except queue.Empty:
                    continue
                
                video_file = video_item['video_file']
                metadata = video_item['metadata']
                
                # Extract video ID from filename
                video_id = os.path.basename(video_file).split('-')[-1].split('.')[0]
                
                if is_tui_enabled():
                    tui_manager.update_upload_thread(
                        thread_name,
                        "uploading",
                        video_id
                    )
                
                # Upload the video
                logger.info(f"{thread_name}: Uploading video: {video_id}")
                success, friendly_token = upload_to_mediacms(
                    video_file, 
                    self.mediacms_url, 
                    self.token, 
                    metadata, 
                    cleanup=(not self.keep_files)
                )
                
                if success:
                    logger.info(f"{thread_name}: Successfully uploaded {video_id} (token: {friendly_token})")
                    
                    # Record the friendly token for encoding status tracking
                    if friendly_token:
                        last_token = friendly_token
                        
                        with self.lock:
                            self.last_uploads[thread_name] = friendly_token
                            self.completed_uploads += 1
                    
                    if is_tui_enabled():
                        tui_manager.update_upload_thread(
                            thread_name,
                            "uploaded",
                            video_id,
                            encoding_status="pending"
                        )
                else:
                    logger.error(f"{thread_name}: Failed to upload {video_id}")
                    
                    if is_tui_enabled():
                        tui_manager.update_upload_thread(
                            thread_name,
                            "failed",
                            video_id
                        )
                
                # Mark this task as done
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"{thread_name}: Error in upload worker: {e}")
                
                # Mark the task as done if it failed
                try:
                    self.queue.task_done()
                except:
                    pass

    def monitor_encoding_status(self, interval=10, max_time=3600):
        """
        Start a thread to monitor encoding status of recently uploaded videos.
        This runs as a separate thread to update the TUI with encoding status
        without interfering with the upload workers.
        """
        if not is_tui_enabled():
            return  # Only run when TUI is enabled
            
        def _monitor_thread():
            logger.info("Started encoding status monitor thread")
            end_time = time.time() + max_time
            
            while time.time() < end_time:
                with self.lock:
                    for thread_name, token in list(self.last_uploads.items()):
                        try:
                            status = check_video_encoding_status(
                                self.mediacms_url, 
                                self.token, 
                                token
                            )
                            
                            if status in ["success", "fail"]:
                                # Update the TUI
                                if is_tui_enabled():
                                    tui_manager.update_upload_thread(
                                        thread_name,
                                        "completed",
                                        None,  # We don't have the video ID here
                                        encoding_status=status
                                    )
                                
                                # Remove from tracking if done
                                if not self.wait_for_encoding:
                                    self.last_uploads.pop(thread_name, None)
                            else:
                                # Update the TUI with current status
                                if is_tui_enabled():
                                    tui_manager.update_upload_thread(
                                        thread_name,
                                        "waiting",
                                        None,  # We don't have the video ID here
                                        encoding_status=status
                                    )
                        except Exception as e:
                            logger.debug(f"Error checking encoding status: {e}")
                
                time.sleep(interval)
                
        # Start the monitor thread
        monitor = threading.Thread(target=_monitor_thread, daemon=True)
        monitor.start()
        return monitor


def sync_channel_improved(channel, mediacms_url, delay, keep_files, youtube_api_key=None, 
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
    
    if youtube_api_key:
        # Use YouTube API to get video IDs
        channel_id = extract_channel_id(yt_channel_url)
        videos = fetch_videos_with_api(channel_id, youtube_api_key)
        video_ids = [v["video_id"] for v in videos]
        
        # Sort video IDs chronologically (oldest first)
        video_ids.reverse()
        
        logger.info(f"Found {len(video_ids)} videos to process via API")
        
        # Queue all videos for download
        download_manager.add_videos(video_ids)
    else:
        # Without API, use a special single-thread downloader that monitors yt-dlp output
        logger.info("YouTube API key not available. Using stream output parser for downloads.")
        logger.warning("This mode does not support multiple download workers. Using 1 worker only.")
        
        # Create a thread that runs the download_youtube_videos_with_callback function
        def streaming_download():
            logger.info("Starting streaming download thread")
            downloaded_files = download_youtube_videos_with_callback(yt_channel_url, OUTPUT_DIR)
            
            # Process each downloaded file
            for video_file in downloaded_files:
                json_file = video_file.rsplit(".", 1)[0] + ".info.json"
                metadata = get_video_metadata(json_file) if os.path.exists(json_file) else {}
                upload_manager.add_video(video_file, metadata)
                
            logger.info("Streaming download thread completed")
            
        download_thread = threading.Thread(target=streaming_download)
        download_thread.start()
        download_thread.join()
        
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
    parser.add_argument("--delay", type=int, default=5, help="Delay (in seconds) between status checks or uploads")
    parser.add_argument("--keep-files", action="store_true", help="Keep downloaded files after upload")
    parser.add_argument("--mediacms-username", help="Target MediaCMS username for video-ids mode")
    parser.add_argument("--youtube-channel", help="Operate only on the channel with this name (as defined in config 'name')")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--log-file", help="Log to specified file in addition to console")
    
    # Add new arguments for improved thread management
    parser.add_argument("--download-workers", type=int, default=1,
                       help="Number of parallel download worker threads")
    parser.add_argument("--upload-workers", type=int, default=1,
                       help="Number of parallel upload worker threads")
    parser.add_argument("--wait-for-encoding", action="store_true",
                       help="Wait for each video to finish encoding before uploading the next one")
    parser.add_argument("--no-wait-for-encoding", action="store_false", dest="wait_for_encoding",
                       help="Don't wait for videos to finish encoding before uploading more")
    parser.add_argument("--tui", action="store_true",
                       help="Enable text-based user interface with live status updates")
    
    # Set defaults
    parser.set_defaults(wait_for_encoding=True)
    
    # Show help if no arguments are provided
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    args = parser.parse_args()

    # Enable TUI first if requested, before any other logging happens
    tui_enabled = False
    if args.tui:
        tui_enabled = enable_tui()
    
    if args.verbose and not tui_enabled:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    if args.log_file and not tui_enabled:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {args.log_file}")

    try:
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
            
            # If using TUI mode, use the enhanced video ID sync
            if tui_enabled:
                # Set up the upload manager
                upload_manager = UploadManager(
                    mediacms_url, 
                    token, 
                    keep_files=args.keep_files, 
                    num_workers=args.upload_workers,
                    wait_for_encoding=args.wait_for_encoding,
                    delay=args.delay
                )
                
                if not upload_manager.start():
                    logger.error("Failed to start upload manager. Aborting.")
                    sys.exit(1)
                    
                # Optionally start the encoding status monitor for TUI mode
                upload_manager.monitor_encoding_status(interval=args.delay)
                
                # Set up the download manager
                download_manager = DownloadManager(
                    output_dir=OUTPUT_DIR,
                    num_workers=args.download_workers,
                    callback=lambda video_file, metadata: upload_manager.add_video(video_file, metadata)
                )
                
                # Start the download workers
                download_manager.start()
                
                # Add videos to the download queue
                download_manager.add_videos(args.video_ids)
                
                # Signal that all videos have been added to the queue
                download_manager.mark_completed()
                
                # Wait for all downloads and uploads to complete
                download_manager.wait()
                upload_manager.wait()
            else:
                # Use the traditional sync method
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
                # For new mode, we still use the original implementation
                sync_channel_new(channel, mediacms_url, args.delay, args.keep_files, youtube_config.get("api_key"))
            elif args.mode == "full":
                # For full mode, use our new improved implementation
                sync_channel_improved(
                    channel,
                    mediacms_url,
                    args.delay,
                    args.keep_files,
                    youtube_api_key=youtube_config.get("api_key"),
                    download_workers=args.download_workers,
                    upload_workers=args.upload_workers,
                    wait_for_encoding=args.wait_for_encoding
                )
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Always clean up TUI if enabled
        if tui_enabled:
            disable_tui()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
