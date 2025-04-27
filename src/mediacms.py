import os
import requests
import logging
import time
import json

logger = logging.getLogger('yt2mediacms')

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
    Now checks the encoding status of the resolution that matches the original video height.
    
    Returns:
    - str: "success" if all relevant encodings are complete, "running" if any are still running,
           "pending" if any are pending, "fail" if any failed, or None if not found
    """
    # Define all possible resolutions in descending order
    resolutions = ["2160", "1440", "1080", "720", "480", "360", "240"]
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
        
        # Check the top-level encoding_status
        overall_status = data.get("encoding_status")
        
        # If the top-level status is "running" or "pending", return that immediately
        if overall_status in ["running", "pending"]:
            return overall_status
            
        # Get the original video height to know which resolution to check
        original_height = data.get("video_height", 0)
        logger.debug(f"Original video height: {original_height}")
        
        # Get all encoding info
        encodings_info = data.get("encodings_info", {})
        
        # Determine target resolution to check based on original height
        target_resolution = resolutions[-1]  # Default to lowest resolution
        
        for resolution in resolutions[:-1]:  # Check all except the lowest
            if original_height >= int(resolution):
                target_resolution = resolution
                break
            
        logger.debug(f"Target resolution to check: {target_resolution}")
        
        # Check if there is encoding info for target resolution
        target_encoding = encodings_info.get(target_resolution, {})
        
        # If the target resolution encoding is empty, check if it's expected
        if not target_encoding:
            # If the server doesn't encode to this resolution, check the highest available
            # Use the same ordered list of resolutions defined at the top of the function
            available_resolutions = [r for r in resolutions if encodings_info.get(r)]
            
            if available_resolutions:
                highest_resolution = available_resolutions[0]  # First is highest due to order
                logger.debug(f"Target resolution {target_resolution} not found, checking highest available: {highest_resolution}")
                
                # Check if the highest available resolution is still encoding
                highest_encoding = encodings_info.get(highest_resolution, {}).get("h264", {})
                if highest_encoding:
                    highest_status = highest_encoding.get("status")
                    if highest_status != "success":
                        logger.debug(f"Highest resolution ({highest_resolution}) status: {highest_status}")
                        return highest_status
                
                # Check lower resolutions too, just to be safe
                for res in available_resolutions[1:]:  # Skip the highest we already checked
                    res_encoding = encodings_info.get(res, {}).get("h264", {})
                    if res_encoding and res_encoding.get("status") != "success":
                        logger.debug(f"Resolution {res} is still encoding with status: {res_encoding.get('status')}")
                        return res_encoding.get("status")
                
                # If we've checked all available resolutions and they're complete
                return "success"
            else:
                # No resolution encodings found - unusual, but default to overall status
                return overall_status
        
        # Check the status of the target resolution
        target_h264 = target_encoding.get("h264", {})
        if target_h264:
            target_status = target_h264.get("status")
            if target_status:
                logger.debug(f"Target resolution {target_resolution} status: {target_status}")
                return target_status
            
        # If we get here, fall back to the overall status
        logger.debug(f"Falling back to overall encoding status: {overall_status}")
        return overall_status
    
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
