# RuTracker to qBittorrent Updater

A robust Python utility that automatically updates your qBittorrent torrents when their corresponding RuTracker sources are updated.

## Overview

This tool monitors your qBittorrent torrents that have RuTracker links in their comments. When a torrent is updated on RuTracker (detected by a change in file size), the script automatically replaces the old torrent with the updated version while preserving your download location, category, and tags.

## Features

- **Automatic Updates**: Detects and applies updates to torrents from RuTracker
- **Data Preservation**: Keeps your downloaded data when updating torrents
- **Tag Filtering**: Option to only check torrents with specific tags
- **Robust Connection Handling**: Implements timeouts, retries, and proper user agent settings
- **Respectful Scraping**: Includes delays between requests to avoid overloading RuTracker servers

## Requirements

- Python 3.6+
- qBittorrent with Web UI enabled
- RuTracker account

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/lafin/rutracker-qbittorrent-updater.git
   cd rutracker-qbittorrent-updater
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Basic usage:

```bash
python rutracker_qbt_updater.py --qbt-host "http://localhost:8080" --qbt-username "admin" --qbt-password "adminpassword" --rutracker-username "your_username" --rutracker-password "your_password"
```

### Command Line Arguments

| Argument | Description |
|----------|-------------|
| `--qbt-host` | qBittorrent Web UI URL (e.g., http://192.168.0.77:8080) |
| `--qbt-username` | qBittorrent Web UI username |
| `--qbt-password` | qBittorrent Web UI password |
| `--qbt-tag` | Only check torrents with this tag (optional) |
| `--rutracker-username` | RuTracker username |
| `--rutracker-password` | RuTracker password |
| `--temp-dir` | Directory for temporary files (default: /tmp) |
| `--verbose`, `-v` | Enable verbose output |

## How It Works

1. The script connects to your qBittorrent client via its Web API
2. It logs into RuTracker using your credentials
3. For each torrent in qBittorrent (or only those with the specified tag):
   - It checks if the torrent has a RuTracker link in its comments
   - If a link is found, it downloads the current .torrent file from RuTracker
   - It compares the size of the downloaded torrent with the existing one
   - If the size differs, it replaces the old torrent with the new one while preserving settings

## Connection Handling

The script implements several measures to ensure reliable and respectful connections to RuTracker:

- Uses a Chrome browser user agent to avoid being blocked
- Adds a 1-second delay between requests to avoid overloading the server
- Sets a 30-second timeout for all HTTP requests
- Implements a retry mechanism (up to 5 attempts) with exponential backoff
- Continues with the next torrent if a request fails after all retry attempts

## Setting Up Automation

### Using Cron (Linux/macOS)

To run the script automatically, for example, once a day at 3 AM:

```bash
crontab -e
```

Add the following line:

```
0 3 * * * /path/to/python /path/to/rutracker_qbt_updater.py --qbt-host "http://localhost:8080" --qbt-username "admin" --qbt-password "adminpassword" --rutracker-username "your_username" --rutracker-password "your_password" >> /path/to/logfile.log 2>&1
```

### Using Task Scheduler (Windows)

1. Create a batch file (update_torrents.bat) with the following content:
   ```batch
   @echo off
   python C:\path\to\rutracker_qbt_updater.py --qbt-host "http://localhost:8080" --qbt-username "admin" --qbt-password "adminpassword" --rutracker-username "your_username" --rutracker-password "your_password"
   ```

2. Open Task Scheduler and create a new task that runs this batch file at your desired schedule.

## Best Practices

1. **Use Tags**: Add a specific tag (e.g., "rutracker") to torrents you want to monitor, then use the `--qbt-tag` option to only check those torrents.

2. **Security**: Consider storing your credentials in environment variables or a configuration file with restricted permissions instead of directly in command line arguments.

3. **Logging**: Redirect the script output to a log file to keep track of updates and potential issues.

## Troubleshooting

### Common Issues

1. **Login Failures**: Ensure your RuTracker account is active and credentials are correct.

2. **Connection Timeouts**: Check your internet connection and RuTracker's availability.

3. **Permission Errors**: Ensure the script has write access to the temporary directory.

4. **qBittorrent Connection Issues**: Verify that the Web UI is enabled and accessible from the machine running the script.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is intended for personal use to keep your legally obtained torrents updated. The developers are not responsible for any misuse of this software. Please respect RuTracker's terms of service and use this tool responsibly.