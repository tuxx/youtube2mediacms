#!/usr/bin/env python3
"""
YouTube to MediaCMS Backup Script

This script downloads videos from a YouTube channel or from a list of video IDs provided via --video-ids.
It converts each video ID to a full YouTube URL using the format:
    https://youtube.com/watch?v={video_id}
This allows downloading both standard videos and YouTube Shorts.
The script uploads the downloaded videos to a MediaCMS instance, preserves original publish dates,
updates the MediaCMS channel with the YouTube channel description (channel mode only),
and cleans up local files after a successful upload.

Requires: yt-dlp, requests, google-api-python-client
Installation: pip install yt-dlp requests google-api-python-client
"""

import os
import sys
import argparse
import json
import time
from subprocess import run, PIPE, Popen, STDOUT
import requests
import logging
import googleapiclient.discovery  # For YouTube API


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('youtube-to-mediacms')


def get_channel_info_youtube_api(channel_id, api_key):
    logger.info(f"Fetching channel information via YouTube API: {channel_id}")

    if not channel_id:
        logger.error("Channel ID is None. Cannot fetch channel information.")
        return None

    youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=api_key)

    try:
        request = youtube.channels().list(part='snippet', id=channel_id)
        response = request.execute()

        if 'items' not in response or not response['items']:
            logger.error("No channel information found.")
            return None

        item = response['items'][0]
        snippet = item['snippet']
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


