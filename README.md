# 📹 YouTube to MediaCMS Sync Script

This script allows you to sync your YouTube videos to a MediaCMS instance. It offers robust channel synchronization, metadata updates, and support for individual video uploads.

## ⚠️ Important Notice
This script is intended only for syncing videos you own (e.g., your personal YouTube channel content). Do not use it to download or upload copyrighted content that you do not have permission to redistribute. Unauthorized copying of copyrighted material may violate YouTube's Terms of Service and copyright laws.

## 🔄 Features
- ✅ Multiple sync modes (full channel, new videos only, selected videos)
- ✅ Channel metadata synchronization from YouTube to MediaCMS
- ✅ Multi-channel support through configuration file
- ✅ Smart video detection to avoid duplicate uploads
- ✅ Preserves video metadata (title, description, tags, upload date)
- ✅ Uploads thumbnails alongside videos
- ✅ Progress reporting and performance metrics

## 🐳 Docker Usage (Recommended)

The easiest way to use this tool is with the official Docker image.

### ⚙️ Configuration

- 🔍 [Finding Your YouTube Channel ID](#Finding-your-YouTube-Channel-ID)
- 🔑 [How to get a YouTube API Key](#youtube-data-api-v3-key)

Create a `config.json` file with your settings:

```json
{
  "mediacms_url": "https://your.mediacms.instance",
  "youtube": {
    "api_key": "your_youtube_api_key",
    "channels": [
      {
        "name": "My Awesome Channel",
        "url": "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxx",
        "mediacms_user": "MediaCMS_Username",
        "mediacms_token": "MediaCMS_API_Token"
      }
    ]
  }
}
```

### 🏃 Running with Docker

Use the official image and mount your config file:

```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --youtube-channel "Channel Name"
```

For large uploads, use `--network host` to improve performance:
```bash
docker run --network host --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --mode full --youtube-channel "Channel Name"
```

To keep downloaded files, mount a directory for the downloads:
```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json -v /path/to/downloads:/app/youtube_downloads tuxxness/youtube2mediacms:latest --keep-files --youtube-channel "Channel Name"
```

### ⏱️ Scheduled Tasks with Docker

For regular synchronization, you can use cron to run the Docker container at set intervals:

```
# Example crontab entry to sync every hour
0 * * * * docker run --rm --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --youtube-channel "Channel Name" >> /path/to/logs/sync.log 2>&1
```

## 📺 Usage Modes

### 🔄 Channel Sync Modes

#### 🆕 Sync new videos only (default mode)
This mode checks the latest video on MediaCMS and only syncs videos published after that date:

```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --youtube-channel "Channel Name"
```

#### 🔄 Full channel sync
This mode attempts to sync all videos from a YouTube channel:

```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --mode full --youtube-channel "Channel Name"
```

#### 🏷️️ Update channel metadata only
Only update the MediaCMS channel profile with YouTube channel details:

```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --update-channel "Channel Name"
```

To update all configured channels:
```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --update-channel
```

### 🎬 Individual Video Upload

To upload specific videos by their YouTube IDs:

```bash
docker run --pull always -v /path/to/your/config.json:/app/config.json tuxxness/youtube2mediacms:latest --video-ids "video_id1" "video_id2" --mediacms-username "Username"
```

## 🐳 Docker Compose

You can also use Docker Compose to run the YouTube to MediaCMS backup script. This is especially useful for scheduled backups or if you're running multiple services.

### 📋 Get the docker-compose.yml and config.json

- ⚙️ [config.json explanation](#⚙️configuration)

```bash
wget https://raw.githubusercontent.com/tuxx/youtube2mediacms/refs/heads/master/docker-compose.yml
wget -O config.json https://raw.githubusercontent.com/tuxx/youtube2mediacms/refs/heads/master/config.json.example
```

### 🚀 Usage

1. **Run the container**:
   ```bash
   docker-compose up
   ```

2. **For scheduled backups**:
   - Set up a cron job to run the container periodically:
   ```bash
   # Run every day at 2 AM
   0 2 * * * cd /path/to/docker-compose && docker-compose up >> backup.log 2>&1
   ```

### 💾 Persistent Storage

By mounting the `youtube_downloads` directory as a volume, you can preserve downloaded videos even after the container exits:

```yaml
volumes:
  - ./config.json:/app/config.json
  - ./downloads:/app/youtube_downloads
```

Don't forget to add the `--keep-files` flag to your command to prevent automatic cleanup of downloaded files.

## 🛠️ Command Line Arguments

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `--mode` | Sync mode: "new" or "full" | "new" | No |
| `--video-ids` | List of YouTube video IDs to download | None | Yes, for video ID mode |
| `--update-channel` | Update channel metadata. Optional channel name for specific channel | None | Yes, for metadata mode |
| `--config` | Path to config file | "config.json" | No |
| `--mediacms-url` | Override MediaCMS URL from config | From config | No |
| `--delay` | Seconds to wait between uploads | 5 | No |
| `--keep-files` | Don't delete downloaded files after upload | False | No |
| `--mediacms-username` | Target MediaCMS username for video-ids mode | None | Yes, for video ID mode |
| `--youtube-channel` | Only operate on channel with this name | All channels | No |
| `--verbose`, `-v` | Enable verbose logging | False | No |
| `--log-file` | Write logs to the specified file | None | No |


## 💻 Manual Installation

If you prefer to run the script directly:

### 📋 Requirements
- Python 3.x
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installed on your system
- YouTube Data API v3 key ([Instructions](#youtube-data-api-v3-key))

### 🔧 Setup
```bash
git clone https://github.com/tuxx/youtube2mediacms
cd youtube2mediacms
python3 -m venv virtual
source virtual/bin/activate
pip install -r requirements.txt
```

Create a configuration file by copying the example:
```bash
cp config.json.example config.json
```

Then run the script directly:
```bash
python yt2mediacms.py --youtube-channel "Channel Name"
```

## 🔍 Finding Your YouTube Channel ID

YouTube channel URLs with an alias look like: `https://www.youtube.com/@ChannelName`

However, this script requires the actual channel ID, not the alias. To find the channel ID:

1. Go to your YouTube channel page
2. Click on **...more** in the **description**
3. Scroll down to the **Share Channel** button and click on it
4. Click on **Copy Channel ID**
4. The channel ID will be in the format: `UCxxxxxxxxxxxxxxxxx`

Alternatively, you can use online tools to convert from a channel alias to an ID.

For example, the alias URL `https://www.youtube.com/@youtube` corresponds to the channel ID URL `https://www.youtube.com/channel/UCBR8-60-B28hp2BmDPdntcQ`

**Always use the full channel ID URL format (`https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxx`) in your config file.**



## 🔑 Youtube Data API v3 key

### Step 1: Create a Google Cloud Project
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. If you don't have a project yet, create a new one:
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

