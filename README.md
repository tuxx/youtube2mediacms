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

## Usage

Official docker image: [Docker Image](https://hub.docker.com/repository/docker/tuxxness/youtube2mediacms/general)

### With Docker

#### Requirements
- docker installed on your system. [Instructions](https://www.docker.com/get-started/)
- YouTube Data API v3 api key [Instructions](#youtube-data-api-v3-key)

#### Minimal
```bash
docker run -e CHANNEL_URL="your_channel_url" \
           -e YT_API_KEY="your_api_key" \
           -e MEDIACMS_URL="your_mediacms_url" \
           -e TOKEN="your_token" \
          tuxxness/youtube2mediacms:latest 
```

#### Saving the downloaded videos to a local directory
```bash
docker run -e CHANNEL_URL="your_channel_url" \
           -e YT_API_KEY="your_api_key" \
           -e MEDIACMS_URL="your_mediacms_url" \
           -e TOKEN="your_token" \
           -v ./youtube_downloads:/app/youtube_downloads \ # Using a volume to keep the downloaded videos when the container stops.
          tuxxness/youtube2mediacms:latest 
```

#### All the environment variables
```bash
docker run -e CHANNEL_URL="your_channel_url" \
           -e YT_API_KEY="your_api_key" \
           -e MEDIACMS_URL="your_mediacms_url" \
           -e TOKEN="your_token" \
           -e SINCE="20230101" \  # Optional: specify if you want to filter by date
           -e DELAY="5" \         # Optional: specify delay between uploads
           -e SKIP_VIDEOS="True" \  # Set to True to skip video downloads
           -e SKIP_CHANNEL_UPDATE="False" \  # Set to False to not skip channel update
           -e KEEP_FILES="False" \  # Set to False to not keep downloaded files
           -e VERBOSE="True" \      # Set to True for verbose output
           -e LOG_FILE="log.txt" \  # Optional: specify a log file
          tuxxness/youtube2mediacms:latest 
```

### Environment Variables
The following environment variables can be set to customize the behavior of the yt2mediacms script:

| Variable | Required | Default Value | Description |
|-------------------------|----------|---------------|--------------------------------------------------------------|
| CHANNEL_URL | Yes | - | YouTube channel URL or ID |
| YT_API_KEY | Yes | - | YouTube Data API v3 key |
| MEDIACMS_URL | Yes | - | MediaCMS instance URL |
| TOKEN | Yes | - | MediaCMS API token |
| SINCE | No | - | Only download videos published after this date (YYYYMMDD) |
| DELAY | No | 5 | Delay between uploads in seconds |
| SKIP_VIDEOS | No | False | Set to True to skip video downloading |
| SKIP_CHANNEL_UPDATE | No | False | Set to True to skip updating channel information |
| KEEP_FILES | No | False | Set to True to keep downloaded files after upload |
| VERBOSE | No | False | Set to True to enable verbose output |
| LOG_FILE | No | - | Specify a log file to log output in addition to the console |


## Development

#### Requirements
- Python 3.x
  - `requests` for MediaCMS API communication
  - `google-api-python-client` for YouTube API interactions
- `yt-dlp` installed on your system.
- YouTube Data API v3 api key [Instructions](#youtube-data-api-v3-key)

#### Arch Linux

`pacman -S yt-dlp`

#### Debian Derivates

`apt install yt-dlp`

#### Installing python stuff
```bash
git clone https://github.com/tuxx/youtube2mediacms
cd youtube2mediacms
python3 -m venv virtual
source virtual/bin/activate
pip install -r requirements.txt
```

#### Running the code
```bash
python yt2mediacms.py --channel CHANNEL_URL --yt-api-key YOUTUBE_API_KEY --mediacms-url MEDIACMS_URL --token MEDIACMS_API_TOKEN
```

##### Command Line Arguments

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

## Youtube Data API v3 key

### Step 1: Create a Google Cloud Project
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. If you don’t have a project yet, create a new one:
     - Click on the project dropdown (top left) → **New Project**.
     - Give it a name and click **Create**.

### Step 2: Enable the YouTube API
1. In the Cloud Console, go to **APIs & Services** → **Library**.
2. Search for **YouTube Data API v3** and click on it.
3. Click **Enable**.

### Step 3: Generate an API Key
1. Go to **APIs & Services** → **Credentials**.
2. Click **Create Credentials** → **API Key**.
3. Your API key will be generated. Copy and save it.
