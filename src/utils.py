import os
import logging

logger = logging.getLogger('yt2mediacms')

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
