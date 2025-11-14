import os
import json
import threading
import time
import logging
import re  # For parsing Spotify URLs and checking URIs
import subprocess  # For ex.py and spotifyd
from functools import wraps
import requests
# Import for flash messages
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback  # Added for debugging
import random  # Added for random song selection
import socket
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import generate_csrf

# --- Configurable Settings ---
# !!! REPLACE THIS INFORMATION WITH YOUR OWN SPOTIFY DEVELOPER DETAILS !!!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'  # EXAMPLE - CHANGE
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'  # EXAMPLE - CHANGE
# !!! MAKE SURE THIS URI IS THE SAME AS THE REDIRECT URI IN YOUR SPOTIFY DEVELOPER DASHBOARD !!!
SPOTIFY_REDIRECT_URI = 'http://web-vds.tail1b3477.ts.net/callback'  # EXAMPLE - CHANGE
SPOTIFY_SCOPE = 'user-read-playback-state user-read-private user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12  # Bluetooth scan duration in seconds
EX_SCRIPT_PATH = 'ex.py'  # Path to the ex.py script
# Default genres to be displayed in the user interface (optional)
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
# ---------------------------------

# Logging settings
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
# --- Custom Logger for Security Events ---
waf_logger = logging.getLogger('WAF')
waf_logger.setLevel(logging.WARNING)
# Write only security events to the 'security_events.log' file
waf_handler = logging.FileHandler('security_events.log')
waf_formatter = logging.Formatter('%(asctime)s - %(levelname)s - IP: %(ip)s - Rule: %(rule)s - Path: %(path)s - Data: %(data)s')
waf_handler.setFormatter(waf_formatter)
waf_logger.addHandler(waf_handler)
# ----------------------------------------
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_unsafe_key_please_change')
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION
app.jinja_env.globals['ALLOWED_GENRES'] = ALLOWED_GENRES
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)
csrf = CSRFProtect(app)


@app.context_processor
def inject_csrf():
    # Can be used in templates as {{ csrf_token() }}
    return dict(csrf_token=generate_csrf)


# --- WAF-Like Middleware ---
@app.before_request
def waf_middleware():
    # Security rules (Regex patterns)
    # You can expand this list according to your needs.
    rules = [
        {'name': 'SQL_INJECTION_1',
         'pattern': r"(\b(union|select|insert|drop|update|delete|from|where)\b.*?--|\' OR \'1\'=\'1\')"},
        {'name': 'SQL_INJECTION_2', 'pattern': r"(\b(exec|execute|char|cast|convert)\b.*?--)"},
        {'name': 'XSS_SCRIPT_TAG', 'pattern': r"<script.*?>.*?</script>"},
        {'name': 'XSS_ON_EVENT', 'pattern': r"onerror=|onload=|onmouseover=|onclick="},
        {'name': 'PATH_TRAVERSAL', 'pattern': r"(\.\./|\.\.\\)"},
        {'name': 'COMMAND_INJECTION', 'pattern': r"(\b(cat|ls|whoami|uname|id|pwd|wget|curl)\s)"},
        {'name': 'MALICIOUS_USER_AGENT', 'pattern': r"(sqlmap|nmap|nikto|wpscan|nessus)"}
    ]

    # Data sources to be inspected
    user_ip = request.remote_addr
    path_and_query = request.path  # Get only the path, not the query string
    user_agent = request.headers.get('User-Agent', '')

    # Safely get the body of requests like POST, PUT
    body = ''
    if request.method in ['POST', 'PUT', 'PATCH']:
        try:
            body = request.get_data(as_text=True)
        except Exception as e:
            logger.warning(f"WAF: Could not read request body. IP: {user_ip}, Error: {e}")

    # Combine all texts to be checked
    data_to_check = {
        'path': path_and_query,
        'user_agent': user_agent,
        'body': body
    }

    # Apply the rules
    for rule in rules:
        for source, data in data_to_check.items():
            if data and re.search(rule['pattern'], data, re.IGNORECASE):
                # Rule matched! Block the attack attempt and log it.
                log_extra = {
                    'ip': user_ip,
                    'rule': rule['name'],
                    'path': request.path,
                    'data': f"Source: {source}, Data: {data[:200]}"  # Log the first 200 characters of the data
                }
                waf_logger.warning("Potential Attack Blocked!", extra=log_extra)

                # Terminate the request with a 403 Forbidden error
                return jsonify({
                    'success': False,
                    'error': 'Forbidden',
                    'message': 'Your request was rejected because it violates our security policies.'
                }), 403

    # If no rule matches, allow the request to proceed normally
    return None


# --- END: New Location Logic ---