def get_mediacms_username(mediacms_url, token):
    """
    Fetch the MediaCMS username via the /api/v1/whoami endpoint.
    The returned JSON includes a 'username' field.
    """
    whoami_url = f"{mediacms_url.rstrip('/')}/api/v1/whoami"
    headers = {
        'Authorization': f'Token {token}',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.get(whoami_url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            username = data.get('username')
            logger.info(f"Retrieved MediaCMS username: {username}")
            return username
        else:
            logger.error(f"Failed to get MediaCMS username: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exception while fetching MediaCMS username: {e}")
        return None


def update_mediacms_channel(mediacms_url, token, channel_info, mediacms_username):
    """
    Update the MediaCMS channel (user profile) using a POST request on:
        /api/v1/users/{username}

    This function sends a multipart/form-data request with:
      - a "name" field (set to the YouTube channel's name),
      - a "description" field (using <br /> as newlines instead of \n), and
      - a "logo" field using the image fetched from the YouTube channel metadata.
    """
    logger.info("Updating MediaCMS channel with YouTube channel information...")
    update_url = f"{mediacms_url.rstrip('/')}/api/v1/users/{mediacms_username}"

    headers = {
        'Authorization': f'Token {token}',
        'accept': 'application/json'
    }

    description_value = f"{channel_info['channel_description']}"

    # Prepare multipart fields.
    files = {
        'name': (None, channel_info['channel_name']),
        'description': (None, description_value)
    }

    # Fetch the logo image from YouTube metadata.
    try:
        logo_response = requests.get(channel_info['channel_image_url'], timeout=30)
        if logo_response.status_code == 200:
            logo_content = logo_response.content
            logo_filename = "logo.jpg"  # Adjust extension if needed.
            logo_mime = logo_response.headers.get('Content-Type', 'image/jpeg')
            logger.info("Fetched logo image from YouTube metadata.")
        else:
            logger.warning(f"Failed to fetch logo from {channel_info['channel_image_url']}: {logo_response.status_code}")
            logo_content = None
    except Exception as e:
        logger.error(f"Exception fetching logo: {e}")
        logo_content = None

    if logo_content:
        files['logo'] = (logo_filename, logo_content, logo_mime)

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


def download_youtube_videos(urls, output_dir, since_date=None):
    """
    Download videos from a YouTube channel, a single video, or a list of videos using yt-dlp.
    If 'urls' is a list, each element should be a full YouTube URL.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")

    if isinstance(urls, list):
        logger.info("Starting download of videos for provided URLs.")
    else:
        logger.info(f"Starting download of videos from: {urls}")

    if since_date:
        logger.info(f"Only downloading videos published after: {since_date}")

    cmd = [
        'yt-dlp',
        '--ignore-errors',
        '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '--merge-output-format', 'mp4',
        '--postprocessor-args', '-c copy',
        '--write-info-json',
        '--write-thumbnail',
        '--restrict-filenames',
        '--progress',
        '--no-colors',
        '-o', f'{output_dir}/%(upload_date)s-%(title)s-%(id)s.%(ext)s'
    ]

    if since_date:
        cmd.extend(['--dateafter', since_date])

    # For channel URLs, add --playlist-reverse. For a list of video URLs, skip it.
    if isinstance(urls, list):
        cmd.extend(urls)
    else:
        cmd.extend(['--playlist-reverse', urls])

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
        logger.error(f"yt-dlp process exited with code {return_code}")

    video_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
    video_files.sort()

    full_paths = [os.path.join(output_dir, f) for f in video_files]
    logger.info(f"Downloaded {len(full_paths)} videos")

    return full_paths


def get_video_metadata(json_file):
    """Extract relevant metadata from yt-dlp JSON file."""
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

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
    """Upload a video to MediaCMS instance and set the original publish date."""
    upload_url = f"{mediacms_url.rstrip('/')}/api/v1/media/"

    headers = {
        'Authorization': f'Token {token}'
    }

    if metadata is None:
        metadata = {}

    if 'title' not in metadata:
        metadata['title'] = os.path.basename(video_file).split('.')[0]

    file_size = os.path.getsize(video_file)
    file_size_human = f"{file_size / (1024 * 1024):.2f} MB"

    logger.info(f"Uploading {metadata['title']} ({file_size_human}) to MediaCMS...")

    data = {
        'title': metadata.get('title', ''),
        'description': metadata.get('description', ''),
        'tags': ','.join(metadata.get('tags', [])),
    }

    if metadata.get('upload_date'):
        data['publication_date'] = metadata['upload_date']

    with open(video_file, 'rb') as f:
        files = {'media_file': f}

        thumbnail_path = video_file.rsplit('.', 1)[0] + '.jpg'
        if os.path.exists(thumbnail_path):
            logger.info(f"Including thumbnail: {thumbnail_path}")
            files['thumbnail'] = open(thumbnail_path, 'rb')

        logger.info(f"Starting upload to {upload_url}...")

        try:
            response = requests.post(upload_url, headers=headers, data=data, files=files)
        except Exception as e:
            logger.error(f"Exception during upload: {e}")
            if 'thumbnail' in files:
                files['thumbnail'].close()
            return False

        if 'thumbnail' in files:
            files['thumbnail'].close()

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


def main():
    parser = argparse.ArgumentParser(description='Backup YouTube channel or videos to MediaCMS')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--channel', help='YouTube channel URL or ID (channel mode)')
    group.add_argument('--video-ids', nargs='+', help='One or more YouTube video IDs to download (each will be converted to https://youtube.com/watch?v={video_id})')
    parser.add_argument('--yt-api-key', help='YouTube API key (required for channel mode)')
    parser.add_argument('--mediacms-url', required=True, help='MediaCMS instance URL')
    parser.add_argument('--token', required=True, help='MediaCMS API token')
    parser.add_argument('--since', help='Only download videos after this date (YYYYMMDD)')
    parser.add_argument('--delay', type=int, default=5, help='Delay between uploads in seconds')
    parser.add_argument('--skip-videos', action='store_true', help='Skip video downloading and only update channel info (channel mode only)')
    parser.add_argument('--skip-channel-update', action='store_true', help='Skip channel info update (channel mode only)')
    parser.add_argument('--keep-files', action='store_true', help='Keep downloaded files after upload')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--log-file', help='Log to specified file in addition to console')
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {args.log_file}")

    logger.info("Starting YouTube to MediaCMS backup process")

    if args.video_ids:
        logger.info("Video IDs mode enabled. Skipping channel info update.")
        # Convert each video ID to a full URL.
        video_urls = [f"https://youtube.com/watch?v={vid}" for vid in args.video_ids]
        video_files = download_youtube_videos(video_urls, './youtube_downloads', args.since)
    else:
        # Channel mode
        if not args.skip_channel_update:
            if not args.yt_api_key:
                logger.error("YouTube API key is required for channel mode.")
                sys.exit(1)
            if "youtube.com/channel/" in args.channel:
                channel_id = args.channel.split("youtube.com/channel/")[1].split("/")[0]
            else:
                channel_id = args.channel
            logger.debug(f"Using channel ID: {channel_id}")
            channel_info = get_channel_info_youtube_api(channel_id, args.yt_api_key)
            if channel_info:
                logger.info(f"Channel info retrieved for: {channel_info['channel_name']}")
                mediacms_username = get_mediacms_username(args.mediacms_url, args.token)
                if not mediacms_username:
                    logger.error("Could not retrieve MediaCMS username; aborting update.")
                    return
                update_mediacms_channel(args.mediacms_url, args.token, channel_info, mediacms_username)
            else:
                logger.error("Could not fetch channel information.")
                if args.skip_videos:
                    return

        if args.skip_videos:
            logger.info("Skipping video download and upload as requested.")
            return

        logger.info(f"Starting video backup process for channel: {args.channel}")
        video_files = download_youtube_videos(args.channel, './youtube_downloads', args.since)

    if not video_files:
        logger.warning("No videos found or downloaded.")
        return

    logger.info(f"Processing {len(video_files)} videos for upload to MediaCMS")
    success_count = 0
    fail_count = 0

    for index, video_file in enumerate(video_files, 1):
        logger.info(f"Processing video {index}/{len(video_files)}: {os.path.basename(video_file)}")
        json_file = video_file.rsplit('.', 1)[0] + '.info.json'
        metadata = get_video_metadata(json_file) if os.path.exists(json_file) else None
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
        logger.info("All successfully uploaded files have been cleaned up.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
