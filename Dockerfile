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

CMD python yt2mediacms.py