# Changelog

All notable changes to this project will be documented in this file.

## [v1.0.1] - 2025-03-06

### Fixed
- Fixed a bug where the script incorrectly considered videos fully encoded when only lower resolutions were ready while higher resolutions were still processing.

## [v1.0.0] - 2025-03-06

### Added
- Parallel downloading and uploading with configurable workers
- Smart encoding status tracking using MediaCMS API
- Interactive TUI mode with live status updates
- Wait-for-encoding option to prevent server overload

### Changed
- Removed dependency on mediacms_user in config.json
- Improved metadata race condition handling with retries
- Enhanced command-line arguments for better control

### Fixed
- Race condition in metadata file handling
- Better error handling during upload process
