# YouTube to MediaCMS Backup Script
This script allows you to back up your own YouTube videos to a MediaCMS instance. It downloads videos from a specified YouTube channel, extracts metadata, and uploads them to MediaCMS for archival and streaming.

## ⚠️ Important Notice
This script is intended only for backing up videos you own (e.g., your personal YouTube channel content). Do not use it to download or upload copyrighted content that you do not have permission to redistribute. Unauthorized copying of copyrighted material may violate YouTube’s Terms of Service and copyright laws.

## Features
- ✅ Fetches channel metadata and updates MediaCMS profile
- ✅ Downloads videos in the best available format (MP4)
- ✅ Extracts and uploads video metadata (title, description, tags)
- ✅ Saves thumbnails and uploads them to MediaCMS
- ✅ Displays real-time progress, folder size, and error handling

## Requirements
- Python 3.x
- yt-dlp for video downloading
- requests for MediaCMS API communication

## Installation
```
pip install yt-dlp requests
```

## Usage

### Minimal
```
python yt2mediacms.py --channel "https://www.youtube.com/c/YOUR_CHANNEL" \
                      --mediacms-url "https://your-mediacms-instance.com" \
                      --token "your_mediacms_api_token" 
```


### All options
```
python yt2mediacms.py --channel "https://www.youtube.com/c/YOUR_CHANNEL" \
                      --mediacms-url "https://your-mediacms-instance.com" \
                      --token "your_mediacms_api_token" \
                      --since YYYYMMDD # (optional) \
                      --delay 5 # (optional) \
                      --skip-videos # Only update channel information (optional) \
                      --skip-channel-update # Do not update the channel information (optional) \
                      --keep-files # Keep the locally downloaded files (optional) \
                      --verbose # Add more verbosity to the output (optional) \
                      --logfile yt2mediacms.log # Keep the output in a file (optional) \
                      --output-dir "./youtube_downloads" # (optional)
```

For more details, check out the script in the repository! 🚀
