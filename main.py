#!/usr/bin/env python3

import re
import os
import sys
import time
import hashlib
import requests
import bencodepy
import argparse
from qbittorrentapi import Client
from requests.exceptions import RequestException, Timeout

# Constants for request handling
REQUEST_TIMEOUT = 30  # 30 seconds timeout
MAX_RETRIES = 5  # Maximum 5 retry attempts

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='qBittorrent RuTracker updater')

    # qBittorrent settings
    parser.add_argument('--qbt-host', required=True, help='qBittorrent host URL (e.g. http://192.168.0.77:3001)')
    parser.add_argument('--qbt-username', required=True, help='qBittorrent username')
    parser.add_argument('--qbt-password', default='', help='qBittorrent password')
    parser.add_argument('--qbt-tag', help='Only check torrents with this tag. If not specified, all torrents will be checked.')

    # RuTracker settings
    parser.add_argument('--rutracker-username', required=True, help='RuTracker username')
    parser.add_argument('--rutracker-password', required=True, help='RuTracker password')

    # Additional options
    parser.add_argument('--temp-dir', default='/tmp', help='Directory for temporary files')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')

    return parser.parse_args()

def make_request(session, method, url, **kwargs):
    """Make HTTP request with retry logic and timeout"""
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)

    for attempt in range(MAX_RETRIES):
        try:
            # Wait 1 second before request
            time.sleep(1)

            if method.lower() == 'get':
                response = session.get(url, **kwargs)
            elif method.lower() == 'post':
                response = session.post(url, **kwargs)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return response

        except (RequestException, Timeout) as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Request to {url} failed (attempt {attempt+1}/{MAX_RETRIES}): {str(e)}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Request to {url} failed after {MAX_RETRIES} attempts: {str(e)}")
                return None

def get_rutracker_session(username, password):
    """Login to RuTracker and return session object"""
    session = requests.Session()

    # Set Chrome user agent
    chrome_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
    session.headers.update({'User-Agent': chrome_user_agent})

    login_url = 'https://rutracker.org/forum/login.php'

    login_data = {
        'login_username': username,
        'login_password': password,
        'login': 'Login'
    }

    try:
        response = make_request(session, 'post', login_url, data=login_data)
        if response is None:
            print("Failed to login to RuTracker due to request failure")
            return None

        if 'logged-in' not in response.text:
            print("Failed to login to RuTracker")
            return None

        print("Successfully logged in to RuTracker")
        return session

    except Exception as e:
        print(f"Error logging in to RuTracker: {str(e)}")
        return None

def get_torrent_info_from_rutracker(topic_id, session, temp_dir):
    """Get torrent info and download .torrent file from RuTracker"""
    topic_url = f'https://rutracker.org/forum/viewtopic.php?t={topic_id}'

    try:
        # Get the page with the torrent information
        response = make_request(session, 'get', topic_url)
        if response is None:
            print(f"Failed to get topic page for {topic_id}")
            return None

        # Extract download link for the .torrent file
        dl_pattern = r'dl\.php\?t=(\d+)'
        dl_match = re.search(dl_pattern, response.text)

        if not dl_match:
            print(f"Could not find download link for topic {topic_id}")
            return None

        dl_id = dl_match.group(1)
        download_url = f'https://rutracker.org/forum/dl.php?t={dl_id}'

        # Download the .torrent file
        torrent_response = make_request(session, 'get', download_url)
        if torrent_response is None:
            print(f"Failed to download torrent file for topic {topic_id}")
            return None

        if torrent_response.status_code != 200:
            print(f"Failed to download torrent file for topic {topic_id}, status code: {torrent_response.status_code}")
            return None

        # Save to a temporary file
        temp_torrent_path = f"{temp_dir}/rutracker_{topic_id}.torrent"
        with open(temp_torrent_path, 'wb') as f:
            f.write(torrent_response.content)

        return temp_torrent_path

    except Exception as e:
        print(f"Error fetching torrent info from RuTracker: {str(e)}")
        return None

def get_torrent_size(torrent_file):
    """Extract the total size from a .torrent file"""
    try:
        with open(torrent_file, 'rb') as f:
            metadata = bencodepy.decode(f.read())

        info = metadata.get(b'info', {})

        # Single file torrent
        if b'length' in info:
            return info[b'length']

        # Multi-file torrent
        elif b'files' in info:
            total_size = 0
            for file_info in info[b'files']:
                total_size += file_info.get(b'length', 0)
            return total_size

        return None
    except Exception as e:
        print(f"Error getting torrent size: {str(e)}")
        return None

def main():
    # Parse command line arguments
    args = parse_arguments()

    # Connect to qBittorrent
    try:
        qbt_client = Client(
            host=args.qbt_host,
            username=args.qbt_username,
            password=args.qbt_password
        )
        qbt_client.auth_log_in()
        print("Successfully connected to qBittorrent")
    except Exception as e:
        print(f"Failed to connect to qBittorrent: {str(e)}")
        sys.exit(1)

    # Login to RuTracker
    rutracker_session = get_rutracker_session(args.rutracker_username, args.rutracker_password)
    if not rutracker_session:
        sys.exit(1)

    # Get list of torrents
    torrents = qbt_client.torrents_info()

    if args.qbt_tag:
        print(f"Only checking torrents with tag: {args.qbt_tag}")
    else:
        print("Checking all torrents (no tag filter specified)")

    for torrent in torrents:
        # Skip torrents that don't have the specified tag if --qbt-tag is provided
        if args.qbt_tag:
            torrent_tags = torrent.tags.split(',') if torrent.tags else []
            if args.qbt_tag not in torrent_tags:
                if args.verbose:
                    print(f"Skipping torrent {torrent.name} as it doesn't have the tag '{args.qbt_tag}'")
                continue

        # Check if torrent has a RuTracker link in comments
        comment = torrent.comment if hasattr(torrent, 'comment') else ""

        rutracker_match = re.search(r'https://rutracker\.org/forum/viewtopic\.php\?t=(\d+)', comment)

        if rutracker_match:
            topic_id = rutracker_match.group(1)
            print(f"Found RuTracker link in torrent {torrent.name}, topic ID: {topic_id}")

            # Get current torrent info
            torrent_hash = torrent.hash
            torrent_data = qbt_client.torrents_properties(torrent_hash=torrent_hash)
            current_size = torrent_data.total_size

            # Download torrent from RuTracker
            new_torrent_path = get_torrent_info_from_rutracker(topic_id, rutracker_session, args.temp_dir)

            if new_torrent_path:
                # Check new torrent size
                new_size = get_torrent_size(new_torrent_path)

                if new_size and new_size != current_size:
                    print(f"Torrent {torrent.name} has changed (Size: {current_size} -> {new_size})")

                    # Remove old torrent (keep data)
                    qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent_hash)
                    print(f"Removed old torrent {torrent.name}")

                    # Add new torrent
                    with open(new_torrent_path, 'rb') as f:
                        torrent_data = f.read()

                    add_options = {
                        'savepath': torrent.save_path,
                        'category': torrent.category,
                        'comment': comment,
                        'paused': False,
                        'tags': torrent.tags  # Preserve the original tags
                    }

                    qbt_client.torrents_add(torrent_files=torrent_data, **add_options)
                    print(f"Added new torrent {torrent.name}")
                else:
                    print(f"No changes detected for torrent {torrent.name}")

                # Clean up temp file
                os.remove(new_torrent_path)
            else:
                print(f"Failed to get new torrent file for {torrent.name}, continuing with next torrent")

if __name__ == "__main__":
    main()
