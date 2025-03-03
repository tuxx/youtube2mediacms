# YouTube to MediaCMS Backup Script

This script allows you to back up your own YouTube videos to a MediaCMS instance. It downloads videos from a specified YouTube channel, extracts metadata, and uploads them to MediaCMS for archival and streaming. Additionally, it updates the MediaCMS user profile with YouTube channel metadata.

## ⚠️ Important Notice
This script is intended only for backing up videos you own (e.g., your personal YouTube channel content). Do not use it to download or upload copyrighted content that you do not have permission to redistribute. Unauthorized copying of copyrighted material may violate YouTube’s Terms of Service and copyright laws.

## Features
- ✅ Fetches channel metadata using the YouTube API and updates MediaCMS profile
- ✅ Downloads videos in the best available format (MP4)
- ✅ Extracts and uploads video metadata (title, description, tags, upload date)
- ✅ Saves thumbnails and uploads them to MediaCMS
- ✅ Displays real-time progress, folder size, and error handling
- ✅ Cleans up downloaded files after successful upload (optional)

## Requirements
- Python 3.x
  - `requests` for MediaCMS API communication
  - `google-api-python-client` for YouTube API interactions
- `yt-dlp` installed on your system.
- YouTube Data API v3 api key [Instructions](#youtube-data-api-v3-key)


## Installation

**Arch Linux**

`pacman -S yt-dlp`

**Debian Derivates**

`apt install yt-dlp`

**Running the code**
```bash
git clone https://github.com/tuxx/youtube2mediacms
cd youtube2mediacms
pip install -r requirements.txt
```

## Usage
```bash
python yt2mediacms.py --channel CHANNEL_URL --yt-api-key YOUTUBE_API_KEY --mediacms-url MEDIACMS_URL --token MEDIACMS_API_TOKEN
```

### Command Line Arguments

| Argument | Required | Default | Description |
|----------|:--------:|:-------:|-------------|
| `--channel` | Yes | - | YouTube channel URL or ID |
| `--yt-api-key` | Yes | - | YouTube Data API v3 key |
| `--mediacms-url` | Yes | - | MediaCMS instance URL |
| `--token` | Yes | - | MediaCMS API token |
| `--since` | No | - | Only download videos after this date (YYYYMMDD) |
| `--delay` | No | `5` | Delay between uploads in seconds |
| `--skip-videos` | No | `False` | Skip video downloading and only update channel info |
| `--skip-channel-update` | No | `False` | Skip channel info update |
| `--keep-files` | No | `False` | Keep downloaded files after upload |
| `--verbose`, `-v` | No | `False` | Enable verbose output |
| `--log-file` | No | - | Log to specified file in addition to console |

### Examples

Download all videos from a channel:
```bash
python yt2mediacms.py --channel https://www.youtube.com/c/ChannelID --yt-api-key YOUR_YT_API_KEY --mediacms-url https://your-mediacms.com --token MEDIACMS_API_TOKEN
```

Download only videos published after January 1, 2023:
```bash
python yt2mediacms.py --channel https://www.youtube.com/c/ChannelID --yt-api-key YOUR_YT_API_KEY --mediacms-url https://your-mediacms.com --token MEDIACMS_API_TOKEN --since 20230101
```

Skip video downloads and only update channel information:
```bash
python yt2mediacms.py --channel https://www.youtube.com/c/ChannelID --yt-api-key YOUR_YT_API_KEY --mediacms-url https://your-mediacms.com --token MEDIACMS_API_TOKEN --skip-videos
```

## Youtube Data API v3 key

#### Step 1: Create a Google Cloud Project
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. If you don’t have a project yet, create a new one:
     - Click on the project dropdown (top left) → **New Project**.
     - Give it a name and click **Create**.

#### Step 2: Enable the YouTube API
1. In the Cloud Console, go to **APIs & Services** → **Library**.
2. Search for **YouTube Data API v3** and click on it.
3. Click **Enable**.

### Step 3: Generate an API Key
1. Go to **APIs & Services** → **Credentials**.
2. Click **Create Credentials** → **API Key**.
3. Your API key will be generated. Copy and save it.
