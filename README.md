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
- beautifulsoup4 for web scraping youtube channel

## Installation
```
git clone https://github.com/tuxx/youtube2mediacms
cd youtube2mediacms
pip install -r requirements.txt
```

## Usage
```
python yt2mediacms.py --channel CHANNEL_URL --mediacms-url MEDIACMS_URL --token MEDIACMS_API_TOKEN
```

### Command Line Arguments

| Argument | Required | Default | Description |
|----------|:--------:|:-------:|-------------|
| `--channel` | Yes | - | YouTube channel URL |
| `--mediacms-url` | Yes | - | MediaCMS instance URL |
| `--token` | Yes | - | MediaCMS API token |
| `--output-dir` | No | `./youtube_downloads` | Directory to store downloads |
| `--since` | No | - | Only download videos after this date (YYYYMMDD) |
| `--delay` | No | `5` | Delay between uploads in seconds |
| `--skip-videos` | No | `False` | Skip video downloading and only update channel info |
| `--skip-channel-update` | No | `False` | Skip channel info update |
| `--keep-files` | No | `False` | Keep downloaded files after upload |
| `--verbose`, `-v` | No | `False` | Enable verbose output |
| `--log-file` | No | - | Log to specified file in addition to console |
| `--youtube-api-key` | No | - | YouTube Data API v3 key (optional) |
| `--fetch-method` | No | `fallback` | Method to fetch YouTube channel info. Options: `youtube-api`, `web-scraping`, `youtube-dl`, `invidious`, `fallback` |

### Examples

Download all videos from a channel:
```bash
python main.py --channel https://www.youtube.com/c/ChannelName --mediacms-url https://your-mediacms.com --token MEDIACMS_API_TOKEN
```

Download only videos published after January 1, 2023:
```bash
python main.py --channel https://www.youtube.com/c/ChannelName --mediacms-url https://your-mediacms.com --token MEDIACMS_API_TOKEN --since 20230101
```

Skip video downloads and only update channel information:
```bash
python main.py --channel https://www.youtube.com/c/ChannelName --mediacms-url https://your-mediacms.com --token MEDIACMS_API_TOKEN --skip-videos
```

For more details, check out the script in the repository! 🚀
