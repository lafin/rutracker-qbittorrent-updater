#!/usr/bin/env python3

import re
import os
import sys
import time
import requests
import bencodepy
import argparse
from qbittorrentapi import Client, TorrentState
from requests.exceptions import RequestException, Timeout
import signal
import daemon

# Constants for request handling
REQUEST_TIMEOUT = 30  # 30 seconds timeout
MAX_RETRIES = 5  # Maximum 5 retry attempts

def parse_arguments():
    parser = argparse.ArgumentParser(description='qBittorrent RuTracker updater (daemonized)')
    parser.add_argument('--qbt-host', required=True, help='qBittorrent host URL (e.g. http://192.168.0.77:3001)')
    parser.add_argument('--qbt-username', required=True, help='qBittorrent username')
    parser.add_argument('--qbt-password', default='', help='qBittorrent password')
    parser.add_argument('--qbt-tag', help='Only check torrents with this tag for RuTracker updates. If not specified, all torrents will be checked.')
    parser.add_argument('--rutracker-username', required=True, help='RuTracker username')
    parser.add_argument('--rutracker-password', required=True, help='RuTracker password')
    parser.add_argument('--tg-token', help='Telegram bot token for notifications')
    parser.add_argument('--tg-chat-id', help='Telegram chat ID to send notifications to')
    parser.add_argument('--temp-dir', default='/tmp', help='Directory for temporary files')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--log-file', default='/tmp/qbt_daemon.log', help='Log file for daemon output')
    parser.add_argument('--plain', type=bool, default=False, help='Run in plain mode')
    return parser.parse_args()

def send_telegram_notification(token, chat_id, message):
    if not token or not chat_id:
        return False
    telegram_api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(telegram_api_url, data=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"Failed to send Telegram notification: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram notification: {str(e)}")
        return False

def make_request(session, method, url, **kwargs):
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)
    for attempt in range(MAX_RETRIES):
        try:
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
                wait_time = 2 ** attempt
                print(f"Request to {url} failed (attempt {attempt+1}/{MAX_RETRIES}): {str(e)}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Request to {url} failed after {MAX_RETRIES} attempts: {str(e)}")
                return None

def get_rutracker_session(username, password):
    session = requests.Session()
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
    topic_url = f'https://rutracker.org/forum/viewtopic.php?t={topic_id}'
    try:
        response = make_request(session, 'get', topic_url)
        if response is None:
            print(f"Failed to get topic page for {topic_id}")
            return None
        dl_pattern = r'dl\.php\?t=(\d+)'
        dl_match = re.search(dl_pattern, response.text)
        if not dl_match:
            print(f"Could not find download link for topic {topic_id}")
            return None
        dl_id = dl_match.group(1)
        download_url = f'https://rutracker.org/forum/dl.php?t={dl_id}'
        torrent_response = make_request(session, 'get', download_url)
        if torrent_response is None:
            print(f"Failed to download torrent file for topic {topic_id}")
            return None
        if torrent_response.status_code != 200:
            print(f"Failed to download torrent file for topic {topic_id}, status code: {torrent_response.status_code}")
            return None
        temp_torrent_path = f"{temp_dir}/rutracker_{topic_id}.torrent"
        with open(temp_torrent_path, 'wb') as f:
            f.write(torrent_response.content)
        return temp_torrent_path
    except Exception as e:
        print(f"Error fetching torrent info from RuTracker: {str(e)}")
        return None

def get_torrent_size(torrent_file):
    try:
        with open(torrent_file, 'rb') as f:
            metadata = bencodepy.decode(f.read())
        info = metadata.get(b'info', {})
        if b'length' in info:
            return info[b'length']
        elif b'files' in info:
            total_size = 0
            for file_info in info[b'files']:
                total_size += file_info.get(b'length', 0)
            return total_size
        return None
    except Exception as e:
        print(f"Error getting torrent size: {str(e)}")
        return None

