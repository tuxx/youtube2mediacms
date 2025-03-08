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
import argparse
import logging
import threading
import queue
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('yt2mediacms')

# Import constants from the constants module
from src.constants import OUTPUT_DIR, CONFIG_FILE

# Import modules from src/
from src.config import load_config
from src.youtube import extract_channel_id
from src.mediacms import find_token_for_username
from src.tui import enable_tui, disable_tui, is_tui_enabled
from src.channel import (
    update_channel_metadata,
    sync_channel_new,
    sync_channel_full,
    sync_channel_improved,
    sync_video_ids
)
from src.upload import UploadManager
from src.download import DownloadManager

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
    
    # Thread management arguments
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
        
        # Get YouTube API key (now required)
        youtube_api_key = youtube_config.get("api_key")
        if not youtube_api_key:
            logger.error("YouTube API key is required. Please add it to your config file.")
            sys.exit(1)
    
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
                
            for channel in channels:
                update_channel_metadata(channel, mediacms_url, youtube_api_key)
            sys.exit(0)
    
        # Before running sync modes, update channel metadata
        if not args.update_channel:  # Don't do this if we're already in update_channel mode
            logger.info("Will update channel metadata before syncing videos")
            for channel in channels:
                update_channel_metadata(channel, mediacms_url, youtube_api_key)
                
        # Default: channel sync mode
        if not channels:
            logger.error("No channels defined in configuration.")
            sys.exit(1)
            
        logger.info(f"Running in {args.mode} mode for {len(channels)} channel(s).")
        for channel in channels:
            if args.mode == "new":
                sync_channel_new(channel, mediacms_url, args.delay, args.keep_files, youtube_api_key)
            elif args.mode == "full":
                # Use improved implementation for multiple workers or TUI
                if args.download_workers > 1 or args.upload_workers > 1 or args.tui:
                    sync_channel_improved(
                        channel,
                        mediacms_url,
                        args.delay,
                        args.keep_files,
                        youtube_api_key,
                        download_workers=args.download_workers,
                        upload_workers=args.upload_workers,
                        wait_for_encoding=args.wait_for_encoding
                    )
                else:
                    # Use simple implementation for single worker
                    sync_channel_full(
                        channel,
                        mediacms_url,
                        args.delay,
                        args.keep_files,
                        youtube_api_key
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
