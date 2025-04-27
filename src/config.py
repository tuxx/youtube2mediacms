import os
import sys
import json
import logging

logger = logging.getLogger('yt2mediacms')

def load_config(config_file):
    """Load configuration from JSON file"""
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    else:
        logger.error(f"Config file {config_file} not found.")
        sys.exit(1)