# --- Helper Function: Spotify URI Processing ---
def _ensure_spotify_uri(item_id, item_type):
    """
    Converts the given ID (or URL) into the correct Spotify URI format or returns None.
    Always uses 'spotify:track:' for songs.
    """
    if not item_id or not isinstance(item_id, str): return None
    item_id = item_id.strip()

    # Normalize item_type: treat 'song' as 'track'
    actual_item_type = 'track' if item_type in ['song', 'track'] else item_type
    prefix = f"spotify:{actual_item_type}:"

    # If already in the correct URI format, return it
    if item_id.startswith(prefix): return item_id

    # If it's just an ID (no ':'), add the prefix
    if ":" not in item_id: return f"{prefix}{item_id}"

    # If it's a URL, extract the ID
    if actual_item_type == 'track' and '/track/' in item_id:
        match = re.search(r'/track/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:track:{match.group(1)}"
    elif actual_item_type == 'artist' and '/artist/' in item_id:
        match = re.search(r'/artist/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:artist:{match.group(1)}"
    # CHANGE: Added conversion of playlist URL to URI
    elif actual_item_type == 'playlist' and '/playlist/' in item_id:
        match = re.search(r'/playlist/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:playlist:{match.group(1)}"

    # Unrecognized or invalid format
    logger.warning(f"Unrecognized or invalid Spotify {actual_item_type} ID/URI format: {item_id}")
    return None


# --- Helper Function: Command Execution (for ex.py and spotifyd) ---
def _run_command(command, timeout=30):
    """Helper function to run shell commands and return parsed JSON or error."""
    try:
        # Check if the command starts with 'python3'
        if command[0] == 'python3' and len(command) > 1 and command[1] == EX_SCRIPT_PATH:
            full_command = command
        elif command[0] == 'spotifyd' or command[0] == 'pgrep':
            full_command = command
        else:
            # If it's an ex.py command, add python3 to the beginning
            full_command = ['python3', EX_SCRIPT_PATH] + command

        logger.debug(f"Running command: {' '.join(full_command)}")
        result = subprocess.run(full_command, capture_output=True, text=True, check=True, timeout=timeout,
                                encoding='utf-8')
        logger.debug(f"Command stdout (first 500 chars): {result.stdout[:500]}")
        try:
            # Only parse JSON for ex.py output
            if full_command[0] == 'python3' and full_command[1] == EX_SCRIPT_PATH:
                if not result.stdout.strip():
                    logger.warning(f"Command {' '.join(full_command)} returned empty output.")
                    return {'success': False, 'error': 'Command returned empty output.'}
                return json.loads(result.stdout)
            else:  # Return raw output for other commands like spotifyd or pgrep
                return {'success': True, 'output': result.stdout.strip()}
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to parse JSON output from command {' '.join(full_command)}: {json_err}")
            logger.error(f"Raw output was: {result.stdout}")
            return {'success': False, 'error': f"Command output is not in JSON format: {json_err}",
                    'raw_output': result.stdout}
    except FileNotFoundError:
        err_msg = f"Command not found: {full_command[0]}. Is it installed and in PATH?"
        if full_command[0] == 'python3' and len(full_command) > 1 and full_command[1] == EX_SCRIPT_PATH:
            err_msg = f"Python 3 interpreter or '{EX_SCRIPT_PATH}' script not found."
        logger.error(err_msg)
        return {'success': False, 'error': err_msg}
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Command '{' '.join(full_command)}' failed with return code {e.returncode}. Stderr:\n{e.stderr}")
        return {'success': False, 'error': f"Command error (code {e.returncode})", 'stderr': e.stderr,
                'stdout': e.stdout}
    except subprocess.TimeoutExpired:
        logger.error(f"Command '{' '.join(full_command)}' timed out after {timeout} seconds.")
        return {'success': False, 'error': f"Command timed out ({timeout}s)."}
    except Exception as e:
        logger.error(f"Error running command '{' '.join(full_command)}': {e}", exc_info=True)
        return {'success': False, 'error': f"Unexpected error: {e}"}


# --- Spotifyd Helper Functions ---
def get_spotifyd_pid():
    """Finds the PID of running spotifyd processes."""
    result = _run_command(["pgrep", "spotifyd"], timeout=5)
    if result.get('success'):
        pids = result.get('output', '').split("\n") if result.get('output') else []
        logger.debug(f"Found spotifyd PIDs: {pids}")
        return pids
    else:
        logger.error(f"Failed to get spotifyd PID: {result.get('error')}")
        return []


def restart_spotifyd():
    """Restarts the spotifyd service via ex.py."""
    logger.info("Attempting to restart spotifyd via ex.py...")
    result = _run_command(['restart_spotifyd'])  # Calls ex.py's own command
    return result.get('success', False), result.get('message', result.get('error', 'Unknown error'))


# --- Settings Management (Filters Added) ---
def load_settings():
    """Loads settings from the file, adds defaults for missing filter settings."""
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5,
        'active_device_id': None,
        'genre_filter_mode': 'blacklist',
        'artist_filter_mode': 'blacklist',
        'track_filter_mode': 'blacklist',  # Use track_filter_mode instead of song_filter_mode
        'genre_blacklist': [],
        'genre_whitelist': [],
        'artist_blacklist': [],
        'artist_whitelist': [],
        'track_blacklist': [],  # Use track_blacklist instead of song_blacklist
        'track_whitelist': [],  # Use track_whitelist instead of song_whitelist
        'active_playlist_uri': None
    }
    settings_to_use = default_settings.copy()  # Get the default first
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            # Convert old 'song_' keys to 'track_' keys (if they exist)
            if 'song_blacklist' in loaded:
                if 'track_blacklist' not in loaded:  # Only move if track_blacklist doesn't exist
                    loaded['track_blacklist'] = loaded.pop('song_blacklist')
                    logger.info("Old 'song_blacklist' setting moved to 'track_blacklist'.")
                else:  # If both exist, delete the song_ one
                    del loaded['song_blacklist']
                    logger.info(
                        "Both 'song_blacklist' and 'track_blacklist' found, 'song_blacklist' removed.")
            if 'song_whitelist' in loaded:
                if 'track_whitelist' not in loaded:
                    loaded['track_whitelist'] = loaded.pop('song_whitelist')
                    logger.info("Old 'song_whitelist' setting moved to 'track_whitelist'.")
                else:
                    del loaded['song_whitelist']
                    logger.info(
                        "Both 'song_whitelist' and 'track_whitelist' found, 'song_whitelist' removed.")
            if 'song_filter_mode' in loaded:
                if 'track_filter_mode' not in loaded:
                    loaded['track_filter_mode'] = loaded.pop('song_filter_mode')
                    logger.info("Old 'song_filter_mode' setting moved to 'track_filter_mode'.")
                else:
                    del loaded['song_filter_mode']
                    logger.info(
                        "Both 'song_filter_mode' and 'track_filter_mode' found, 'song_filter_mode' removed.")

            # Overwrite defaults with loaded settings
            settings_to_use.update(loaded)
            # Re-check for missing keys (after update)
            updated = False
            for key, default_value in default_settings.items():
                if key not in settings_to_use:
                    logger.info(
                        f"'{key}' setting not found in file (after update), adding default value ({default_value}).")
                    settings_to_use[key] = default_value
                    updated = True
            # Remove old 'active_genres' setting (if it exists)
            if 'active_genres' in settings_to_use:
                del settings_to_use['active_genres'];
                logger.info("Old 'active_genres' setting removed.");
                updated = True
            # Ensure lists are in URI format (if newly added or in old format)
            for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
                if key in settings_to_use:
                    item_type = 'track' if 'track' in key else 'artist'
                    original_list = settings_to_use[key]
                    # Prevent NoneType error
                    if original_list is None:
                        original_list = []
                        settings_to_use[key] = []
                        updated = True

                    converted_list = []
                    changed = False
                    # Ensure the list is actually a list
                    if not isinstance(original_list, list):
                        logger.warning(
                            f"While loading settings, '{key}' is not in the expected list format: {type(original_list)}. Replacing with an empty list.")
                        original_list = []
                        settings_to_use[key] = []
                        updated = True
                        changed = True

                    for item in original_list:
                        uri = _ensure_spotify_uri(item, item_type)
                        if uri:
                            converted_list.append(uri)
                            if uri != item: changed = True  # Mark if the format changed
                        else:
                            logger.warning(
                                f"While loading settings, invalid item in '{key}' list was skipped: {item}")
                            changed = True  # Mark if an invalid item was removed
                    if changed:
                        settings_to_use[key] = sorted(list(set(converted_list)))
                        updated = True

            if updated:
                save_settings(
                    settings_to_use)  # Save if a missing key was added or format was corrected
            logger.info(f"Settings loaded: {SETTINGS_FILE}")
        except json.JSONDecodeError as e:
            logger.error(
                f"Settings file ({SETTINGS_FILE}) contains corrupt JSON: {e}. Defaults will be used.")
            settings_to_use = default_settings.copy()  # Revert to default in case of error
        except Exception as e:
            logger.error(f"Could not read settings file ({SETTINGS_FILE}): {e}. Defaults will be used.")
            settings_to_use = default_settings.copy()  # Revert to default in case of error
    else:
        logger.info(f"Settings file not found, creating with defaults: {SETTINGS_FILE}")
        settings_to_use = default_settings.copy()
        save_settings(settings_to_use)
    return settings_to_use


def save_settings(current_settings):
    """Saves settings to the file. Cleans lists, converts to URI format, and sorts."""
    try:
        # Copy settings so the original dict doesn't change (if it came from outside the function)
        settings_to_save = current_settings.copy()

        # Convert genre lists to lowercase and sort
        if 'genre_blacklist' in settings_to_save:
            settings_to_save['genre_blacklist'] = sorted(list(set(
                [g.lower() for g in settings_to_save.get('genre_blacklist', []) if
                 isinstance(g, str) and g.strip()])))
        if 'genre_whitelist' in settings_to_save:
            settings_to_save['genre_whitelist'] = sorted(list(set(
                [g.lower() for g in settings_to_save.get('genre_whitelist', []) if
                 isinstance(g, str) and g.strip()])))

        # Convert Artist and Song lists to URI format, clean, and sort
        for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
            if key in settings_to_save:
                cleaned_uris = set()
                item_type = 'track' if 'track' in key else 'artist'
                # Ensure the list exists and is not None
                current_list = settings_to_save.get(key, [])
                if current_list is None: current_list = []

                # Ensure the list is actually a list
                if not isinstance(current_list, list):
                    logger.warning(
                        f"While saving settings, '{key}' is not in the expected list format: {type(current_list)}. It will be saved as an empty list.")
                    current_list = []

                for item in current_list:
                    uri = _ensure_spotify_uri(item, item_type)
                    if uri:
                        cleaned_uris.add(uri)
                    else:
                        logger.warning(
                            f"While saving settings, invalid item in '{key}' list was skipped: {item}")
                settings_to_save[key] = sorted(list(cleaned_uris))

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Settings saved: {SETTINGS_FILE}")
    except Exception as e:
        logger.error(f"Error while saving settings: {e}", exc_info=True)


# --- Global Variables ---
spotify_client = None
song_queue = []  # Holds song objects {'id': URI, 'name': ..., 'artist': ..., 'artist_ids': [URI,...], ...}
user_requests = {}  # Holds request counts per IP address
# CHANGE: 'time_profiles' removed. We will keep track of recently played from the playlist instead.
recently_played_from_playlist = []
settings = load_settings()  # Load settings on startup
auto_advance_enabled = True  # Is automatic song transition active?


# --- Spotify Token Management (Improved) ---
def load_token():
    """Loads the token from the file."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                token_info = json.load(f)
                if 'access_token' in token_info and 'refresh_token' in token_info:
                    logger.info(f"Token successfully loaded from file: {TOKEN_FILE}")
                    return token_info
                else:
                    logger.warning(
                        f"Token file ({TOKEN_FILE}) has missing keys. The file is being deleted.")
                    try:
                        os.remove(TOKEN_FILE)
                    except OSError as rm_err:
                        logger.error(f"Could not delete token file: {rm_err}")
                    return None
        except json.JSONDecodeError as e:
            logger.error(f"Token file ({TOKEN_FILE}) contains corrupt JSON: {e}. The file is being deleted.")
            try:
                os.remove(TOKEN_FILE)
            except OSError as rm_err:
                logger.error(f"Could not delete corrupt token file: {rm_err}")
            return None
        except Exception as e:
            logger.error(f"Token file read error ({TOKEN_FILE}): {e}", exc_info=True);
            return None
    else:
        logger.info(f"Token file not found: {TOKEN_FILE}");
        return None


def save_token(token_info):
    """Saves the token to the file."""
    try:
        if not token_info or 'access_token' not in token_info or 'refresh_token' not in token_info:
            logger.error("Token information to be saved is missing or invalid.");
            return False
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_info, f, indent=4)
        logger.info(f"Token successfully saved to file: {TOKEN_FILE}");
        return True
    except Exception as e:
        logger.error(f"Token save error ({TOKEN_FILE}): {e}", exc_info=True);
        return False


def get_spotify_auth():
    """Creates the SpotifyOAuth object."""
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('YOUR_') or \
            not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('YOUR_') or \
            not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.critical(
            "CRITICAL ERROR: Spotify API information (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) is not set correctly in app.py!")
        raise ValueError("Spotify API information is missing or incorrect!")
    logger.debug(f"Creating SpotifyOAuth. Redirect URI: {SPOTIFY_REDIRECT_URI}")
    return SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET,
                        redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPE, open_browser=False,
                        cache_path=None)


def get_spotify_client():
    """Returns the current Spotify client or creates/refreshes a new one."""
    global spotify_client
    if spotify_client:
        try:
            spotify_client.current_user();
            logger.debug("Current Spotify client is valid.");
            return spotify_client
        except spotipy.SpotifyException as e:
            logger.warning(
                f"Error with current Spotify client ({e.http_status}): {e.msg}. It will be recreated.");
            spotify_client = None
        except Exception as e:
            logger.error(f"Unknown error with current Spotify client: {e}. It will be recreated.",
                         exc_info=True);
            spotify_client = None

    token_info = load_token()
    if not token_info: logger.info("No valid token found. Authorization required."); return None

    try:
        auth_manager = get_spotify_auth()
    except ValueError as e:
        logger.error(f"Could not create Spotify authorization manager: {e}");
        return None

    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token has expired, renewing...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val: logger.error(
                "Refresh token not found. The token file is being deleted."); os.remove(
                TOKEN_FILE); return None
            try:
                auth_manager.token = token_info  # Set the old token
                new_token_info = auth_manager.refresh_access_token(refresh_token_val)
                if not new_token_info: logger.error(
                    "Could not renew token (empty response from API?). The token file is being deleted."); os.remove(
                    TOKEN_FILE); return None
                if isinstance(new_token_info, str):
                    logger.warning(
                        "refresh_access_token returned only an access token. Merging with old token information.")
                    token_info['access_token'] = new_token_info;
                    token_info['expires_at'] = int(time.time()) + 3600;
                    new_token_info = token_info
                elif not isinstance(new_token_info, dict):
                    logger.error(
                        f"Token renewal returned data in an unexpected format: {type(new_token_info)}. The token file is being deleted.");
                    os.remove(
                        TOKEN_FILE);
                    return None
                logger.info("Token successfully renewed.")
                if not save_token(new_token_info): logger.error("Could not save the renewed token!")
                token_info = new_token_info
            except spotipy.SpotifyOauthError as oauth_err:
                logger.error(
                    f"OAuth error during token renewal: {oauth_err}. The refresh token may be invalid. The token file is being deleted.");
                os.remove(
                    TOKEN_FILE);
                return None
            except Exception as refresh_err:
                logger.error(f"Unexpected error during token renewal: {refresh_err}",
                             exc_info=True);
                return None

        access_token = token_info.get('access_token')
        if not access_token: logger.error("access_token not found in token information."); return None
        new_spotify_client = spotipy.Spotify(auth=access_token)
        try:
            user_info = new_spotify_client.current_user()
            logger.info(
                f"Spotify client successfully created/verified. User: {user_info.get('display_name', '?')}")
            spotify_client = new_spotify_client
            return spotify_client
        except spotipy.SpotifyException as e:
            logger.error(
                f"Verification error with new Spotify client ({e.http_status}): {e.msg}. The token may be invalid.")
            if e.http_status == 401 or e.http_status == 403: logger.warning(
                "Authorization error received. The token file is being deleted."); os.remove(
                TOKEN_FILE)
            return None
        except Exception as e:
            logger.error(f"Unknown error during verification with new Spotify client: {e}",
                         exc_info=True);
            return None
    except spotipy.SpotifyOauthError as e:
        logger.error(f"Spotify OAuth error: {e}. The API keys or URI may be incorrect.");
        return None
    except Exception as e:
        logger.error(f"General error while getting Spotify client: {e}", exc_info=True);
        return None


# --- Admin Login Decorator ---
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Unauthorized admin panel access attempt")
            flash("You must be logged in as an administrator to access this page.", "warning")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)

    return decorated_function


# CHANGE: Time profile and suggestion functions have been removed.

# --- Song Filtering Helper Function (Updated) ---
def check_song_filters(track_uri, spotify_client):
    """
    Checks if the given track_uri complies with the filters.
    Expects input in URI format ('spotify:track:...').
    Returns: (bool: is_allowed, str: reason)
    """
    global settings
    if not spotify_client: return False, "No Spotify connection."
    if not track_uri or not isinstance(track_uri, str) or not track_uri.startswith('spotify:track:'):
        logger.error(f"check_song_filters: Invalid track_uri format: {track_uri}")
        return False, f"Invalid song URI format: {track_uri}"

    logger.debug(f"Starting filter check: {track_uri}")
    try:
        # 1. Get Song Information
        song_info = spotify_client.track(track_uri, market='TR')
        if not song_info: return False, f"Song not found (URI: {track_uri})."
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []);
        # Convert artist IDs to URI format
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists];
        primary_artist_uri = artist_uris[0] if artist_uris else None  # Get the URI of the first artist
        logger.debug(f"Song information: {song_name}, Artists: {artist_names} ({artist_uris})")

        # Get filter lists from settings (they should be in URI format)
        track_blacklist_uris = settings.get('track_blacklist', [])
        track_whitelist_uris = settings.get('track_whitelist', [])
        artist_blacklist_uris = settings.get('artist_blacklist', [])
        artist_whitelist_uris = settings.get('artist_whitelist', [])
        genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
        genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]

        # 2. Song Filter Check
        track_filter_mode = settings.get('track_filter_mode', 'blacklist')
        logger.debug(f"Song filter mode: {track_filter_mode}")
        if track_filter_mode == 'whitelist':
            if not track_whitelist_uris:
                logger.debug("Filter failed: Song whitelist is empty.")
                return False, 'The song whitelist is active but empty.'
            if track_uri not in track_whitelist_uris:
                logger.debug(
                    f"Filter failed: Song ({track_uri}) is not on the whitelist. Whitelist: {track_whitelist_uris}")
                return False, 'This song is not on the whitelist.'
        elif track_filter_mode == 'blacklist':
            if track_uri in track_blacklist_uris:
                logger.debug(
                    f"Filter failed: Song ({track_uri}) is on the blacklist. Blacklist: {track_blacklist_uris}")
                return False, 'This song is on the blacklist.'
        logger.debug(f"Passed song filter: {track_uri}")

        # 3. Artist Filter Check
        artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
        logger.debug(f"Artist filter mode: {artist_filter_mode}")
        if artist_filter_mode == 'blacklist':
            # Is any of the song's artists on the blacklist?
            if any(a_uri in artist_blacklist_uris for a_uri in artist_uris if a_uri):
                blocked_artist_info = next(
                    ((a_uri, a_name) for a_uri, a_name in zip(artist_uris, artist_names) if
                     a_uri in artist_blacklist_uris), (None, "?"))
                logger.debug(
                    f"Filter failed: Artist ({blocked_artist_info[1]} - {blocked_artist_info[0]}) is on the blacklist.")
                return False, f"The artist '{blocked_artist_info[1]}' is on the blacklist."
        elif artist_filter_mode == 'whitelist':
            if not artist_whitelist_uris:
                logger.debug("Filter failed: Artist whitelist is empty.")
                return False, 'The artist whitelist is active but empty.'
            # Is at least one of the song's artists on the whitelist?
            if not any(a_uri in artist_whitelist_uris for a_uri in artist_uris if a_uri):
                logger.debug(
                    f"Filter failed: Artist ({artist_names}) is not on the whitelist. Whitelist: {artist_whitelist_uris}")
                return False, 'This artist is not on the whitelist.'
        logger.debug("Passed artist filter.")

        # 4. Genre Filter Check
        genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
        logger.debug(f"Genre filter mode: {genre_filter_mode}")
        # Only perform genre check if one of the lists is full and the mode is active
        run_genre_check = (genre_filter_mode == 'blacklist' and genre_blacklist) or \
                          (genre_filter_mode == 'whitelist' and genre_whitelist)

        if run_genre_check:
            artist_genres = []
            # Try to get the genres of the primary artist
            if primary_artist_uri:
                try:
                    artist_info = spotify_client.artist(primary_artist_uri)
                    artist_genres = [g.lower() for g in artist_info.get('genres', [])]
                    logger.debug(f"Artist genres ({primary_artist_uri}): {artist_genres}")
                except Exception as e:
                    logger.warning(
                        f"Genre filter: Could not get artist genres ({primary_artist_uri}): {e}")

            if not artist_genres:
                logger.warning(
                    f"Cannot apply genre filter (no genres): {song_name}. Allowing.")
            else:
                if genre_filter_mode == 'blacklist':
                    # Is any of the artist's genres on the blacklist?
                    if any(genre in genre_blacklist for genre in artist_genres):
                        blocked_genre = next(
                            (genre for genre in artist_genres if genre in genre_blacklist), "?")
                        logger.debug(f"Filter failed: Genre ({blocked_genre}) is on the blacklist.")
                        return False, f"The genre '{blocked_genre}' is on the blacklist."
                elif genre_filter_mode == 'whitelist':
                    if not genre_whitelist:  # No need to check if the whitelist is empty, it won't be allowed anyway
                        logger.debug("Filter failed: Genre whitelist is empty.")
                        return False, 'The genre whitelist is active but empty.'
                    # Is at least one of the artist's genres on the whitelist?
                    if not any(genre in genre_whitelist for genre in artist_genres):
                        logger.debug(
                            f"Filter failed: Genre ({artist_genres}) is not on the whitelist. Whitelist: {genre_whitelist}")
                        return False, 'This genre is not on the whitelist.'
            logger.debug("Passed genre filter.")
        else:
            logger.debug(
                "Genre filter not applied (mode is not blacklist/whitelist or the relevant list is empty).")

        # 5. Passed All Filters
        logger.debug(f"Filter check completed: Allowed - {track_uri}")
        return True, "Passed filters."

    except spotipy.SpotifyException as e:
        logger.error(f"Spotify error during filter check (URI={track_uri}): {e}")
        if e.http_status == 400: return False, f"Invalid Spotify Song URI: {track_uri}"
        return False, f"Spotify error: {e.msg}"
    except Exception as e:
        logger.error(f"Error during filter check (URI={track_uri}): {e}", exc_info=True)
        return False, "Unknown error during filter check."


# --- Flask Routes ---

@app.route('/')
def index():
    """Displays the main page."""
    return render_template('index.html', allowed_genres=ALLOWED_GENRES)


@app.route('/admin')
def admin():
    """Displays the admin login page or panel."""
    if session.get('admin_logged_in'): return redirect(url_for('admin_panel'))
    return render_template('admin.html', csrf_token=generate_csrf())


@app.route('/admin-login', methods=['POST'])
@limiter.limit("3 per minute")
def admin_login():
    """Handles the admin login request."""
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123")  # Should be taken from a safe place
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True;
        logger.info("Admin login successful")
        flash("Welcome to the admin panel!", "success");
        return redirect(url_for('admin_panel'))
    else:
        logger.warning("Failed admin login attempt");
        flash("You entered the wrong password.", "danger")
        return redirect(url_for('admin'))


@app.route('/logout')
@admin_login_required
def logout():
    """Handles the admin logout process."""
    global spotify_client;
    spotify_client = None;
    session.clear()
    logger.info("Admin logged out.");
    flash("You have successfully logged out.", "info")
    return redirect(url_for('admin'))


@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    """Displays the admin panel. Sends settings and lists to the template."""
    global auto_advance_enabled, settings, song_queue
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None
    filtered_queue = []

    # CHANGE: Variables for pagination
    user_playlists = []
    paginated_playlists = []
    page = request.args.get('page', 1, type=int)
    per_page = 8  # Number of playlists to show per page
    total_pages = 1

    # Get audio device information
    audio_sinks_result = _run_command(['list_sinks'])
    audio_sinks = audio_sinks_result.get('sinks', []) if audio_sinks_result.get('success') else []
    default_audio_sink_name = audio_sinks_result.get('default_sink_name') if audio_sinks_result.get(
        'success') else None
    if not audio_sinks_result.get('success'):
        flash(
            f"Could not list audio devices: {audio_sinks_result.get('error', 'Unknown error')}",
            "danger")

    if spotify:
        spotify_authenticated = True
        session['spotify_authenticated'] = True
        try:
            # Get Spotify devices
            result = spotify.devices();
            spotify_devices = result.get('devices', [])

            # Get all of the user's playlists
            try:
                all_playlists = []
                results = spotify.current_user_playlists(limit=50)
                all_playlists.extend(results['items'])
                while results['next']:
                    results = spotify.next(results)
                    all_playlists.extend(results['items'])
                user_playlists = all_playlists
                logger.info(f"{len(user_playlists)} playlists found.")

                # Apply pagination logic
                total_items = len(user_playlists)
                total_pages = (total_items + per_page - 1) // per_page
                start = (page - 1) * per_page
                end = start + per_page
                paginated_playlists = user_playlists[start:end]

            except Exception as pl_err:
                logger.warning(f"Could not get user's playlists: {pl_err}")
                flash("An error occurred while getting your Spotify playlists.", "warning")

            # Get user information
            try:
                user = spotify.current_user();
                spotify_user = user.get('display_name', '?');
                session['spotify_user'] = spotify_user
            except Exception as user_err:
                logger.warning(f"Could not get Spotify user information: {user_err}");
                session.pop('spotify_user', None)

            # Get currently playing song information
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item'];
                    is_playing = playback.get('is_playing', False)
                    track_uri = item.get('uri')
                    if track_uri and track_uri.startswith('spotify:track:'):
                        is_allowed, _ = check_song_filters(track_uri, spotify)
                        track_name = item.get('name', '?');
                        artists = item.get('artists', [])
                        artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if
                                       a.get('id')]
                        images = item.get('album', {}).get('images', []);
                        image_url = images[0].get('url') if images else None
                        currently_playing_info = {
                            'id': track_uri, 'name': track_name, 'artist': artist_name,
                            'artist_ids': artist_uris, 'image_url': image_url,
                            'is_playing': is_playing, 'is_allowed': is_allowed
                        }
            except Exception as pb_err:
                logger.warning(f"Could not get playback status: {pb_err}")

            # Filter the queue
            for song in song_queue:
                song_uri = song.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, spotify)
                    if is_allowed:
                        if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                            song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in
                                                  song['artist_ids']]
                        filtered_queue.append(song)
        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API error (Admin Panel): {e.http_status} - {e.msg}")
            spotify_authenticated = False;
            session['spotify_authenticated'] = False
            if e.http_status in [401, 403]:
                flash("Spotify authorization is invalid. Please authorize again.", "warning")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                spotify_client = None
            else:
                flash(f"Spotify API error: {e.msg}", "danger")
        except Exception as e:
            logger.error(f"Unexpected error in admin panel: {e}", exc_info=True)
            spotify_authenticated = False;
            session['spotify_authenticated'] = False
            flash("An unexpected error occurred.", "danger")
    else:
        spotify_authenticated = False;
        session['spotify_authenticated'] = False
        if not os.path.exists(TOKEN_FILE): flash("Authorize to connect your Spotify account.", "info")
    return render_template(
        'admin_panel.html',
        settings=settings,
        spotify_devices=spotify_devices,
        queue=filtered_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        audio_sinks=audio_sinks, default_audio_sink_name=default_audio_sink_name,
        currently_playing_info=currently_playing_info,
        auto_advance_enabled=auto_advance_enabled,
        # CHANGE: Send paginated list and page information to the template
        paginated_playlists=paginated_playlists,
        page=page,
        total_pages=total_pages,
        active_playlist_uri=settings.get('active_playlist_uri'),
        csrf_token=generate_csrf()
    )


# --- Playback Control Routes ---
@app.route('/player/pause')
@limiter.limit("10 per minute")
@admin_login_required
def player_pause():
    global auto_advance_enabled;
    spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    if not spotify: flash('No Spotify connection!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        logger.info(f"Admin: Pause request (Device: {active_spotify_connect_device_id or '?'}).")
        spotify.pause_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = False;
        logger.info("Admin: Auto-advance PAUSED.")
        flash('Music paused and auto-advance turned off.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify pause error: {e}")
        if e.http_status == 401 or e.http_status == 403: flash('Spotify authorization error.', 'danger');
        global spotify_client;
        spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404:
            flash(f'Pause error: Device not found ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE':
            flash('No active Spotify device found!', 'warning')
        else:
            flash(f'Spotify pause error: {e.msg}', 'danger')
    except Exception as e:
        logger.error(f"General error during pause: {e}", exc_info=True);
        flash('An error occurred while pausing the music.', 'danger')
    return redirect(url_for('admin_panel'))


@app.route('/player/resume')
@admin_login_required
@limiter.limit("10 per minute")
def player_resume():
    global auto_advance_enabled;
    spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    if not spotify: flash('No Spotify connection!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        logger.info(f"Admin: Resume request (Device: {active_spotify_connect_device_id or '?'}).")
        spotify.start_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = True;
        logger.info("Admin: Auto-advance RESUMED.")
        flash('Music resumed and auto-queue advance turned on.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify resume error: {e}")
        if e.http_status == 401 or e.http_status == 403: flash('Spotify authorization error.', 'danger');
        global spotify_client;
        spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404:
            flash(f'Resume error: Device not found ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE':
            flash('No active Spotify device found!', 'warning')
        elif e.reason == 'PREMIUM_REQUIRED':
            flash('Spotify Premium is required for this action.', 'warning')
        else:
            flash(f'Spotify resume error: {e.msg}', 'danger')
    except Exception as e:
        logger.error(f"General error during resume: {e}", exc_info=True);
        flash('An error occurred while resuming the music.', 'danger')
    return redirect(url_for('admin_panel'))


@app.route('/player/next',
           methods=['POST'])  # The 'POST' method is more secure and suitable for non-idempotent operations
@admin_login_required
@limiter.limit("5 per minute")
def player_next():
    global auto_advance_enabled  # You may also want to control auto-advance
    spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')

    if not spotify:
        flash('No Spotify connection!', 'danger')
        return redirect(url_for('admin_panel'))

    try:
        logger.info(
            f"Admin: Next song request (Device: {active_spotify_connect_device_id or '?'}).")
        spotify.next_track(device_id=active_spotify_connect_device_id)
        logger.info("Admin: Skipped to the next song.")
        flash('Skipped to the next song.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify next song error: {e}")
        if e.http_status == 401 or e.http_status == 403:
            flash('Spotify authorization error. Please authorize again.', 'danger')
            global spotify_client
            spotify_client = None
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404:
            flash(f'Next song error: Device not found or playback is not active ({e.msg})',
                  'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE':
            flash('No active Spotify device found!', 'warning')
        else:
            flash(f'Spotify next song error: {e.msg}', 'danger')
    except Exception as e:
        logger.error(f"General error while skipping to the next song: {e}", exc_info=True)
        flash('An error occurred while skipping to the next song.', 'danger')

    return redirect(url_for('admin_panel'))


# --- Other Routes ---
@app.route('/refresh-devices')
@admin_login_required
@limiter.limit("5 per minute")
def refresh_devices():
    spotify = get_spotify_client()
    if not spotify: flash('No Spotify connection!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        result = spotify.devices();
        devices = result.get('devices', [])
        logger.info(f"Spotify Connect Devices refreshed: {len(devices)} devices")
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device and not any(
                d['id'] == active_spotify_connect_device for d in devices):
            logger.warning(
                f"Active Spotify Connect device ({active_spotify_connect_device}) is not in the list. Clearing the setting.")
            settings['active_device_id'] = None;
            save_settings(settings)
            flash('The active Spotify Connect device in the settings is no longer available.',
                  'warning')
        flash('Spotify Connect device list refreshed.', 'info')
    except Exception as e:
        logger.error(f"Error while refreshing Spotify Connect Devices: {e}")
        flash('An error occurred while refreshing the Spotify Connect device list.', 'danger')
        if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
            global spotify_client;
            spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    return redirect(url_for('admin_panel'))


@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    global settings
    try:
        logger.info("Updating settings...")
        current_settings = load_settings()  # Get the most current settings
        current_settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        current_settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))

        if 'active_spotify_connect_device_id' in request.form:
            new_spotify_device_id = request.form.get('active_spotify_connect_device_id')
            current_settings[
                'active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
            logger.info(
                f"Active Spotify Connect device set: {current_settings['active_device_id']}")

        # CHANGE: Save the active playlist setting
        if 'active_playlist_uri' in request.form:
            new_playlist_uri = request.form.get('active_playlist_uri')
            current_settings[
                'active_playlist_uri'] = new_playlist_uri if new_playlist_uri else None
            logger.info(f"Active playlist set: {current_settings['active_playlist_uri']}")

        current_settings['genre_filter_mode'] = request.form.get('genre_filter_mode', 'blacklist')
        current_settings['artist_filter_mode'] = request.form.get('artist_filter_mode', 'blacklist')
        # Use 'track_filter_mode' for the song filter mode
        current_settings['track_filter_mode'] = request.form.get('song_filter_mode',
                                                                 'blacklist')  # Comes from the form as 'song_' but save as 'track_'

        save_settings(current_settings);
        settings = current_settings  # Update global settings
        logger.info(f"Settings updated: {settings}")
        flash("Settings successfully updated.", "success")
    except ValueError:
        logger.error("Invalid numeric value while updating settings.")
        flash("Invalid numeric value entered!", "danger")
    except Exception as e:
        logger.error(f"Error while updating settings: {e}", exc_info=True)
        flash("An error occurred while updating settings.", "danger")
    return redirect(url_for('admin_panel'))


@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    if os.path.exists(TOKEN_FILE): logger.warning(
        "Re-authorization while a token already exists.")
    try:
        auth_manager = get_spotify_auth();
        auth_url = auth_manager.get_authorize_url();
        logger.info("Redirecting to Spotify authorization URL.");
        return redirect(auth_url)
    except ValueError as e:
        logger.error(f"Spotify authorization error: {e}");
        flash(f"Spotify Authorization Error: {e}", "danger");
        return redirect(url_for('admin_panel'))
    except Exception as e:
        logger.error(f"Error while getting Spotify authorization URL: {e}", exc_info=True);
        flash("Could not initiate Spotify authorization.", "danger");
        return redirect(url_for('admin_panel'))


@app.route('/callback')
def callback():
    try:
        auth_manager = get_spotify_auth()
    except ValueError as e:
        logger.error(f"Callback error: {e}");
        return f"Callback Error: {e}", 500
    if 'error' in request.args:
        error = request.args.get('error');
        logger.error(f"Spotify authorization error (callback): {error}");
        return f"Spotify Authorization Error: {error}", 400
    if 'code' not in request.args: logger.error(
        "No 'code' in callback."); return "Invalid callback request.", 400
    code = request.args.get('code')
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        if not token_info: logger.error(
            "Could not get token from Spotify."); return "Could not get token.", 500
        if isinstance(token_info, str):
            logger.error(
                "get_access_token returned only a string, could not get refresh token.");
            return "Token information is incomplete.", 500
        elif not isinstance(token_info, dict):
            logger.error(
                f"get_access_token returned data in an unexpected format: {type(token_info)}");
            return "An error occurred while getting token information.", 500
        if save_token(token_info):
            global spotify_client;
            spotify_client = None  # Force recreation of the client with the new token
            logger.info("Spotify authorization successful, token saved.")
            if session.get('admin_logged_in'):
                flash("Spotify authorization completed successfully!", "success");
                return redirect(
                    url_for('admin_panel'))
            else:
                return redirect(url_for('index'))  # Redirect to the main page if not an admin
        else:
            logger.error("Could not save the received token to a file.");
            return "An error occurred while saving the token.", 500
    except spotipy.SpotifyOauthError as e:
        logger.error(f"OAuth error while getting Spotify token: {e}", exc_info=True);
        return f"Authorization error while getting token: {e}", 500
    except Exception as e:
        logger.error(f"Error while getting/saving Spotify token: {e}", exc_info=True);
        return "An error occurred while processing the token.", 500


# UPDATED: /search endpoint applies filtering and uses URI
@app.route('/search', methods=['POST'])
@limiter.limit("5 per minute")
def search():
    """Searches on Spotify and filters the results according to active filters."""
    global settings
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track')  # Search type (track or artist)
    logger.info(f"Search request: '{search_query}' (Type: {search_type})")
    if not search_query: return jsonify({'error': 'Enter a search term.'}), 400

    spotify = get_spotify_client()
    if not spotify: logger.error(
        "Search: No Spotify client."); return jsonify({'error': 'No Spotify connection.'}), 503

    try:
        items = []
        if search_type == 'artist':
            results = spotify.search(q=search_query, type='artist', limit=20, market='TR')
            items = results.get('artists', {}).get('items', [])
            logger.info(f"{len(items)} artists found on Spotify.")
        elif search_type == 'track':
            results = spotify.search(q=search_query, type='track', limit=20, market='TR')
            items = results.get('tracks', {}).get('items', [])
            logger.info(f"{len(items)} songs found on Spotify.")
        else:
            return jsonify({'error': 'Invalid search type.'}), 400

        filtered_items = []
        for item in items:
            if not item: continue
            item_uri = item.get('uri')  # Get the URI
            if not item_uri: continue

            is_allowed = True;
            reason = ""
            if search_type == 'track':
                # Check the song filter with the URI
                is_allowed, reason = check_song_filters(item_uri, spotify)
            elif search_type == 'artist':
                # Check the artist filter with the URI
                artist_uri_to_check = item_uri
                artist_name = item.get('name')
                artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
                artist_blacklist_uris = settings.get('artist_blacklist', [])
                artist_whitelist_uris = settings.get('artist_whitelist', [])

                if artist_filter_mode == 'blacklist':
                    if artist_uri_to_check in artist_blacklist_uris: is_allowed = False; reason = f"'{artist_name}' is on the blacklist."
                elif artist_filter_mode == 'whitelist':
                    if not artist_whitelist_uris:
                        is_allowed = False; reason = "The artist whitelist is empty."
                    elif artist_uri_to_check not in artist_whitelist_uris:
                        is_allowed = False; reason = f"'{artist_name}' is not on the whitelist."

                # If it passed the artist filter, apply the genre filter
                if is_allowed:
                    genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
                    genre_blacklist = [g.lower() for g in
                                       settings.get('genre_blacklist', [])]
                    genre_whitelist = [g.lower() for g in
                                       settings.get('genre_whitelist', [])]
                    run_genre_check = (genre_filter_mode == 'blacklist' and genre_blacklist) or \
                                      (genre_filter_mode == 'whitelist' and genre_whitelist)
                    if run_genre_check:
                        artist_genres = [g.lower() for g in item.get('genres', [])]
                        if not artist_genres: logger.warning(
                            f"Cannot apply genre filter (no genres): {artist_name}")
                        else:
                            if genre_filter_mode == 'blacklist':
                                if any(genre in genre_blacklist for genre in artist_genres):
                                    blocked_genre = next(
                                        (genre for genre in artist_genres if
                                         genre in genre_blacklist),
                                        "?"); is_allowed = False; reason = f"The genre '{blocked_genre}' is on the blacklist."
                            elif genre_filter_mode == 'whitelist':
                                if not genre_whitelist:
                                    is_allowed = False; reason = "The genre whitelist is empty."
                                elif not any(
                                        genre in genre_whitelist for genre in artist_genres):
                                    is_allowed = False; reason = "This genre is not on the whitelist."

            # If the item did not fail the filters, add it to the list
            if is_allowed:
                filtered_items.append(item)
            else:
                logger.debug(
                    f"Search result filtered ({reason}): {item.get('name')} ({item_uri})")

        # Format the results for the frontend (with ID and other information)
        search_results = []
        limit = 10  # Max number of results to show in the frontend
        for item in filtered_items[:limit]:
            item_id = item.get('id')  # Frontend usually expects an ID
            item_uri = item.get('uri')
            if not item_id or not item_uri: continue

            result_data = {'id': item_id, 'uri': item_uri,
                           'name': item.get('name')}  # Basic information
            images = item.get('images', [])
            if not images and 'album' in item: images = item.get('album', {}).get('images',
                                                                                  [])  # Album cover for songs
            result_data['image'] = images[-1].get('url') if images else None

            if search_type == 'artist':
                result_data['genres'] = item.get('genres', [])
            elif search_type == 'track':
                artists = item.get('artists', []);
                result_data['artist'] = ', '.join([a.get('name') for a in artists])
                result_data['artist_ids'] = [_ensure_spotify_uri(a.get('id'), 'artist') for a in
                                             artists if a.get('id')]  # Artist URIs
                result_data['album'] = item.get('album', {}).get('name')

            search_results.append(result_data)

        logger.info(
            f"Filtered {search_type} search result: {len(search_results)} items.")
        return jsonify({'results': search_results})

    except Exception as e:
        logger.error(f"Spotify search error ({search_type}): {e}", exc_info=True)
        return jsonify({'error': 'A problem occurred during the search.'}), 500


@app.route('/add-song', methods=['POST'])
@admin_login_required
@limiter.limit("5 per minute")
def add_song():
    """Song adding by admin (skips filters)."""
    global song_queue
    song_input = request.form.get('song_id', '').strip()
    if not song_input: flash("Enter a song ID/URL.", "warning"); return redirect(
        url_for('admin_panel'))

    # Convert the input to URI format
    track_uri = _ensure_spotify_uri(song_input, 'track')
    if not track_uri: flash("Invalid Spotify Song ID or URL format.", "danger"); return redirect(
        url_for('admin_panel'))

    if len(song_queue) >= settings.get('max_queue_length',
                                       20): flash("The queue is full!", "warning"); return redirect(
        url_for('admin_panel'))

    spotify = get_spotify_client()
    if not spotify: flash("Spotify authorization required.", "warning"); return redirect(
        url_for('spotify_auth'))

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: flash(f"Song not found (URI: {track_uri}).",
                                "danger"); return redirect(url_for('admin_panel'))

        artists = song_info.get('artists');
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]

        images = song_info.get('album', {}).get('images', [])
        image_url = images[0].get('url') if images else None

        song_queue.append({
            'id': track_uri,
            'name': song_info.get('name', '?'),
            'artist': ', '.join([a.get('name') for a in artists]),
            'artist_ids': artist_uris,
            'image_url': image_url,
            'added_by': 'admin',
            'added_at': time.time()
        })
        logger.info(
            f"Song added (Admin - Unfiltered): {track_uri} - {song_info.get('name')}")
        flash(f"'{song_info.get('name')}' added.", "success");
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify error while adding as admin (URI={track_uri}): {e}")
        if e.http_status == 401 or e.http_status == 403:
            flash("Spotify authorization error.", "danger");
            return redirect(
                url_for('spotify_auth'))
        elif e.http_status == 400:
            flash(f"Invalid Spotify URI: {track_uri}", "danger")
        else:
            flash(f"Spotify error: {e.msg}", "danger")
    except Exception as e:
        logger.error(f"General error while adding as admin (URI={track_uri}): {e}",
                     exc_info=True);
        flash("Error while adding song.", "danger")
    return redirect(url_for('admin_panel'))


# --- Queue Routes ---
@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Song adding by user (filters are applied)."""
    global settings, song_queue, user_requests
    if not request.is_json: return jsonify({'error': 'Invalid format.'}), 400
    data = request.get_json();
    track_identifier = data.get('track_id')
    logger.info(f"Add to queue request: identifier={track_identifier}")
    if not track_identifier: return jsonify({'error': 'Missing ID.'}), 400

    track_uri = _ensure_spotify_uri(track_identifier, 'track')
    if not track_uri:
        logger.error(f"User adding: Invalid ID format: {track_identifier}")
        return jsonify({'error': 'Invalid song ID format.'}), 400

    if len(song_queue) >= settings.get('max_queue_length',
                                       20): logger.warning("Queue is full."); return jsonify(
        {'error': 'The queue is full.'}), 429

    user_ip = request.remote_addr;
    max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: logger.warning(
        f"Limit exceeded: {user_ip}"); return jsonify(
        {'error': f'Your request limit ({max_requests}) is full.'}), 429

    spotify = get_spotify_client()
    if not spotify: logger.error(
        "Adding: No Spotify client."); return jsonify({'error': 'No Spotify connection.'}), 503

    is_allowed, reason = check_song_filters(track_uri, spotify)
    if not is_allowed:
        logger.info(f"Rejected ({reason}): {track_uri}")
        return jsonify({'error': reason}), 403

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: return jsonify(
            {'error': 'Could not get song information (re-check).'}), 500
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []);
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists]

        images = song_info.get('album', {}).get('images', [])
        image_url = images[0].get('url') if images else None

        logger.info(f"Passed filters: {song_name} ({track_uri})")

        song_queue.append({
            'id': track_uri,
            'name': song_name,
            'artist': ', '.join(artist_names),
            'artist_ids': artist_uris,
            'image_url': image_url,
            'added_by': user_ip,
            'added_at': time.time()
        })
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        logger.info(
            f"Song added (User: {user_ip}): {song_name}. Queue: {len(song_queue)}")
        return jsonify({'success': True, 'message': f"'{song_name}' added to the queue!"})

    except spotipy.SpotifyException as e:
        logger.error(f"Spotify error while user adding (URI={track_uri}): {e}")
        if e.http_status == 401 or e.http_status == 403:
            return jsonify({'error': 'Spotify authorization problem.'}), 503
        elif e.http_status == 400:
            return jsonify({'error': f"Invalid Spotify URI: {track_uri}"}), 400
        else:
            return jsonify({'error': f"Spotify error: {e.msg}"}), 500
    except Exception as e:
        logger.error(f"Error adding to queue (URI: {track_uri}): {e}", exc_info=True)
        return jsonify(
            {'error': 'An unknown problem occurred while adding the song.'}), 500


