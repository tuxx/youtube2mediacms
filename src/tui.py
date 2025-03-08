import threading
import logging
import queue
from datetime import datetime

logger = logging.getLogger('yt2mediacms')

# Only attempt imports if we're going to use them
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Global variable for the TUI manager instance
tui_manager = None

class TUIManager:
    """Manages the Text-based User Interface"""
    def __init__(self):
        self.console = Console(highlight=False)
        self.live = None
        self.enabled = False
        self.stats = {
            "videos_downloaded": 0,
            "videos_uploaded": 0,
            "videos_encoding": 0,
            "videos_encoded": 0,
            "start_time": datetime.now(),
            "download_threads": {},
            "upload_threads": {},
            "recent_logs": []
        }
        self.lock = threading.Lock()
        
    def is_enabled(self):
        """Check if TUI is enabled"""
        return self.enabled
            
    def start(self):
        """Start the TUI display"""
        self.layout = self.generate_layout()
        self.live = Live(self.layout, refresh_per_second=2, console=self.console, screen=True)
        self.live.start()
        self.enabled = True
        return self
            
    def stop(self):
        """Stop the TUI display"""
        if self.live:
            try:
                self.live.stop()
            except Exception as e:
                print(f"Error stopping TUI: {e}")
            self.enabled = False

    def log(self, message, level="INFO"):
        """Add a log entry"""
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.stats["recent_logs"].append((timestamp, level, message))
            # Keep only the most recent 10 logs
            if len(self.stats["recent_logs"]) > 10:
                self.stats["recent_logs"].pop(0)
            
            # Update the live display
            if self.live:
                self.live.update(self.generate_layout())
        
    def update_download_thread(self, thread_id, status, video_id=None):
        """Update the status of a download thread"""
        with self.lock:
            self.stats["download_threads"][thread_id] = {
                "status": status,
                "video_id": video_id,
                "updated_at": datetime.now()
            }
            
            if status == "completed" and video_id:
                self.stats["videos_downloaded"] += 1
            
            if self.live:
                self.live.update(self.generate_layout())

    def update_upload_thread(self, thread_id, status, video_id=None, encoding_status=None):
        """Update the status of an upload thread"""
        with self.lock:
            self.stats["upload_threads"][thread_id] = {
                "status": status,
                "video_id": video_id,
                "updated_at": datetime.now(),
                "encoding_status": encoding_status
            }
            
            if status == "uploaded" and video_id:
                self.stats["videos_uploaded"] += 1
                self.stats["videos_encoding"] += 1
            
            if encoding_status == "success" and video_id:
                self.stats["videos_encoded"] += 1
                self.stats["videos_encoding"] = max(0, self.stats["videos_encoding"] - 1)
            
            if self.live:
                self.live.update(self.generate_layout())

    def generate_layout(self):
        """Generate the complete TUI layout"""
        # Create a main table for the entire layout
        layout_table = Table.grid(expand=True)
        layout_table.add_column("Main")
        
        # Add the header with stats
        duration = datetime.now() - self.stats["start_time"]
        duration_str = str(duration).split('.')[0]  # Remove microseconds
        
        header = Table.grid(expand=True)
        header.add_column("Stats", justify="center", ratio=1)
        header.add_column("Timing", justify="center", ratio=1)
        
        # Create formatted text elements for stats instead of a string with markup
        from rich.text import Text
        stats_text = Text()
        stats_text.append("Downloaded: ", style="bold green")
        stats_text.append(str(self.stats['videos_downloaded']))
        stats_text.append(" | ")
        stats_text.append("Uploaded: ", style="bold blue")
        stats_text.append(str(self.stats['videos_uploaded']))
        stats_text.append(" | ")
        stats_text.append("Encoding: ", style="bold yellow")
        stats_text.append(str(self.stats['videos_encoding']))
        stats_text.append(" | ")
        stats_text.append("Completed: ", style="bold green")
        stats_text.append(str(self.stats['videos_encoded']))
        
        timing_text = Text()
        timing_text.append("Running time: ", style="bold")
        timing_text.append(duration_str)
        
        header.add_row(stats_text, timing_text)

        # Create the download threads table
        download_table = Table(
            title="Download Threads",
            expand=True,
            border_style="blue"
        )
        download_table.add_column("Thread ID")
        download_table.add_column("Status")
        download_table.add_column("Video")
        download_table.add_column("Last Update")
        
        for thread_id, info in self.stats["download_threads"].items():
            # Format time as HH:MM:SS
            update_time = info["updated_at"].strftime("%H:%M:%S")
            status_color = "green" if info["status"] == "completed" else "yellow"
            
            download_table.add_row(
                f"{thread_id}",
                f"[{status_color}]{info['status']}[/{status_color}]",
                f"{info['video_id'] or ''}",
                f"{update_time}"
            )
        
        # Create the upload threads table
        upload_table = Table(
            title="Upload/Encoding Threads",
            expand=True,
            border_style="green"
        )
        upload_table.add_column("Thread ID")
        upload_table.add_column("Status")
        upload_table.add_column("Video")
        upload_table.add_column("Encoding")
        upload_table.add_column("Last Update")
        
        for thread_id, info in self.stats["upload_threads"].items():
            # Format time as HH:MM:SS
            update_time = info["updated_at"].strftime("%H:%M:%S")
            
            # Set status color based on current status
            status_color = "yellow"
            if info["status"] == "uploaded":
                status_color = "green"
            elif info["status"] == "waiting":
                status_color = "blue"
            
            # Set encoding status color
            encoding_color = "yellow"
            if info["encoding_status"] == "success":
                encoding_color = "green"
            elif info["encoding_status"] == "fail":
                encoding_color = "red"
            
            upload_table.add_row(
                f"{thread_id}",
                f"[{status_color}]{info['status']}[/{status_color}]",
                f"{info['video_id'] or ''}",
                f"[{encoding_color}]{info['encoding_status'] or ''}[/{encoding_color}]",
                f"{update_time}"
            )
        
        # Create recent logs panel
        logs_table = Table(
            expand=True,
            show_header=False,
            box=None
        )
        logs_table.add_column("Time", style="dim", width=10)
        logs_table.add_column("Level", width=10)
        logs_table.add_column("Message", ratio=1)
        
        for timestamp, level, message in self.stats["recent_logs"]:
            level_color = "white"
            if level == "INFO":
                level_color = "blue"
            elif level == "WARNING":
                level_color = "yellow"
            elif level == "ERROR":
                level_color = "red"
            
            logs_table.add_row(
                timestamp,
                f"[{level_color}]{level}[/{level_color}]",
                message
            )
        
        logs_panel = Panel(
            logs_table,
            title="Recent Logs",
            border_style="yellow"
        )
        
        # Add all components to the layout
        layout_table.add_row(Panel(header, title="YouTube to MediaCMS Sync", border_style="green"))
        layout_table.add_row(download_table)
        layout_table.add_row(upload_table)
        layout_table.add_row(logs_panel)
        
        return layout_table


