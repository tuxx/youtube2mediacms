#!/usr/bin/env python3
"""
YouTube to MediaCMS Backup Script

This script downloads videos from a YouTube channel, uploads them to a MediaCMS instance,
preserves original publish dates, updates the MediaCMS channel with the YouTube channel 
description, and cleans up local files after successful upload.

Requires: yt-dlp, requests
Installation: pip install yt-dlp requests
"""

import os
import sys
import argparse
import json
import time
import datetime
import shutil
from subprocess import run, PIPE, Popen, STDOUT
import requests
import logging


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('youtube-to-mediacms')


def get_dir_size(path):
    """Get the size of a directory in bytes, then convert to human readable format"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    
    # Convert bytes to human readable format
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if total_size < 1024.0:
            return f"{total_size:.2f} {unit}"
        total_size /= 1024.0
    
    return f"{total_size:.2f} PB"

import requests
import re
import json
import subprocess
import urllib.parse
from bs4 import BeautifulSoup

def get_channel_info_youtube_api(api_key, channel_url):
    """Fetch channel information using YouTube Data API v3"""
    logger.info(f"Fetching channel information from YouTube API: {channel_url}")
    
    # Extract channel ID or username from URL
    channel_id = None
    username = None
    
    if '@' in channel_url:
        username = channel_url.split('@')[-1]
    elif 'channel/' in channel_url:
        channel_id = channel_url.split('channel/')[-1].split('/')[0]
    
    if not channel_id and not username:
        logger.error("Could not extract channel ID or username from URL")
        return None
    
    # Build the API URL
    base_url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        'key': api_key,
        'part': 'snippet,statistics'
    }
    
    if channel_id:
        params['id'] = channel_id
    else:
        params['forUsername'] = username
    
    try:
        response = requests.get(base_url, params=params, timeout=20)
        
        if response.status_code != 200:
            logger.error(f"YouTube API error: {response.status_code}")
            logger.error(response.text)
            return None
        
        data = response.json()
        
        if not data.get('items'):
            logger.error("No channel found")
            return None
        
        channel_data = data['items'][0]
        snippet = channel_data.get('snippet', {})
        
        channel_info = {
            'channel_id': channel_data.get('id'),
            'channel_name': snippet.get('title', 'Unknown Channel'),
            'channel_description': snippet.get('description', ''),
            'channel_url': channel_url
        }
        
        logger.info(f"Successfully retrieved channel info for: {channel_info['channel_name']}")
        return channel_info
        
    except Exception as e:
        logger.error(f"Exception while getting channel info: {str(e)}")
        return None


def get_channel_info_web_scraping(channel_url):
    """Fetch channel information using web scraping"""
    logger.info(f"Fetching channel information via web scraping: {channel_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(channel_url, headers=headers, timeout=20)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch channel page: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try to extract metadata from the page
        # This is fragile and may break with YouTube UI changes
        channel_name = soup.find('meta', property='og:title')
        channel_name = channel_name['content'] if channel_name else 'Unknown Channel'
        
        description_meta = soup.find('meta', {'name': 'description'})
        channel_description = description_meta['content'] if description_meta else ''
        
        # Extract channel ID from script tags
        channel_id = None
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and 'channelId' in script.string:
                match = re.search(r'"channelId":"([^"]+)"', script.string)
                if match:
                    channel_id = match.group(1)
                    break
        
        if not channel_id:
            # Extract from URL as fallback
            if '@' in channel_url:
                channel_id = channel_url.split('@')[-1]
        
        channel_info = {
            'channel_id': channel_id,
            'channel_name': channel_name,
            'channel_description': channel_description,
            'channel_url': channel_url
        }
        
        logger.info(f"Successfully retrieved channel info for: {channel_info['channel_name']}")
        return channel_info
        
    except Exception as e:
        logger.error(f"Exception while scraping channel info: {str(e)}")
        return None


def get_channel_info_youtube_dl(channel_url):
    """Fetch channel information using youtube-dl (alternative to yt-dlp)"""
    logger.info(f"Fetching channel information using youtube-dl: {channel_url}")
    
    cmd = [
        'youtube-dl',
        '--skip-download',
        '--no-warnings',
        '--get-id',
        '--get-title',
        '--get-description',
        channel_url
    ]
    
    try:
        # Use a longer timeout
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                text=True, timeout=45)
        
        if result.returncode != 0:
            logger.error(f"Error fetching channel with youtube-dl: {result.stderr}")
            return None
        
        lines = result.stdout.strip().split('\n')
        
        # Default values
        channel_id = None
        channel_name = "YouTube Channel"
        channel_description = "Imported from YouTube"
        
        if lines and len(lines) >= 1:
            channel_id = lines[0]
        if len(lines) >= 2:
            channel_name = lines[1]
        if len(lines) >= 3:
            channel_description = '\n'.join(lines[2:])
        
        channel_info = {
            'channel_id': channel_id,
            'channel_name': channel_name,
            'channel_description': channel_description,
            'channel_url': channel_url
        }
        
        logger.info(f"Successfully retrieved channel info for: {channel_info['channel_name']}")
        return channel_info
        
    except subprocess.TimeoutExpired:
        logger.error("youtube-dl process timed out")
        return None
    except Exception as e:
        logger.error(f"Exception while getting channel info with youtube-dl: {str(e)}")
        return None


def get_channel_info_invidious(channel_url, invidious_instance="https://invidious.snopyta.org"):
    """Fetch channel information using Invidious API (a YouTube alternative)"""
    logger.info(f"Fetching channel information via Invidious: {channel_url}")
    
    # Extract channel ID or username from URL
    channel_id = None
    
    if '@' in channel_url:
        username = channel_url.split('@')[-1].split('/')[0]
        api_url = f"{invidious_instance}/api/v1/search?q={urllib.parse.quote(username)}&type=channel"
    elif 'channel/' in channel_url:
        channel_id = channel_url.split('channel/')[-1].split('/')[0]
        api_url = f"{invidious_instance}/api/v1/channels/{channel_id}"
    else:
        logger.error("Could not extract channel ID or username from URL")
        return None
    
    try:
        response = requests.get(api_url, timeout=20)
        
        if response.status_code != 200:
            logger.error(f"Invidious API error: {response.status_code}")
            return None
        
        data = response.json()
        
        # Handle search results if searching by username
        if '@' in channel_url and isinstance(data, list):
            if not data:
                logger.error("No channel found in search results")
                return None
            
            # Use the first channel in search results
            channel_data = data[0]
            channel_id = channel_data.get('authorId')
            
            # Now fetch the specific channel
            channel_api_url = f"{invidious_instance}/api/v1/channels/{channel_id}"
            response = requests.get(channel_api_url, timeout=20)
            
            if response.status_code != 200:
                logger.error(f"Invidious channel API error: {response.status_code}")
                return None
                
            data = response.json()
        
        channel_info = {
            'channel_id': data.get('authorId'),
            'channel_name': data.get('author', 'Unknown Channel'),
            'channel_description': data.get('description', ''),
            'channel_url': channel_url
        }
        
        logger.info(f"Successfully retrieved channel info for: {channel_info['channel_name']}")
        return channel_info
        
    except Exception as e:
        logger.error(f"Exception while getting channel info from Invidious: {str(e)}")
        return None


def get_channel_info_fallback(channel_url):
    """Combined approach to try different methods for fetching channel info"""
    logger.info(f"Trying multiple methods to fetch channel info for: {channel_url}")
    
    # Method 1: Try with standard web scraping
    channel_info = get_channel_info_web_scraping(channel_url)
    if channel_info:
        return channel_info
    
    # Method 2: Try with youtube-dl if installed
    try:
        subprocess.run(['youtube-dl', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        channel_info = get_channel_info_youtube_dl(channel_url)
        if channel_info:
            return channel_info
    except:
        logger.warning("youtube-dl not available, skipping this method")
    
    # Method 3: Try with Invidious API
    invidious_instances = [
        "https://invidious.snopyta.org",
        "https://invidious.kavin.rocks",
        "https://vid.puffyan.us"
    ]
    
    for instance in invidious_instances:
        try:
            channel_info = get_channel_info_invidious(channel_url, instance)
            if channel_info:
                return channel_info
        except:
            continue
    
    # Final fallback: Create minimal info from URL
    logger.warning("All methods failed, using minimal channel info from URL")
    channel_name = "Unknown Channel"
    
    if '@' in channel_url:
        channel_name = channel_url.split('@')[-1].split('/')[0]
    
    return {
        'channel_id': channel_name,
        'channel_name': channel_name,
        'channel_description': f"Imported from YouTube: {channel_url}",
        'channel_url': channel_url
    }

def update_mediacms_channel(mediacms_url, token, channel_info):
    """Update or create a channel on MediaCMS with YouTube channel information"""
    logger.info("Updating MediaCMS channel with YouTube channel information...")
    channels_url = f"{mediacms_url.rstrip('/')}/api/v1/users/me/"
    
    headers = {
        'Authorization': f'Token {token}',
        'Content-Type': 'application/json'
    }
    
    # Get current user info
    try:
        response = requests.get(channels_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Failed to get user information: {response.status_code}")
            logger.error(response.text)
            return False
        
        # Update user profile with channel description
        user_data = response.json()
        
        update_data = {
            'description': f"YouTube Channel: {channel_info['channel_name']}\n\n{channel_info['channel_description']}\n\nOriginal YouTube URL: {channel_info['channel_url']}"
        }
        
        # If user has username or name fields, we could update those too
        if 'name' in user_data and not user_data['name']:
            update_data['name'] = channel_info['channel_name']
        
        # Update the user profile
        update_url = f"{mediacms_url.rstrip('/')}/api/v1/users/me/"
        response = requests.patch(
            update_url,
            headers=headers,
            data=json.dumps(update_data),
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully updated MediaCMS channel with YouTube channel information")
            return True
        else:
            logger.error(f"Failed to update MediaCMS channel: {response.status_code}")
            logger.error(response.text)
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


def download_youtube_videos(channel_url, output_dir, since_date=None):
    """Download videos from a YouTube channel using yt-dlp"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")
    
    logger.info(f"Starting download of videos from: {channel_url}")
    if since_date:
        logger.info(f"Only downloading videos published after: {since_date}")
    
    # Base yt-dlp command - add --progress flag for more detailed output
    cmd = [
        'yt-dlp',
        '--ignore-errors',
        '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '--merge-output-format', 'mp4',
        '--write-info-json',
        '--write-thumbnail',
        '--restrict-filenames',
        '--progress',
        '--no-colors',  # Better for log output
        '-o', f'{output_dir}/%(upload_date)s-%(title)s-%(id)s.%(ext)s'  # Include upload date in filename
    ]
    
    # Add date filter if provided
    if since_date:
        cmd.extend(['--dateafter', since_date])
    
    # Add reverse-sort to download oldest videos first
    cmd.extend(['--playlist-reverse'])
    
    # Add the channel URL
    cmd.append(channel_url)
    
    logger.info(f"Running yt-dlp command: {' '.join(cmd)}")
    
    # Use Popen to stream the output in real-time
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
        logger.error(f"yt-dlp process exited with code {return_code}")
    
    # Get current disk usage
    dir_size = get_dir_size(output_dir)
    logger.info(f"Current disk usage of {output_dir}: {dir_size}")
    
    # Get list of downloaded MP4 files and sort by filename (which includes upload date)
    video_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
    video_files.sort()  # Sort by filename which starts with upload date (YYYYMMDD)
    
    full_paths = [os.path.join(output_dir, f) for f in video_files]
    logger.info(f"Downloaded {len(full_paths)} videos")
    
    return full_paths