@app.route('/remove-song/<path:song_id_str>', methods=['POST'])
@admin_login_required
def remove_song(song_id_str):
    """Song removal from the queue by admin."""
    global song_queue;
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track')
    if not song_uri_to_remove:
        flash(f"Invalid song ID format: {song_id_str}", "danger")
        return redirect(url_for('admin_panel'))

    logger.debug(f"URI to be removed from the queue: {song_uri_to_remove}")
    original_length = len(song_queue)
    song_queue = [song for song in song_queue if song.get('id') != song_uri_to_remove]
    if len(song_queue) < original_length:
        logger.info(f"Song removed (Admin): URI={song_uri_to_remove}")
        flash("The song has been removed from the queue.", "success")
    else:
        logger.warning(f"Song to be removed not found: URI={song_uri_to_remove}")
        flash("The song was not found in the queue.", "warning")
    return redirect(url_for('admin_panel'))


@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue, user_requests;
    song_queue = [];
    user_requests = {}
    logger.info("Queue cleared (Admin).");
    flash("The queue has been cleared.", "success")
    return redirect(url_for('admin_panel'))


@app.route('/queue')
def view_queue():
    """Displays the song queue for users (Filtered)."""
    global spotify_client, song_queue
    currently_playing_info = None
    recently_played_info = None
    filtered_queue = []
    spotify = get_spotify_client()

    if spotify:
        try:
            recent_tracks = spotify.current_user_recently_played(limit=1)
            if recent_tracks and recent_tracks.get('items'):
                item = recent_tracks['items'][0]['track']
                track_uri = item.get('uri')
                if track_uri and track_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(track_uri, spotify)
                    if is_allowed:
                        track_name = item.get('name')
                        artists = item.get('artists', [])
                        artist_name = ', '.join([a.get('name') for a in artists])
                        images = item.get('album', {}).get('images', [])
                        image_url = images[-1].get('url') if images else None  # Get the smallest image
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in
                                       artists if a.get('id')]
                        recently_played_info = {
                            'id': track_uri, 'name': track_name, 'artist': artist_name,
                            'artist_ids': artist_uris, 'image_url': image_url
                        }
                        logger.debug(f"Last Played (Queue): {track_name}")
        except Exception as e:
            logger.error(f"Error while getting the last played song: {e}", exc_info=True)

        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item'];
                is_playing = playback.get('is_playing', False)
                track_uri = item.get('uri')
                if track_uri and track_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(track_uri, spotify)
                    if is_allowed:
                        track_name = item.get('name');
                        artists = item.get('artists', [])
                        artist_name = ', '.join([a.get('name') for a in artists]);
                        images = item.get('album', {}).get('images', [])
                        image_url = images[-1].get('url') if images else None
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in
                                       artists if a.get('id')]
                        currently_playing_info = {
                            'id': track_uri, 'name': track_name, 'artist': artist_name,
                            'artist_ids': artist_uris, 'image_url': image_url,
                            'is_playing': is_playing
                        }
                        logger.debug(
                            f"Currently Playing (Queue): {track_name} - {'Playing' if is_playing else 'Paused'}")
                    else:
                        logger.debug(
                            f"Queue Page: Playing song filtered: {item.get('name')} ({track_uri})")
        except spotipy.SpotifyException as e:
            logger.warning(f"Playback status error (Queue): {e}")
            if e.http_status == 401 or e.http_status == 403: spotify_client = None;
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        except Exception as e:
            logger.error(f"General playback status error (Queue): {e}", exc_info=True)

        for song in song_queue:
            song_uri = song.get('id')
            if song_uri and song_uri.startswith('spotify:track:'):
                is_allowed, _ = check_song_filters(song_uri, spotify)
                if is_allowed:
                    if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                        song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in
                                              song['artist_ids']]
                    filtered_queue.append(song)
                else:
                    logger.debug(
                        f"Queue Page: Song in queue filtered: {song.get('name')} ({song_uri})")
            else:
                logger.warning(f"Queue Page: Invalid song format in queue: {song}")

    return render_template(
        'queue.html',
        queue=filtered_queue,
        currently_playing_info=currently_playing_info,
        recently_played_info=recently_played_info
    )