def run_main(args):
    print("Main daemon entered", flush=True)

    def sigterm_handler(signum, frame):
        print("Daemon received SIGTERM, exiting gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)

    notified_completed = set()
    torrent_complete_state = dict()

    STATUS_INTERVAL = 30           # 30 seconds
    RUTRACKER_INTERVAL = 1800      # 30 minutes

    last_status_check = 0
    last_rutracker_check = 0

    rutracker_session = None

    try:
        qbt_client = Client(
            host=args.qbt_host,
            username=args.qbt_username,
            password=args.qbt_password
        )
        qbt_client.auth_log_in()
        torrents = qbt_client.torrents_info()
        for torrent in torrents:
            is_complete = TorrentState(torrent.state).is_complete
            torrent_complete_state[torrent.hash] = is_complete
    except Exception as e:
        print(f"Failed to initialize torrent states: {str(e)}")

    while True:
        now = time.time()

        if now - last_status_check >= STATUS_INTERVAL:
            last_status_check = now
            try:
                qbt_client = Client(
                    host=args.qbt_host,
                    username=args.qbt_username,
                    password=args.qbt_password
                )
                qbt_client.auth_log_in()
            except Exception as e:
                print(f"Failed to connect to qBittorrent: {str(e)}")
                time.sleep(STATUS_INTERVAL)
                continue

            torrents = qbt_client.torrents_info()
            telegram_enabled = args.tg_token and args.tg_chat_id

            for torrent in torrents:
                is_complete = TorrentState(torrent.state).is_complete
                prev_complete = torrent_complete_state.get(torrent.hash, False)

                if not prev_complete and is_complete:
                    message = f"✅ Torrent Downloaded: {torrent.name}"
                    if telegram_enabled:
                        if send_telegram_notification(args.tg_token, args.tg_chat_id, message):
                            print(f"Telegram notification sent for completed torrent: {torrent.name}")
                        else:
                            print(f"Failed to send Telegram notification for: {torrent.name}")
                    notified_completed.add(torrent.hash)

                torrent_complete_state[torrent.hash] = is_complete

            current_hashes = set(t.hash for t in torrents)
            for h in list(torrent_complete_state):
                if h not in current_hashes:
                    del torrent_complete_state[h]
            for h in list(notified_completed):
                if h not in current_hashes:
                    notified_completed.remove(h)

        if now - last_rutracker_check >= RUTRACKER_INTERVAL:
            last_rutracker_check = now
            try:
                qbt_client = Client(
                    host=args.qbt_host,
                    username=args.qbt_username,
                    password=args.qbt_password
                )
                qbt_client.auth_log_in()
            except Exception as e:
                print(f"Failed to connect to qBittorrent: {str(e)}")
                time.sleep(STATUS_INTERVAL)
                continue

            if not rutracker_session:
                rutracker_session = get_rutracker_session(args.rutracker_username, args.rutracker_password)
            if not rutracker_session:
                print("Could not login to RuTracker, skipping RuTracker check.")
            else:
                torrents = qbt_client.torrents_info()
                telegram_enabled = args.tg_token and args.tg_chat_id
                for torrent in torrents:
                    if args.qbt_tag:
                        torrent_tags = torrent.tags.split(',') if torrent.tags else []
                        if args.qbt_tag not in torrent_tags:
                            continue
                    comment = torrent.comment if hasattr(torrent, 'comment') else ""
                    rutracker_match = re.search(r'https://rutracker\.org/forum/viewtopic\.php\?t=(\d+)', comment)
                    if rutracker_match:
                        topic_id = rutracker_match.group(1)
                        torrent_hash = torrent.hash
                        torrent_data = qbt_client.torrents_properties(torrent_hash=torrent_hash)
                        current_size = torrent_data.total_size
                        new_torrent_path = get_torrent_info_from_rutracker(topic_id, rutracker_session, args.temp_dir)
                        if new_torrent_path:
                            new_size = get_torrent_size(new_torrent_path)
                            if new_size and new_size != current_size:
                                print(f"Torrent {torrent.name} has changed (Size: {current_size} -> {new_size})")
                                qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent_hash)
                                print(f"Removed old torrent {torrent.name}")
                                with open(new_torrent_path, 'rb') as f:
                                    torrent_data_bin = f.read()
                                add_options = {
                                    'savepath': torrent.save_path,
                                    'category': torrent.category,
                                    'comment': comment,
                                    'paused': False,
                                    'tags': torrent.tags
                                }
                                qbt_client.torrents_add(torrent_files=torrent_data_bin, **add_options)
                                print(f"Added new torrent {torrent.name}")
                                if telegram_enabled:
                                    message = f"🔄 Torrent Updated: {torrent.name}"
                                    send_telegram_notification(args.tg_token, args.tg_chat_id, message)
                            else:
                                print(f"No changes detected for torrent {torrent.name}")
                            os.remove(new_torrent_path)
                        else:
                            print(f"Failed to get new torrent file for {torrent.name}, continuing with next torrent")

        time.sleep(1)

def run_daemon(args):
    log_file = open(args.log_file, 'a+', buffering=1)
    with daemon.DaemonContext(files_preserve=[log_file.fileno()]):
        sys.stdout = log_file
        sys.stderr = log_file
        print("Main daemon entered", flush=True)
        run_main(args)

if __name__ == "__main__":
    args = parse_arguments()
    if args.plain:
        run_main(args)
    else:
        run_daemon(args)
