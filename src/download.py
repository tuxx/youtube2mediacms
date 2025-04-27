import os
import threading
import queue
import logging
import subprocess
import json
import time
from datetime import datetime
from .constants import OUTPUT_DIR

logger = logging.getLogger('yt2mediacms')

# Import functions from other modules
from .tui import is_tui_enabled
from .youtube import get_video_metadata

class DownloadManager:
    """
    Manages video downloads using multiple worker threads.
    """
    def __init__(self, output_dir=OUTPUT_DIR, num_workers=1, callback=None):
        self.output_dir = output_dir
        self.num_workers = num_workers
        self.queue = queue.Queue()
        self.callback = callback  # Function to call when a video is downloaded
        self.workers = []
        self.completed = threading.Event()
        self.processed_videos = 0
        self.lock = threading.Lock()
        
        # Ensure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logger.info(f"Created output directory: {self.output_dir}")
    
    def start(self):
        """Start the download worker threads"""
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._download_worker,
                args=(i+1,),
                daemon=True
            )
            self.workers.append(worker)
            worker.start()
            logger.info(f"Started download worker {i+1}")
    
    def add_video(self, video_id):
        """Add a video ID to the download queue"""
        self.queue.put(video_id)
        
    def add_videos(self, video_ids):
        """Add multiple video IDs to the queue"""
        for vid in video_ids:
            self.add_video(vid)
    
    def mark_completed(self):
        """Signal that all videos have been added to the queue"""
        self.completed.set()
    
    def wait(self):
        """Wait for all workers to complete"""
        for worker in self.workers:
            worker.join()
    
    def _download_worker(self, worker_id):
        """Worker thread function for downloading videos"""
        thread_name = f"Download-{worker_id}"
        
        if is_tui_enabled():
            tui_manager.update_download_thread(thread_name, "started")
        
        while not (self.completed.is_set() and self.queue.empty()):
            try:
                # Get a video from the queue with timeout
                try:
                    video_id = self.queue.get(timeout=5)
                except queue.Empty:
                    continue
                
                # Update TUI status
                if is_tui_enabled():
                    tui_manager.update_download_thread(
                        thread_name, 
                        "downloading", 
                        video_id
                    )
                
                # Download the video
                logger.info(f"{thread_name}: Downloading video ID: {video_id}")
                
                # Create a temporary directory for this video
                temp_dir = os.path.join(self.output_dir, video_id)
                os.makedirs(temp_dir, exist_ok=True)
                
                # Prepare download command
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                cmd = [
                    "yt-dlp",
                    "--ignore-errors",
                    "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "--postprocessor-args", "-c copy",
                    "--write-info-json",
                    "--write-thumbnail",
                    "--restrict-filenames",
                    "--no-colors",
                    "-o", f"{temp_dir}/%(upload_date)s-%(title)s-%(id)s.%(ext)s",
                    video_url
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    logger.error(f"{thread_name}: Failed to download {video_id}: {result.stderr}")
                    
                    if is_tui_enabled():
                        tui_manager.update_download_thread(
                            thread_name, 
                            "failed", 
                            video_id
                        )
                        
                    self.queue.task_done()
                    continue
                
                # Find the downloaded MP4 file
                mp4_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
                if not mp4_files:
                    logger.error(f"{thread_name}: No MP4 file found after download for {video_id}")
                    
                    if is_tui_enabled():
                        tui_manager.update_download_thread(
                            thread_name, 
                            "failed", 
                            video_id
                        )
                        
                    self.queue.task_done()
                    continue
                
                video_file = os.path.join(temp_dir, mp4_files[0])
                
                # Check and wait for the metadata file
                metadata = self._wait_for_metadata(video_file)
                
                logger.info(f"{thread_name}: Successfully downloaded {video_id}")
                
                if is_tui_enabled():
                    tui_manager.update_download_thread(
                        thread_name, 
                        "completed", 
                        video_id
                    )
                
                # Increment processed count
                with self.lock:
                    self.processed_videos += 1
                
                # Call the callback if provided
                if self.callback:
                    self.callback(video_file, metadata)
                
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"{thread_name}: Error downloading video: {e}")
                
                if is_tui_enabled():
                    tui_manager.update_download_thread(
                        thread_name, 
                        "error", 
                        video_id if 'video_id' in locals() else None
                    )
                
                # Mark task as done if it failed
                try:
                    self.queue.task_done()
                except:
                    pass
    
    def _wait_for_metadata(self, video_file, max_attempts=5):
        """Wait for the metadata file to be fully written and return it"""
        json_file = video_file.rsplit(".", 1)[0] + ".info.json"
        
        for attempt in range(1, max_attempts + 1):
            if os.path.exists(json_file):
                try:
                    metadata = get_video_metadata(json_file)
                    if metadata and 'title' in metadata:
                        return metadata
                except json.JSONDecodeError:
                    logger.debug(f"Metadata file not fully written yet: {json_file}")
            
            if attempt < max_attempts:
                logger.debug(f"Metadata not ready, attempt {attempt}/{max_attempts}. Waiting...")
                time.sleep(2 * attempt)  # Increasing backoff
                
        logger.warning(f"Could not get metadata after {max_attempts} attempts, using empty metadata")
        return {}