def get_video_metadata(json_file):
    """Extract relevant metadata from yt-dlp JSON file"""
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Parse upload date into a format MediaCMS can use (YYYYMMDD to YYYY-MM-DD)
        upload_date = data.get('upload_date', '')
        if upload_date and len(upload_date) == 8:
            formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        else:
            formatted_date = ''
        
        metadata = {
            'title': data.get('title', ''),
            'description': data.get('description', ''),
            'tags': data.get('tags', []),
            'upload_date': formatted_date,
            'original_upload_date': upload_date,
            'duration': data.get('duration', 0),
            'view_count': data.get('view_count', 0),
        }
        
        logger.debug(f"Extracted metadata for video: {metadata['title']}")
        return metadata
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error reading metadata from {json_file}: {e}")
        return {}


def upload_to_mediacms(video_file, mediacms_url, token, metadata=None, cleanup=True):
    """Upload a video to MediaCMS instance and set the original publish date"""
    upload_url = f"{mediacms_url.rstrip('/')}/api/v1/media/"
    
    headers = {
        'Authorization': f'Token {token}'
    }
    
    # Default metadata if none provided
    if metadata is None:
        metadata = {}
    
    # Get filename for title if no title in metadata
    if 'title' not in metadata:
        metadata['title'] = os.path.basename(video_file).split('.')[0]
    
    file_size = os.path.getsize(video_file)
    file_size_human = f"{file_size / (1024 * 1024):.2f} MB"
    
    logger.info(f"Uploading {metadata['title']} ({file_size_human}) to MediaCMS...")
    
    # Prepare the payload
    data = {
        'title': metadata.get('title', ''),
        'description': metadata.get('description', ''),
        'tags': ','.join(metadata.get('tags', [])),
    }
    
    # Add original publish date if available
    if metadata.get('upload_date'):
        data['publication_date'] = metadata['upload_date']
    
    # Prepare the file for upload
    with open(video_file, 'rb') as f:
        files = {'media_file': f}
        
        # Attempt to find and include a thumbnail
        thumbnail_path = video_file.rsplit('.', 1)[0] + '.jpg'
        if os.path.exists(thumbnail_path):
            logger.info(f"Including thumbnail: {thumbnail_path}")
            files['thumbnail'] = open(thumbnail_path, 'rb')
        
        logger.info(f"Starting upload to {upload_url}...")
        
        try:
            # No timeout for upload as large files may take time
            response = requests.post(upload_url, headers=headers, data=data, files=files)
        except Exception as e:
            logger.error(f"Exception during upload: {e}")
            if 'thumbnail' in files:
                files['thumbnail'].close()
            return False
        
        # Close thumbnail file if it was opened
        if 'thumbnail' in files:
            files['thumbnail'].close()
    
    if response.status_code in (200, 201):
        logger.info(f"Successfully uploaded {metadata['title']}")
        
        # Clean up the files if requested
        if cleanup:
            clean_up_files(video_file)
        
        return True
    else:
        logger.error(f"Failed to upload {metadata['title']}: {response.status_code}")
        logger.error(response.text)
        return False