def is_tui_enabled():
    """Safely check if TUI is enabled"""
    global tui_manager
    return tui_manager is not None and tui_manager.enabled


def initialize_tui():
    """Initialize the TUI system"""
    global tui_manager
    
    if not RICH_AVAILABLE:
        print("Rich library not installed. Install it with: pip install rich")
        return False

    # Setup for Docker container environment
    import os
    in_container = os.environ.get('CONTAINER', '') == 'docker' or os.path.exists('/.dockerenv')
    if in_container:
        print("Running in Docker container. Enabling TUI with container optimizations.")
        os.environ['TERM'] = os.environ.get('TERM', 'xterm-256color')
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        os.environ['COLORTERM'] = 'truecolor'

    try:
        # Completely disable standard logging output
        import logging
        root_logger = logging.getLogger()
        
        # Store original handlers and level for restoration later
        original_handlers = root_logger.handlers.copy()
        original_level = root_logger.level
        
        # Remove all handlers and set level to ERROR to suppress console output
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create a brand new TUIManager instance
        tui = TUIManager().start()
        
        # Create custom logging methods that use the TUI
        def tui_info(msg, *args, **kwargs):
            if args or kwargs:
                try:
                    msg = msg % args
                except:
                    pass
            tui.log(msg, "INFO")
            
        def tui_error(msg, *args, **kwargs):
            if args or kwargs:
                try:
                    msg = msg % args
                except:
                    pass
            tui.log(msg, "ERROR")
            
        def tui_warning(msg, *args, **kwargs):
            if args or kwargs:
                try:
                    msg = msg % args
                except:
                    pass
            tui.log(msg, "WARNING")
            
        def tui_debug(msg, *args, **kwargs):
            # Skip debug messages in TUI
            pass
        
        # Replace the global logger functions
        logger.info = tui_info
        logger.error = tui_error
        logger.warning = tui_warning
        logger.debug = tui_debug
        
        # Store TUI manager in global variable
        tui_manager = tui
        
        # Store original state for cleanup
        tui_manager.original_handlers = original_handlers
        tui_manager.original_level = original_level
        
        return True
        
    except Exception as e:
        print(f"Error initializing TUI: {str(e)}")
        return False


def cleanup_tui():
    """Clean up the TUI and restore original logging"""
    global tui_manager
    
    if tui_manager is not None and hasattr(tui_manager, 'stop'):
        try:
            # Stop the live display
            tui_manager.stop()
            
            # Restore the original logging configuration
            root_logger = logging.getLogger()
            
            if hasattr(tui_manager, 'original_handlers'):
                # First remove any current handlers
                for handler in root_logger.handlers[:]:
                    root_logger.removeHandler(handler)
                
                # Then restore original handlers
                for handler in tui_manager.original_handlers:
                    root_logger.addHandler(handler)
            
            if hasattr(tui_manager, 'original_level'):
                root_logger.setLevel(tui_manager.original_level)
            
        except Exception as e:
            print(f"Error cleaning up TUI: {str(e)}")


def enable_tui():
    """Enable the TUI"""
    return initialize_tui()


def disable_tui():
    """Disable the TUI"""
    cleanup_tui()