@app.route('/api/queue')
def api_get_queue():
    """API: Returns unfiltered raw queue data (for Admin or debug)."""
    global song_queue
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue),
                    'max_length': settings.get('max_queue_length', 20)})


# --- Audio/Bluetooth API Routes (Calling ex.py) ---
@app.route('/api/audio-sinks')
@admin_login_required
def api_audio_sinks():
    logger.info("API: Requesting audio sink list (via ex.py)...")
    result = _run_command(['list_sinks'])
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code


@app.route('/api/set-audio-sink', methods=['POST'])
@admin_login_required
def api_set_audio_sink():
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json()
    sink_identifier = data.get('sink_identifier')
    if sink_identifier is None: return jsonify(
        {'success': False, 'error': 'Sink identifier required'}), 400
    logger.info(f"API: Setting default audio sink: {sink_identifier} (ex.py)...")
    result = _run_command(['set_audio_sink', '--identifier', str(sink_identifier)])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
        sinks_list_res = _run_command(['list_sinks'])
        bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
        if sinks_list_res.get('success'):
            final_result['sinks'] = sinks_list_res.get('sinks', [])
            final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
        if bt_list_res.get('success'):
            all_bt = bt_list_res.get('devices', [])
            final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
        else:
            final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code


@app.route('/api/discover-bluetooth')
@admin_login_required
def api_discover_bluetooth():
    scan_duration = request.args.get('duration', BLUETOOTH_SCAN_DURATION, type=int)
    logger.info(f"API: Bluetooth discovery (Duration: {scan_duration}s, ex.py)...")
    result = _run_command(['discover_bluetooth', '--duration', str(scan_duration)])
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code