def clean_up_files(video_file):
    """Remove the video file and associated metadata files"""
    try:
        # Remove the video file
        os.remove(video_file)
        logger.info(f"Removed video file: {video_file}")
        
        # Remove the JSON metadata file if it exists
        json_file = video_file.rsplit('.', 1)[0] + '.info.json'
        if os.path.exists(json_file):
            os.remove(json_file)
            logger.info(f"Removed metadata file: {json_file}")
        
        # Remove the thumbnail if it exists
        thumbnail_file = video_file.rsplit('.', 1)[0] + '.jpg'
        if os.path.exists(thumbnail_file):
            os.remove(thumbnail_file)
            logger.info(f"Removed thumbnail file: {thumbnail_file}")
            
        # Report current disk usage after cleanup
        output_dir = os.path.dirname(video_file)
        dir_size = get_dir_size(output_dir)
        logger.info(f"Current disk usage after cleanup: {dir_size}")
        
    except Exception as e:
        logger.error(f"Error during file cleanup: {e}")

def main():
    parser = argparse.ArgumentParser(description='Backup YouTube channel to MediaCMS')
    parser.add_argument('--channel', required=True, help='YouTube channel URL')
    parser.add_argument('--mediacms-url', required=True, help='MediaCMS instance URL')
    parser.add_argument('--token', required=True, help='MediaCMS API token')
    parser.add_argument('--output-dir', default='./youtube_downloads', help='Directory to store downloads')
    parser.add_argument('--since', help='Only download videos after this date (YYYYMMDD)')
    parser.add_argument('--delay', type=int, default=5, help='Delay between uploads in seconds')
    parser.add_argument('--skip-videos', action='store_true', help='Skip video downloading and only update channel info')
    parser.add_argument('--skip-channel-update', action='store_true', help='Skip channel info update')
    parser.add_argument('--keep-files', action='store_true', help='Keep downloaded files after upload')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--log-file', help='Log to specified file in addition to console')
    parser.add_argument('--youtube-api-key', help='YouTube Data API v3 key (optional)')
    parser.add_argument('--fetch-method', choices=['youtube-api', 'web-scraping', 'youtube-dl', 'invidious', 'fallback'], 
                      default='fallback', help='Method to fetch YouTube channel info')
    args = parser.parse_args()
    
    # Configure additional logging options
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
    
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {args.log_file}")
    
    logger.info(f"Starting YouTube to MediaCMS backup process")
    
    # Get channel information using the selected method
    if not args.skip_channel_update:
        try:
            # Choose the appropriate channel info fetching method
            channel_info = None
            
            if args.fetch_method == 'youtube-api':
                if not args.youtube_api_key:
                    logger.error("YouTube API key is required when using youtube-api method")
                    return
                channel_info = get_channel_info_youtube_api(args.youtube_api_key, args.channel)
            elif args.fetch_method == 'web-scraping':
                channel_info = get_channel_info_web_scraping(args.channel)
            elif args.fetch_method == 'youtube-dl':
                channel_info = get_channel_info_youtube_dl(args.channel)
            elif args.fetch_method == 'invidious':
                channel_info = get_channel_info_invidious(args.channel)
            else:  # fallback method
                logger.info("Using fallback method to fetch channel info")
                channel_info = get_channel_info_fallback(args.channel)
            
            if channel_info:
                logger.info(f"Channel info retrieved for: {channel_info['channel_name']}")
                update_mediacms_channel(args.mediacms_url, args.token, channel_info)
            else:
                logger.error("Could not fetch channel information with any method.")
                if args.skip_videos:
                    return  # Nothing to do if skipping videos and channel update failed
        except Exception as e:
            logger.error(f"Error during channel update: {e}")
            if args.skip_videos:
                return
    
    if args.skip_videos:
        logger.info("Skipping video download and upload as requested.")
        return
    
    logger.info(f"Starting video backup process for channel: {args.channel}")
    
    # Download videos from YouTube (sorted by upload date - oldest first)
    video_files = download_youtube_videos(args.channel, args.output_dir, args.since)
    
    if not video_files:
        logger.warning("No videos found or downloaded.")
        return
    
    logger.info(f"Processing {len(video_files)} videos for upload to MediaCMS")
    
    # Upload each video to MediaCMS
    success_count = 0
    fail_count = 0
    
    for index, video_file in enumerate(video_files, 1):
        logger.info(f"Processing video {index}/{len(video_files)}: {os.path.basename(video_file)}")
        
        # Extract metadata from corresponding JSON file
        json_file = video_file.rsplit('.', 1)[0] + '.info.json'
        metadata = get_video_metadata(json_file) if os.path.exists(json_file) else None
        
        # Upload video with metadata
        success = upload_to_mediacms(
            video_file, 
            args.mediacms_url, 
            args.token, 
            metadata, 
            cleanup=(not args.keep_files)
        )
        
        if success:
            success_count += 1
            if args.delay > 0 and index < len(video_files):
                logger.info(f"Waiting {args.delay} seconds before next upload...")
                time.sleep(args.delay)
        else:
            fail_count += 1
    
    logger.info(f"Backup process completed. Successfully uploaded {success_count} videos. Failed: {fail_count}")
    if not args.keep_files and success_count > 0:
        logger.info(f"All successfully uploaded files have been cleaned up.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
