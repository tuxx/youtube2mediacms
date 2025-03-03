# Use the official Python image based on Alpine
FROM python:3.11-alpine

# Set the working directory
WORKDIR /app

# Install yt-dlp and other dependencies
RUN apk add --no-cache ffmpeg  # Install ffmpeg for video processing
RUN pip install --no-cache-dir yt-dlp

# Copy the requirements file and install other dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python script and any other necessary files
COPY yt2mediacms.py .

# Set environment variables for command line arguments
ENV CHANNEL_URL=""
ENV YT_API_KEY=""
ENV MEDIACMS_URL=""
ENV TOKEN=""
ENV SINCE=""
ENV DELAY="5"
ENV SKIP_VIDEOS=""
ENV SKIP_CHANNEL_UPDATE=""
ENV KEEP_FILES=""
ENV VERBOSE=""
ENV LOG_FILE=""

# Command to run the Python script using shell form for variable expansion
CMD python yt2mediacms.py \
    --channel "$CHANNEL_URL" \
    --yt-api-key "$YT_API_KEY" \
    --mediacms-url "$MEDIACMS_URL" \
    --token "$TOKEN" \
    --since "$SINCE" \
    --delay "$DELAY" \
    $(if [ "$SKIP_VIDEOS" = "True" ]; then echo "--skip-videos"; fi) \
    $(if [ "$SKIP_CHANNEL_UPDATE" = "True" ]; then echo "--skip-channel-update"; fi) \
    $(if [ "$KEEP_FILES" = "True" ]; then echo "--keep-files"; fi) \
    $(if [ "$VERBOSE" = "True" ]; then echo "--verbose"; fi) \
    --log-file "$LOG_FILE"