@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json()
    device_path = data.get('device_path')
    if not device_path: return jsonify(
        {'success': False, 'error': 'device_path required'}), 400

    logger.info(f"API: Bluetooth pairing/connecting: {device_path} (ex.py)...")
    result = _run_command(['pair_bluetooth', '--path', device_path])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
        sinks_list_res = _run_command(['list_sinks'])
        bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
        if sinks_list_res.get('success'):
            final_result['sinks'] = sinks_list_res.get('sinks', [])
            final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
        if bt_list_res.get('success'):
            all_bt = bt_list_res.get('devices', [])
            final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
        else:
            final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code


@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json()
    device_path = data.get('device_path')
    if not device_path: return jsonify(
        {'success': False, 'error': 'device_path required'}), 400

    logger.info(f"API: Disconnecting Bluetooth: {device_path} (ex.py)...")
    result = _run_command(['disconnect_bluetooth', '--path', device_path])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
        sinks_list_res = _run_command(['list_sinks'])
        bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
        if sinks_list_res.get('success'):
            final_result['sinks'] = sinks_list_res.get('sinks', [])
            final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
        if bt_list_res.get('success'):
            all_bt = bt_list_res.get('devices', [])
            final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
        else:
            final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code


@app.route('/api/switch-to-alsa', methods=['POST'])
@admin_login_required
def api_switch_to_alsa():
    logger.info("API: Requesting to switch to ALSA audio output (via ex.py)...")
    result = _run_command(['switch_to_alsa'])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
        sinks_list_res = _run_command(['list_sinks'])
        bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
        if sinks_list_res.get('success'):
            final_result['sinks'] = sinks_list_res.get('sinks', [])
            final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
        if bt_list_res.get('success'):
            all_bt = bt_list_res.get('devices', [])
            final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
        else:
            final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code


