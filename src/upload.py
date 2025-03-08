import queue
import threading
import time
import logging
import os
from datetime import datetime

logger = logging.getLogger('yt2mediacms')

# Import functions from other modules
from .tui import is_tui_enabled
from .mediacms import (
    get_mediacms_username, 
    upload_to_mediacms, 
    check_video_encoding_status
)

class UploadManager:
    """
    Manages video uploads with encoding status tracking
    """
    def __init__(self, mediacms_url, token, keep_files=False, num_workers=1, wait_for_encoding=True, delay=5):
        self.mediacms_url = mediacms_url
        self.token = token
        self.keep_files = keep_files
        self.num_workers = num_workers
        self.wait_for_encoding = wait_for_encoding
        self.delay = delay
        self.username = None
        self.queue = queue.Queue()
        self.workers = []
        self.lock = threading.Lock()
        
        # Track most recently uploaded videos per thread (friendly_token)
        self.last_uploads = {}
        
        # Number of completed uploads
        self.completed_uploads = 0
    
    def start(self):
        """Start the upload worker threads"""
        # Get the MediaCMS username first
        self.username = get_mediacms_username(self.mediacms_url, self.token)
        if not self.username:
            logger.error("Could not determine MediaCMS username for upload manager")
            return False
        
        logger.info(f"Starting {self.num_workers} upload worker(s) for user: {self.username}")
        
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._upload_worker,
                args=(i+1,),
                daemon=True
            )
            self.workers.append(worker)
            worker.start()
            logger.info(f"Started upload worker {i+1}")
            
        return True
    
    def add_video(self, video_file, metadata=None):
        """Add a video to the upload queue"""
        self.queue.put({
            'video_file': video_file,
            'metadata': metadata or {}
        })
    
    def wait(self):
        """Wait for all uploads to complete"""
        self.queue.join()
        logger.info(f"All uploads completed. Total: {self.completed_uploads}")
    
    def _upload_worker(self, worker_id):
        """Worker thread function for uploading videos"""
        thread_name = f"Upload-{worker_id}"
        last_token = None
        
        if is_tui_enabled():
            tui_manager.update_upload_thread(thread_name, "started")
        
        while True:
            try:
                # Before getting a new video, check if we need to wait for encoding
                if self.wait_for_encoding and last_token:
                    # Check encoding status in a loop until it's complete
                    logger.info(f"{thread_name}: Checking if previous video {last_token} has finished encoding")
                    
                    while True:  # Keep checking until encoding is complete
                        # Check if the previous upload is done encoding
                        encoding_status = check_video_encoding_status(
                            self.mediacms_url, 
                            self.token, 
                            last_token
                        )
                        
                        if is_tui_enabled():
                            tui_manager.update_upload_thread(
                                thread_name,
                                "waiting",
                                f"MC:{last_token}",
                                encoding_status=encoding_status
                            )
                        
                        # Log the encoding status with more detail
                        logger.info(f"{thread_name}: Video {last_token} encoding status: {encoding_status}")
                        
                        if encoding_status in ["success", "fail"]:
                            # Encoding is complete (success or failed), proceed with next upload
                            logger.info(f"{thread_name}: Previous video {last_token} encoding {encoding_status}, proceeding to next upload")
                            last_token = None
                            break
                        elif encoding_status in ["running", "pending"]:
                            # Still encoding, wait and check again
                            logger.info(f"{thread_name}: Waiting for video {last_token} to finish encoding (status: {encoding_status})")
                            time.sleep(self.delay)
                            continue
                        else:
                            # Unknown status or None, wait a bit and retry
                            logger.warning(f"{thread_name}: Unknown encoding status '{encoding_status}' for {last_token}, waiting before retry")
                            time.sleep(self.delay)
                            continue
                
                # Get a video from the queue with timeout
                try:
                    video_item = self.queue.get(timeout=5)
                except queue.Empty:
                    continue
                
                video_file = video_item['video_file']
                metadata = video_item['metadata']
                
                # Extract video ID from filename
                video_id = os.path.basename(video_file).split('-')[-1].split('.')[0]
                
                if is_tui_enabled():
                    tui_manager.update_upload_thread(
                        thread_name,
                        "uploading",
                        video_id
                    )
                
                # Upload the video
                logger.info(f"{thread_name}: Uploading video: {video_id}")
                success, friendly_token = upload_to_mediacms(
                    video_file, 
                    self.mediacms_url, 
                    self.token, 
                    metadata, 
                    cleanup=(not self.keep_files)
                )
                
                if success:
                    logger.info(f"{thread_name}: Successfully uploaded {video_id} (token: {friendly_token})")
                    
                    # Record the friendly token for encoding status tracking
                    if friendly_token:
                        # Store this token as the one we need to wait for
                        last_token = friendly_token
                        
                        with self.lock:
                            self.last_uploads[thread_name] = friendly_token
                            self.completed_uploads += 1
                    
                    if is_tui_enabled():
                        tui_manager.update_upload_thread(
                            thread_name,
                            "uploaded",
                            video_id,
                            encoding_status="pending"
                        )
                else:
                    logger.error(f"{thread_name}: Failed to upload {video_id}")
                    
                    if is_tui_enabled():
                        tui_manager.update_upload_thread(
                            thread_name,
                            "failed",
                            video_id
                        )
                
                # Mark this task as done
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"{thread_name}: Error in upload worker: {e}")
                logger.error(f"Exception details:", exc_info=True)
                
                # Mark the task as done if it failed
                try:
                    self.queue.task_done()
                except:
                    pass

    def monitor_encoding_status(self, interval=10, max_time=3600):
        """
        Start a thread to monitor encoding status of recently uploaded videos.
        This runs as a separate thread to update the TUI with encoding status
        without interfering with the upload workers.
        """
        if not is_tui_enabled():
            return  # Only run when TUI is enabled
            
        def _monitor_thread():
            logger.info("Started encoding status monitor thread")
            end_time = time.time() + max_time
            
            while time.time() < end_time:
                with self.lock:
                    for thread_name, token in list(self.last_uploads.items()):
                        try:
                            status = check_video_encoding_status(
                                self.mediacms_url, 
                                self.token, 
                                token
                            )
                            
                            if status in ["success", "fail"]:
                                # Update the TUI
                                if is_tui_enabled():
                                    tui_manager.update_upload_thread(
                                        thread_name,
                                        "completed",
                                        f"MC:{token}",
                                        encoding_status=status
                                    )
                                
                                # Remove from tracking if done
                                if not self.wait_for_encoding:
                                    self.last_uploads.pop(thread_name, None)
                            else:
                                # Update the TUI with current status
                                if is_tui_enabled():
                                    tui_manager.update_upload_thread(
                                        thread_name,
                                        "waiting",
                                        f"MC:{token}",
                                        encoding_status=status
                                    )
                        except Exception as e:
                            logger.debug(f"Error checking encoding status: {e}")
                
                time.sleep(interval)
                
        # Start the monitor thread
        monitor = threading.Thread(target=_monitor_thread, daemon=True)
        monitor.start()
        return monitor