@app.route('/api/restart-spotifyd', methods=['POST'])
@admin_login_required
def api_restart_spotifyd():
    logger.info("API: Spotifyd restart request received (via ex.py)...")
    success, message = restart_spotifyd()
    status_code = 200 if success else 500
    response_data = {'success': success}
    if success:
        response_data['message'] = message
    else:
        response_data['error'] = message
    sinks_list_res = _run_command(['list_sinks'])
    bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
    if sinks_list_res.get('success'):
        response_data['sinks'] = sinks_list_res.get('sinks', [])
        response_data['default_sink_name'] = sinks_list_res.get('default_sink_name')
    if bt_list_res.get('success'):
        all_bt = bt_list_res.get('devices', [])
        response_data['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
    else:
        response_data['bluetooth_devices'] = []
    return jsonify(response_data), status_code


# --- Filter Management API Routes (Updated) ---

@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    """Quick block: Adds an artist or song directly to the blacklist."""
    global settings
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json();
    item_type = data.get('type');
    identifier = data.get('identifier')
    actual_item_type = 'track' if item_type in ['song', 'track'] else 'artist'
    if actual_item_type not in ['artist', 'track']: return jsonify(
        {'success': False, 'error': 'Invalid item type (artist or track).'}), 400

    item_uri = _ensure_spotify_uri(identifier, actual_item_type)
    if not item_uri: return jsonify(
        {'success': False, 'error': f"Invalid Spotify {actual_item_type} ID/URI."}), 400

    list_key = f"{actual_item_type}_blacklist"  # Add to the blacklist
    try:
        current_settings = load_settings();
        target_list = current_settings.get(list_key, [])
        if item_uri not in target_list:
            target_list.append(item_uri);
            current_settings[list_key] = target_list;
            save_settings(current_settings)
            settings = current_settings;  # Update global settings
            logger.info(
                f"Quick Block: '{item_uri}' ({actual_item_type}) added to the blacklist.")
            return jsonify(
                {'success': True, 'message': f"'{identifier}' added to the blacklist."})
        else:
            logger.info(
                f"Quick Block: '{item_uri}' ({actual_item_type}) is already on the blacklist.")
            return jsonify(
                {'success': True, 'message': f"'{identifier}' is already on the blacklist."})
    except Exception as e:
        logger.error(f"Quick block error ({actual_item_type}, {item_uri}): {e}",
                     exc_info=True);
        return jsonify(
            {'success': False, 'error': f"Error while adding item to the blacklist: {e}"}), 500


@app.route('/api/add-to-list', methods=['POST'])
@admin_login_required
def api_add_to_list():
    """Adds an item to the specified filter list."""
    global settings
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json();
    filter_type = data.get('filter_type');
    list_type = data.get('list_type');
    item = data.get('item')

    actual_filter_type = 'track' if filter_type == 'song' else filter_type
    if actual_filter_type not in ['genre', 'artist', 'track']: return jsonify(
        {'success': False, 'error': 'Invalid filter type.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify(
        {'success': False, 'error': 'Invalid list type.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify(
        {'success': False, 'error': 'The item to be added cannot be empty.'}), 400

    item = item.strip();
    processed_item = None
    if actual_filter_type == 'genre':
        processed_item = item.lower()  # Genres are lowercase
    elif actual_filter_type in ['artist', 'track']:
        processed_item = _ensure_spotify_uri(item, actual_filter_type)  # Convert to URI
        if not processed_item: return jsonify({
                                                  'success': False,
                                                  'error': f"Invalid Spotify {actual_filter_type} ID/URI format."}), 400

    if not processed_item: return jsonify(
        {'success': False, 'error': 'The item to be processed could not be created.'}), 500

    list_key = f"{actual_filter_type}_{list_type}"  # Use the correct key (e.g., track_whitelist)
    try:
        current_settings = load_settings();
        target_list = current_settings.get(list_key, [])
        if target_list is None: target_list = []

        if processed_item not in target_list:
            target_list.append(processed_item);
            current_settings[list_key] = target_list;
            save_settings(current_settings)
            settings = current_settings;  # Update global settings
            logger.info(f"Add to List: '{processed_item}' -> '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item}' added to the list.",
                            'updated_list': settings[list_key]})
        else:
            logger.info(f"Add to List: '{processed_item}' is already in the '{list_key}' list.")
            return jsonify({'success': True, 'message': f"'{item}' is already in the list.",
                            'updated_list': target_list})
    except Exception as e:
        logger.error(f"Error adding to list ({list_key}, {item}): {e}", exc_info=True);
        return jsonify(
            {'success': False, 'error': f"Error while adding item to the list: {e}"}), 500


@app.route('/api/remove-from-list', methods=['POST'])
@admin_login_required
def api_remove_from_list():
    """Removes an item from the specified filter list."""
    global settings
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json();
    filter_type = data.get('filter_type');
    list_type = data.get('list_type');
    item = data.get('item')

    actual_filter_type = 'track' if filter_type == 'song' else filter_type
    if actual_filter_type not in ['genre', 'artist', 'track']: return jsonify(
        {'success': False, 'error': 'Invalid filter type.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify(
        {'success': False, 'error': 'Invalid list type.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify(
        {'success': False, 'error': 'The item to be removed cannot be empty.'}), 400

    item = item.strip();
    item_to_remove = None
    if actual_filter_type == 'genre':
        item_to_remove = item.lower()
    elif actual_filter_type in ['artist', 'track']:
        item_to_remove = _ensure_spotify_uri(item, actual_filter_type)  # Convert to URI

    if not item_to_remove: return jsonify(
        {'success': False, 'error': f"Invalid item format: {item}"}), 400

    list_key = f"{actual_filter_type}_{list_type}"  # Use the correct key
    try:
        current_settings = load_settings();
        target_list = current_settings.get(list_key, [])
        if target_list is None: target_list = []

        if item_to_remove in target_list:
            target_list.remove(item_to_remove);
            current_settings[list_key] = target_list;
            save_settings(current_settings)
            settings = current_settings;  # Update global settings
            logger.info(f"Remove from List: '{item_to_remove}' <- '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item}' removed from the list.",
                            'updated_list': target_list})
        else:
            logger.info(
                f"Remove from List: '{item_to_remove}' not found in the '{list_key}' list.")
            return jsonify(
                {'success': False, 'error': f"'{item}' not found in the list.",
                 'updated_list': target_list}), 404
    except Exception as e:
        logger.error(f"Error removing from list ({list_key}, {item}): {e}",
                     exc_info=True);
        return jsonify(
            {'success': False, 'error': f"Error while removing item from the list: {e}"}), 500


@app.route('/api/spotify/genres')
@admin_login_required
def api_spotify_genres():
    """
    Gets all genres from the Spotify API via the /recommendations/available-genre-seeds endpoint
    and filters them according to the 'q' query parameter.
    """
    spotify = get_spotify_client()
    if not spotify:
        return jsonify({'success': False, 'error': 'No Spotify connection.'}), 503

    try:
        auth_header = spotify._auth_headers()

        response = requests.get(
            "https://api.spotify.com/v1/recommendations/available-genre-seeds",
            headers=auth_header
        )
        response.raise_for_status()
        data = response.json()
        genres = data.get('genres', [])

        query = request.args.get('q', '').lower()
        if query:
            filtered_genres = [g for g in genres if query in g.lower()]
        else:
            filtered_genres = genres

        return jsonify({'success': True, 'genres': filtered_genres})

    except requests.HTTPError as http_err:
        logger.error(f"Spotify API HTTP error: {http_err}", exc_info=True)
        return jsonify(
            {'success': False, 'error': 'Spotify API call failed.'}), 502
    except Exception as e:
        logger.error(f"Error while getting Spotify genres: {e}", exc_info=True)
        return jsonify(
            {'success': False, 'error': 'Could not get Spotify genres.'}), 500


# API for Getting Details from Spotify IDs (Uses URI)
@app.route('/api/spotify/details', methods=['POST'])
@admin_login_required
def api_spotify_details():
    """Gets names and details for the given Spotify URI list."""
    if not request.is_json: return jsonify(
        {'success': False, 'error': 'JSON request required'}), 400
    data = request.get_json()
    uris = data.get('ids', [])  # Even if the frontend sends 'ids', they should be URIs
    id_type = data.get('type')  # 'artist' or 'track'

    logger.debug(
        f"Received /api/spotify/details request: type={id_type}, uris_count={len(uris)}")
    if uris: logger.debug(f"First few URIs: {uris[:5]}")

    if not uris or not isinstance(uris, list): return jsonify(
        {'success': False, 'error': 'Valid URI list required.'}), 400
    actual_id_type = 'track' if id_type == 'song' else id_type
    if actual_id_type not in ['artist', 'track']: return jsonify(
        {'success': False, 'error': 'Invalid type (artist or track).'}), 400

    spotify = get_spotify_client()
    if not spotify: return jsonify({'success': False, 'error': 'No Spotify connection.'}), 503

    details_map = {}
    batch_size = 50
    valid_uris = [_ensure_spotify_uri(uri, actual_id_type) for uri in uris]
    valid_uris = [uri for uri in valid_uris if uri]

    if not valid_uris:
        logger.warning("No valid Spotify URIs found in the request.")
        return jsonify({'success': True, 'details': {}})

    logger.debug(
        f"Fetching details for {len(valid_uris)} valid URIs (type: {actual_id_type})...")

    try:
        for i in range(0, len(valid_uris), batch_size):
            batch_uris = valid_uris[i:i + batch_size]
            if not batch_uris: continue
            logger.debug(f"Processing batch {i // batch_size + 1} with URIs: {batch_uris}")

            results = None;
            items = []
            try:
                if actual_id_type == 'artist':
                    results = spotify.artists(batch_uris)
                    items = results.get('artists', []) if results else []
                elif actual_id_type == 'track':
                    results = spotify.tracks(batch_uris, market='TR')
                    items = results.get('tracks', []) if results else []
            except spotipy.SpotifyException as e:
                logger.error(
                    f"Spotify API error during batch fetch (type: {actual_id_type}, batch: {batch_uris}): {e}")
                if e.http_status == 400:
                    logger.error("Likely caused by invalid URIs in the batch.");
                    continue
                else:
                    raise e

            if items:
                for item in items:
                    if item:
                        item_uri = item.get('uri')  # Use the URI
                        item_name = item.get('name')
                        if item_uri and item_name:
                            if actual_id_type == 'track':
                                artists = item.get('artists', [])
                                artist_name = ', '.join(
                                    [a.get('name') for a in artists]) if artists else ''
                                details_map[item_uri] = f"{item_name} - {artist_name}"
                            else:  # Artist
                                details_map[item_uri] = item_name
                        else:
                            logger.warning(f"Missing URI or Name in item: {item}")
                    else:
                        logger.warning("Received a null item in the batch response.")
        logger.debug(f"Successfully fetched details for {len(details_map)} items.")
        return jsonify({'success': True, 'details': details_map})

    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API error processing details (type: {actual_id_type}): {e}",
                     exc_info=True)
        return jsonify(
            {'success': False, 'error': f'Spotify API error: {e.msg}'}), e.http_status or 500
    except Exception as e:
        logger.error(f"Error fetching Spotify details (type: {actual_id_type}): {e}",
                     exc_info=True)
        return jsonify({
                           'success': False,
                           'error': 'An unknown error occurred while getting Spotify details.'}), 500


@app.route('/debug-genre-filter/<artist_id>')
def debug_genre_filter(artist_id):
    spotify = get_spotify_client()
    if not spotify:
        return jsonify({'error': 'No Spotify connection'}), 503

    uri = _ensure_spotify_uri(artist_id, 'artist')
    if not uri:
        return jsonify({'error': 'Invalid artist ID'}), 400

    try:
        artist_info = spotify.artist(uri)
        genres = [g.lower() for g in artist_info.get('genres', [])]

        return jsonify({
            'artist_name': artist_info.get('name'),
            'genres': genres,
            'filter_mode': settings.get('genre_filter_mode'),
            'genre_blacklist': settings.get('genre_blacklist'),
            'genre_whitelist': settings.get('genre_whitelist'),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Background Song Playing Thread ---
def background_queue_player():
    # CHANGE: Using 'recently_played_from_playlist' instead of 'time_profiles'.
    global spotify_client, song_queue, user_requests, settings, auto_advance_enabled, recently_played_from_playlist
    logger.info("Starting background song playing/playlist task...")
    last_played_song_uri = None

    while True:
        try:
            spotify = get_spotify_client()
            active_spotify_connect_device_id = settings.get('active_device_id')

            if not spotify or not active_spotify_connect_device_id:
                time.sleep(10)
                continue

            current_playback = None
            try:
                current_playback = spotify.current_playback(additional_types='track,episode',
                                                            market='TR')
            except spotipy.SpotifyException as pb_err:
                logger.error(f"Background: Playback control error: {pb_err}")
                if pb_err.http_status in [401, 403]:
                    spotify_client = None
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                time.sleep(10)
                continue
            except Exception as pb_err:
                logger.error(f"Background: General playback control error: {pb_err}",
                             exc_info=True)
                time.sleep(15)
                continue

            is_playing_now = current_playback.get('is_playing',
                                                  False) if current_playback else False

            # If music is not playing and auto-advance is active
            if auto_advance_enabled and not is_playing_now:
                # 1. First, check the queue
                if song_queue:
                    next_song = song_queue.pop(0)
                    next_song_uri = next_song.get('id')

                    if not next_song_uri or not next_song_uri.startswith('spotify:track:'):
                        logger.warning(
                            f"Background: Invalid URI format in the queue: {next_song_uri}")
                        continue

                    if next_song_uri == last_played_song_uri:
                        logger.debug(
                            f"Song ({next_song.get('name')}) was already the last one played, skipping.")
                        last_played_song_uri = None
                        time.sleep(1)
                        continue

                    logger.info(
                        f"Background: Playing from the queue: {next_song.get('name')} ({next_song_uri})")
                    try:
                        spotify.start_playback(device_id=active_spotify_connect_device_id,
                                               uris=[next_song_uri])
                        logger.info(
                            f"===> Started playing song: {next_song.get('name')}")
                        last_played_song_uri = next_song_uri
                        user_ip = next_song.get('added_by')
                        if user_ip and user_ip not in ['admin', 'auto-playlist']:
                            user_requests[user_ip] = max(0, user_requests.get(user_ip, 0) - 1)
                            logger.debug(
                                f"User {user_ip} limit reduced: {user_requests.get(user_ip)}")
                        time.sleep(1)
                        continue
                    except spotipy.SpotifyException as start_err:
                        logger.error(
                            f"Background: Could not start song ({next_song_uri}): {start_err}")
                        song_queue.insert(0, next_song)
                        if start_err.http_status in [401, 403]:
                            spotify_client = None
                            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                        elif start_err.http_status == 404 and 'device_id' in str(
                                start_err).lower():
                            logger.warning(
                                f"Active Spotify Connect device ({active_spotify_connect_device_id}) not found.");
                            settings['active_device_id'] = None;
                            save_settings(settings)
                        time.sleep(5)
                        continue

                # 2. If the queue is empty, add a random song from the selected playlist
                else:
                    playlist_uri = settings.get('active_playlist_uri')
                    if not playlist_uri:
                        logger.debug(
                            "Background: Queue is empty and no active playlist is selected. Waiting.")
                        time.sleep(15)
                        continue

                    logger.info(
                        f"Background: Queue is empty. A random song will be selected from the '{playlist_uri}' list.")
                    try:
                        # Get all songs from the playlist (only URIs are needed)
                        results = spotify.playlist_items(playlist_uri,
                                                         fields='items.track.uri,items.track.name',
                                                         market='TR')
                        playlist_tracks = [item['track'] for item in
                                           results.get('items', []) if
                                           item and item.get('track') and item['track'].get(
                                               'uri')]

                        if not playlist_tracks:
                            logger.warning(
                                f"The playlist '{playlist_uri}' is empty or songs could not be retrieved.")
                            time.sleep(30)
                            continue

                        # Remove recently played songs from the list
                        potential_tracks = [track for track in playlist_tracks if
                                            track['uri'] not in recently_played_from_playlist]

                        # If all songs have been played recently, reset the list
                        if not potential_tracks:
                            logger.info(
                                "All songs in the playlist have been played recently. Resetting the list.")
                            recently_played_from_playlist.clear()
                            potential_tracks = playlist_tracks

                        # Choose a random song
                        chosen_track = random.choice(potential_tracks)
                        chosen_track_uri = chosen_track.get('uri')
                        chosen_track_name = chosen_track.get('name', '?')

                        logger.info(
                            f"Randomly selected song: {chosen_track_name} ({chosen_track_uri})")

                        # Check if the selected song complies with the filters
                        is_allowed, reason = check_song_filters(chosen_track_uri, spotify)
                        if not is_allowed:
                            logger.info(
                                f"The selected song '{chosen_track_name}' failed the filters: {reason}. Another song will be tried.")
                            # Temporarily add this song to the recently played so it's not selected again
                            recently_played_from_playlist.append(chosen_track_uri)
                            time.sleep(1)
                            continue

                        # If it passed the filter, get the full song information and add it to the queue
                        song_info = spotify.track(chosen_track_uri, market='TR')
                        artists = song_info.get('artists', []);
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in
                                       artists if a.get('id')]
                        images = song_info.get('album', {}).get('images', [])
                        image_url = images[0].get('url') if images else None

                        song_queue.append({
                            'id': chosen_track_uri,
                            'name': song_info.get('name', '?'),
                            'artist': ', '.join([a.get('name') for a in artists]),
                            'artist_ids': artist_uris,
                            'image_url': image_url,
                            'added_by': 'auto-playlist',
                            'added_at': time.time()
                        })

                        # Add this song to the recently played list
                        recently_played_from_playlist.append(chosen_track_uri)
                        # Prevent the list from growing too large (half the playlist size or max 50)
                        max_recent = min(50, len(playlist_tracks) // 2)
                        if len(recently_played_from_playlist) > max_recent:
                            recently_played_from_playlist.pop(0)

                        logger.info(
                            f"'{chosen_track_name}' added to the queue to be played.")

                    except Exception as e:
                        logger.error(f"Background: Error while getting a song from the playlist: {e}",
                                     exc_info=True)
                        time.sleep(20)

            # If music is already playing
            elif is_playing_now:
                current_track_uri_now = current_playback['item'].get(
                    'uri') if current_playback.get('item') else None
                if current_track_uri_now and current_track_uri_now != last_played_song_uri:
                    logger.debug(f"Background: New song detected: {current_track_uri_now}")
                    last_played_song_uri = current_track_uri_now
                time.sleep(5)
            # If auto-advance is off and music is not playing
            else:
                time.sleep(10)

        except Exception as loop_err:
            logger.error(f"Background loop error: {loop_err}", exc_info=True)
            time.sleep(15)


@app.route('/api/set-active-playlist', methods=['POST'])
@admin_login_required
def api_set_active_playlist():
    """API: Instantly sets the clicked playlist as active."""
    global settings
    if not request.is_json:
        return jsonify({'success': False, 'error': 'JSON request required'}), 400

    data = request.get_json()
    playlist_uri = data.get(
        'playlist_uri')  # URI can be an empty string (when the selection is cleared)

    logger.info(f"API: Updating active playlist -> {playlist_uri or 'None'}")

    try:
        current_settings = load_settings()
        current_settings['active_playlist_uri'] = playlist_uri if playlist_uri else None
        save_settings(current_settings)
        settings = current_settings  # Also update global settings instantly

        message = "Automatic playlist updated." if playlist_uri else "Automatic playlist selection cleared."
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error while setting active playlist: {e}", exc_info=True)
        return jsonify(
            {'success': False, 'error': 'An error occurred while saving the setting.'}), 500


# --- Application Start ---
def check_token_on_startup():
    logger.info("Checking Spotify token on startup...")
    client = get_spotify_client()
    if client:
        logger.info("Spotify client successfully obtained on startup.")
    else:
        logger.warning(
            "Could not obtain Spotify client on startup. Authorization may be required.")


def start_queue_player():
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread",
                              daemon=True)
    thread.start()
    logger.info("Background song playing/playlist task started.")


@app.route('/api/check-port', methods=['POST'])
@admin_login_required
def check_port():
    """Checks the status of the SSH port (22)."""
    try:
        data = request.get_json()
        port = data.get('port')

        if port != 22:
            return jsonify(
                {'success': False, 'error': 'Only the SSH port (22) can be checked'})

        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()

        return jsonify({
            'success': True,
            'is_open': result == 0
        })
    except Exception as e:
        logger.error(f"Error during SSH port check: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/open-port', methods=['POST'])
@admin_login_required
def open_port():
    """Opens the SSH port (22)."""
    try:
        data = request.get_json()
        port = data.get('port')

        if port != 22:
            return jsonify({'success': False, 'error': 'Only the SSH port (22) can be opened'})

        # Opening port with netsh command for Windows
        command = f'netsh advfirewall firewall add rule name="Open SSH Port 22" dir=in action=allow protocol=TCP localport=22'
        result = _run_command(command.split())

        if result.get('success'):
            return jsonify(
                {'success': True, 'message': 'SSH port (22) successfully opened'})
        else:
            return jsonify({'success': False,
                            'error': result.get('error', 'Could not open SSH port')})
    except Exception as e:
        logger.error(f"Error during SSH port opening: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/close-port', methods=['POST'])
@admin_login_required
def close_port():
    """Closes the SSH port (22)."""
    try:
        data = request.get_json()
        port = data.get('port')

        if port != 22:
            return jsonify(
                {'success': False, 'error': 'Only the SSH port (22) can be closed'})

        # Closing port with netsh command for Windows
        command = f'netsh advfirewall firewall delete rule name="Open SSH Port 22"'
        result = _run_command(command.split())

        if result.get('success'):
            return jsonify(
                {'success': True, 'message': 'SSH port (22) successfully closed'})
        else:
            return jsonify({'success': False,
                            'error': result.get('error', 'Could not close SSH port')})
    except Exception as e:
        logger.error(f"Error during SSH port closing: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Starting Venue Music Application       ")
    logger.info("=================================================")
    logger.info(f"Settings Loaded: {SETTINGS_FILE}")
    logger.info(f"External script path: {EX_SCRIPT_PATH}")

    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('YOUR_') or \
            not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('YOUR_') or \
            not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.error("PLEASE set your Spotify API information in the app.py file!")
    else:
        logger.info("Spotify API information appears to be defined in app.py.")
        logger.info(f"Redirect URI to be used: {SPOTIFY_REDIRECT_URI}")
        logger.info(
            "!!! Make sure this URI is registered in the Spotify Developer Dashboard !!!")

    if not os.path.exists(EX_SCRIPT_PATH):
        logger.error(f"Critical Error: External script '{EX_SCRIPT_PATH}' not found!")
    else:
        logger.info(f"Testing '{EX_SCRIPT_PATH}' script...")
        test_result = _run_command(['list_sinks'], timeout=10)
        if test_result.get('success'):
            logger.info(f"'{EX_SCRIPT_PATH}' script ran successfully.")
        else:
            logger.warning(f"'{EX_SCRIPT_PATH}' script error: {test_result.get('error')}.")

    check_token_on_startup()
    start_queue_player()

    port = int(os.environ.get('PORT', 8080))
    logger.info(
        f"The application interface can be accessed at http://<SERVER_IP>:{port}.")
    logger.info(f"The admin panel can be accessed at http://<SERVER_IP>:{port}/admin.")

    app.run(host='0.0.0.0', port=8080)
