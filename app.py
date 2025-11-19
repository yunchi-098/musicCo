import os
import json
import threading
import time
import logging
import re
import subprocess
from functools import wraps
import requests
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback
import random
import socket
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import generate_csrf
 
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'
SPOTIFY_REDIRECT_URI = 'http://web-vds.tail1b3477.ts.net/callback'
SPOTIFY_SCOPE = 'user-read-playback-state user-read-private user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12
EX_SCRIPT_PATH = 'ex.py'
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
waf_logger = logging.getLogger('WAF')
waf_logger.setLevel(logging.WARNING)
waf_handler = logging.FileHandler('security_events.log')
waf_formatter = logging.Formatter('%(asctime)s - %(levelname)s - IP: %(ip)s - Rule: %(rule)s - Path: %(path)s - Data: %(data)s')
waf_handler.setFormatter(waf_formatter)
waf_logger.addHandler(waf_handler)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
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
    return dict(csrf_token=generate_csrf)

@app.before_request
def waf_middleware():
    rules = [
        {'name': 'SQL_INJECTION_1', 'pattern': r"(\b(union|select|insert|drop|update|delete|from|where)\b.*?--|\' OR \'1\'=\'1\')"},
        {'name': 'SQL_INJECTION_2', 'pattern': r"(\b(exec|execute|char|cast|convert)\b.*?--)"},
        {'name': 'XSS_SCRIPT_TAG', 'pattern': r"<script.*?>.*?</script>"},
        {'name': 'XSS_ON_EVENT', 'pattern': r"onerror=|onload=|onmouseover=|onclick="},
        {'name': 'PATH_TRAVERSAL', 'pattern': r"(\.\./|\.\.\\)"},
        {'name': 'COMMAND_INJECTION', 'pattern': r"(\b(cat|ls|whoami|uname|id|pwd|wget|curl)\s)"},
        {'name': 'MALICIOUS_USER_AGENT', 'pattern': r"(sqlmap|nmap|nikto|wpscan|nessus)"}
    ]

    user_ip = request.remote_addr
    path_and_query = request.path
    user_agent = request.headers.get('User-Agent', '')
    
    body = ''
    if request.method in ['POST', 'PUT', 'PATCH']:
        try:
            body = request.get_data(as_text=True)
        except Exception as e:
            logger.warning(f"WAF: İstek body'si okunamadı. IP: {user_ip}, Hata: {e}")

    data_to_check = {
        'path': path_and_query,
        'user_agent': user_agent,
        'body': body
    }

    for rule in rules:
        for source, data in data_to_check.items():
            if data and re.search(rule['pattern'], data, re.IGNORECASE):
                log_extra = {
                    'ip': user_ip,
                    'rule': rule['name'],
                    'path': request.path,
                    'data': f"Kaynak: {source}, Veri: {data[:200]}"
                }
                waf_logger.warning("Potansiyel Saldırı Engellendi!", extra=log_extra)
                
                return jsonify({
                    'success': False,
                    'error': 'Forbidden',
                    'message': 'İsteğiniz güvenlik politikalarımızı ihlal ettiği için reddedildi.'
                }), 403

    return None

def _ensure_spotify_uri(item_id, item_type):
    """
    Converts the given ID (or URL) into the correct Spotify URI format or returns None.
    Always uses 'spotify:track:' for songs.
    """
    if not item_id or not isinstance(item_id, str): return None
    item_id = item_id.strip()

    actual_item_type = 'track' if item_type in ['song', 'track'] else item_type
    prefix = f"spotify:{actual_item_type}:"

    if item_id.startswith(prefix): return item_id

    if ":" not in item_id: return f"{prefix}{item_id}"

    if actual_item_type == 'track' and '/track/' in item_id:
        match = re.search(r'/track/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:track:{match.group(1)}"
    elif actual_item_type == 'artist' and '/artist/' in item_id:
        match = re.search(r'/artist/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:artist:{match.group(1)}"
    elif actual_item_type == 'playlist' and '/playlist/' in item_id:
        match = re.search(r'/playlist/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:playlist:{match.group(1)}"

    logger.warning(f"Tanınmayan veya geçersiz Spotify {actual_item_type} ID/URI formatı: {item_id}")
    return None

def _run_command(command, timeout=30):
    """Helper function to run shell commands and return parsed JSON or error."""
    try:
        if command[0] == 'python3' and len(command) > 1 and command[1] == EX_SCRIPT_PATH:
             full_command = command
        elif command[0] == 'spotifyd' or command[0] == 'pgrep':
             full_command = command
        else:
             full_command = ['python3', EX_SCRIPT_PATH] + command

        logger.debug(f"Running command: {' '.join(full_command)}")
        result = subprocess.run(full_command, capture_output=True, text=True, check=True, timeout=timeout, encoding='utf-8')
        logger.debug(f"Command stdout (first 500 chars): {result.stdout[:500]}")
        try:
            if full_command[0] == 'python3' and full_command[1] == EX_SCRIPT_PATH:
                 if not result.stdout.strip():
                      logger.warning(f"Command {' '.join(full_command)} returned empty output.")
                      return {'success': False, 'error': 'Komut boş çıktı döndürdü.'}
                 return json.loads(result.stdout)
            else:
                 return {'success': True, 'output': result.stdout.strip()}
        except json.JSONDecodeError as json_err:
             logger.error(f"Failed to parse JSON output from command {' '.join(full_command)}: {json_err}")
             logger.error(f"Raw output was: {result.stdout}")
             return {'success': False, 'error': f"Komut çıktısı JSON formatında değil: {json_err}", 'raw_output': result.stdout}
    except FileNotFoundError:
        err_msg = f"Komut bulunamadı: {full_command[0]}. Yüklü ve PATH içinde mi?"
        if full_command[0] == 'python3' and len(full_command) > 1 and full_command[1] == EX_SCRIPT_PATH:
             err_msg = f"Python 3 yorumlayıcısı veya '{EX_SCRIPT_PATH}' betiği bulunamadı."
        logger.error(err_msg)
        return {'success': False, 'error': err_msg}
    except subprocess.CalledProcessError as e:
        logger.error(f"Command '{' '.join(full_command)}' failed with return code {e.returncode}. Stderr:\n{e.stderr}")
        return {'success': False, 'error': f"Komut hatası (kod {e.returncode})", 'stderr': e.stderr, 'stdout': e.stdout}
    except subprocess.TimeoutExpired:
        logger.error(f"Command '{' '.join(full_command)}' timed out after {timeout} seconds.")
        return {'success': False, 'error': f"Komut zaman aşımına uğradı ({timeout}s)."}
    except Exception as e:
        logger.error(f"Error running command '{' '.join(full_command)}': {e}", exc_info=True)
        return {'success': False, 'error': f"Beklenmedik hata: {e}"}

def get_spotifyd_pid():
    """Çalışan spotifyd süreçlerinin PID'sini bulur."""
    result = _run_command(["pgrep", "spotifyd"], timeout=5)
    if result.get('success'):
         pids = result.get('output', '').split("\n") if result.get('output') else []
         logger.debug(f"Found spotifyd PIDs: {pids}")
         return pids
    else:
         logger.error(f"Failed to get spotifyd PID: {result.get('error')}")
         return []

def restart_spotifyd():
    """Spotifyd servisini ex.py aracılığıyla yeniden başlatır."""
    logger.info("Attempting to restart spotifyd via ex.py...")
    result = _run_command(['restart_spotifyd'])
    return result.get('success', False), result.get('message', result.get('error', 'Bilinmeyen hata'))

def load_settings():
    """Ayarları dosyadan yükler, eksik filtre ayarları için varsayılanları ekler."""
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5,
        'active_device_id': None,
        'genre_filter_mode': 'blacklist',
        'artist_filter_mode': 'blacklist',
        'track_filter_mode': 'blacklist',
        'genre_blacklist': [],
        'genre_whitelist': [],
        'artist_blacklist': [],
        'artist_whitelist': [],
        'track_blacklist': [],
        'track_whitelist': [],
        'active_playlist_uri': None
    }
    settings_to_use = default_settings.copy()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: loaded = json.load(f)

            if 'song_blacklist' in loaded:
                if 'track_blacklist' not in loaded:
                    loaded['track_blacklist'] = loaded.pop('song_blacklist')
                    logger.info("Eski 'song_blacklist' ayarı 'track_blacklist' olarak taşındı.")
                else:
                    del loaded['song_blacklist']
                    logger.info("Hem 'song_blacklist' hem 'track_blacklist' bulundu, 'song_blacklist' kaldırıldı.")
            if 'song_whitelist' in loaded:
                if 'track_whitelist' not in loaded:
                    loaded['track_whitelist'] = loaded.pop('song_whitelist')
                    logger.info("Eski 'song_whitelist' ayarı 'track_whitelist' olarak taşındı.")
                else:
                    del loaded['song_whitelist']
                    logger.info("Hem 'song_whitelist' hem 'track_whitelist' bulundu, 'song_whitelist' kaldırıldı.")
            if 'song_filter_mode' in loaded:
                 if 'track_filter_mode' not in loaded:
                      loaded['track_filter_mode'] = loaded.pop('song_filter_mode')
                      logger.info("Eski 'song_filter_mode' ayarı 'track_filter_mode' olarak taşındı.")
                 else:
                      del loaded['song_filter_mode']
                      logger.info("Hem 'song_filter_mode' hem 'track_filter_mode' bulundu, 'song_filter_mode' kaldırıldı.")


            settings_to_use.update(loaded)
            updated = False
            for key, default_value in default_settings.items():
                if key not in settings_to_use:
                    logger.info(f"'{key}' ayarı dosyada bulunamadı (update sonrası), varsayılan değer ({default_value}) ekleniyor.")
                    settings_to_use[key] = default_value
                    updated = True
            if 'active_genres' in settings_to_use:
                del settings_to_use['active_genres']; logger.info("Eski 'active_genres' ayarı kaldırıldı."); updated = True
            for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
                if key in settings_to_use:
                    item_type = 'track' if 'track' in key else 'artist'
                    original_list = settings_to_use[key]
                    if original_list is None:
                        original_list = []
                        settings_to_use[key] = []
                        updated = True

                    converted_list = []
                    changed = False
                    if not isinstance(original_list, list):
                         logger.warning(f"Ayarlar yüklenirken '{key}' beklenen liste formatında değil: {type(original_list)}. Boş liste ile değiştiriliyor.")
                         original_list = []
                         settings_to_use[key] = []
                         updated = True
                         changed = True

                    for item in original_list:
                        uri = _ensure_spotify_uri(item, item_type)
                        if uri:
                            converted_list.append(uri)
                            if uri != item: changed = True
                        else:
                            logger.warning(f"Ayarlar yüklenirken '{key}' listesindeki geçersiz öğe atlandı: {item}")
                            changed = True
                    if changed:
                        settings_to_use[key] = sorted(list(set(converted_list)))
                        updated = True

            if updated:
                save_settings(settings_to_use)
            logger.info(f"Ayarlar yüklendi: {SETTINGS_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Ayar dosyası ({SETTINGS_FILE}) bozuk JSON içeriyor: {e}. Varsayılanlar kullanılacak.")
            settings_to_use = default_settings.copy()
        except Exception as e:
            logger.error(f"Ayar dosyası ({SETTINGS_FILE}) okunamadı: {e}. Varsayılanlar kullanılacak.")
            settings_to_use = default_settings.copy()
    else:
        logger.info(f"Ayar dosyası bulunamadı, varsayılanlar oluşturuluyor: {SETTINGS_FILE}")
        settings_to_use = default_settings.copy()
        save_settings(settings_to_use)
    return settings_to_use

def save_settings(current_settings):
    """Ayarları dosyaya kaydeder. Listeleri temizler, URI formatına çevirir ve sıralar."""
    try:
        settings_to_save = current_settings.copy()

        if 'genre_blacklist' in settings_to_save:
            settings_to_save['genre_blacklist'] = sorted(list(set([g.lower() for g in settings_to_save.get('genre_blacklist', []) if isinstance(g, str) and g.strip()])))
        if 'genre_whitelist' in settings_to_save:
            settings_to_save['genre_whitelist'] = sorted(list(set([g.lower() for g in settings_to_save.get('genre_whitelist', []) if isinstance(g, str) and g.strip()])))

        for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
             if key in settings_to_save:
                  cleaned_uris = set()
                  item_type = 'track' if 'track' in key else 'artist'
                  current_list = settings_to_save.get(key, [])
                  if current_list is None: current_list = []

                  if not isinstance(current_list, list):
                      logger.warning(f"Ayarlar kaydedilirken '{key}' beklenen liste formatında değil: {type(current_list)}. Boş liste olarak kaydedilecek.")
                      current_list = []

                  for item in current_list:
                      uri = _ensure_spotify_uri(item, item_type)
                      if uri:
                           cleaned_uris.add(uri)
                      else:
                           logger.warning(f"Ayarlar kaydedilirken '{key}' listesindeki geçersiz öğe atlandı: {item}")
                  settings_to_save[key] = sorted(list(cleaned_uris))

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Ayarlar kaydedildi: {SETTINGS_FILE}")
    except Exception as e:
        logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)

spotify_client = None
song_queue = []
user_requests = {}
recently_played_from_playlist = []
settings = load_settings()
auto_advance_enabled = True

def load_token():
    """Token'ı dosyadan yükler."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                token_info = json.load(f)
                if 'access_token' in token_info and 'refresh_token' in token_info:
                    logger.info(f"Token dosyadan başarıyla yüklendi: {TOKEN_FILE}")
                    return token_info
                else:
                    logger.warning(f"Token dosyasında ({TOKEN_FILE}) eksik anahtarlar var. Dosya siliniyor.")
                    try: os.remove(TOKEN_FILE)
                    except OSError as rm_err: logger.error(f"Token dosyası silinemedi: {rm_err}")
                    return None
        except json.JSONDecodeError as e:
            logger.error(f"Token dosyası ({TOKEN_FILE}) bozuk JSON içeriyor: {e}. Dosya siliniyor.")
            try: os.remove(TOKEN_FILE)
            except OSError as rm_err: logger.error(f"Bozuk token dosyası silinemedi: {rm_err}")
            return None
        except Exception as e:
            logger.error(f"Token dosyası okuma hatası ({TOKEN_FILE}): {e}", exc_info=True); return None
    else:
        logger.info(f"Token dosyası bulunamadı: {TOKEN_FILE}"); return None

def save_token(token_info):
    """Token'ı dosyaya kaydeder."""
    try:
        if not token_info or 'access_token' not in token_info or 'refresh_token' not in token_info:
            logger.error("Kaydedilecek token bilgisi eksik veya geçersiz."); return False
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_info, f, indent=4)
        logger.info(f"Token başarıyla dosyaya kaydedildi: {TOKEN_FILE}"); return True
    except Exception as e:
        logger.error(f"Token kaydetme hatası ({TOKEN_FILE}): {e}", exc_info=True); return False

def get_spotify_auth():
    """SpotifyOAuth nesnesini oluşturur."""
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
         logger.critical("KRİTİK HATA: Spotify API bilgileri (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) app.py içinde doğru şekilde ayarlanmamış!")
         raise ValueError("Spotify API bilgileri eksik veya yanlış!")
    logger.debug(f"SpotifyOAuth oluşturuluyor. Redirect URI: {SPOTIFY_REDIRECT_URI}")
    return SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPE, open_browser=False, cache_path=None)

def get_spotify_client():
    """Mevcut Spotify istemcisini döndürür veya yenisini oluşturur/yeniler."""
    global spotify_client
    if spotify_client:
        try:
            spotify_client.current_user(); logger.debug("Mevcut Spotify istemcisi geçerli."); return spotify_client
        except spotipy.SpotifyException as e:
            logger.warning(f"Mevcut Spotify istemcisi ile hata ({e.http_status}): {e.msg}. Yeniden oluşturulacak."); spotify_client = None
        except Exception as e:
            logger.error(f"Mevcut Spotify istemcisi ile bilinmeyen hata: {e}. Yeniden oluşturulacak.", exc_info=True); spotify_client = None

    token_info = load_token()
    if not token_info: logger.info("Geçerli token bulunamadı. Yetkilendirme gerekli."); return None

    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(f"Spotify yetkilendirme yöneticisi oluşturulamadı: {e}"); return None

    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token süresi dolmuş, yenileniyor...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val: logger.error("Refresh token bulunamadı. Token dosyası siliniyor."); os.remove(TOKEN_FILE); return None
            try:
                auth_manager.token = token_info
                new_token_info = auth_manager.refresh_access_token(refresh_token_val)
                if not new_token_info: logger.error("Token yenilenemedi (API'den boş yanıt?). Token dosyası siliniyor."); os.remove(TOKEN_FILE); return None
                if isinstance(new_token_info, str):
                    logger.warning("refresh_access_token sadece access token döndürdü. Eski token bilgisiyle birleştiriliyor.")
                    token_info['access_token'] = new_token_info; token_info['expires_at'] = int(time.time()) + 3600; new_token_info = token_info
                elif not isinstance(new_token_info, dict):
                     logger.error(f"Token yenileme beklenmedik formatta veri döndürdü: {type(new_token_info)}. Token dosyası siliniyor."); os.remove(TOKEN_FILE); return None
                logger.info("Token başarıyla yenilendi.")
                if not save_token(new_token_info): logger.error("Yenilenen token kaydedilemedi!")
                token_info = new_token_info
            except spotipy.SpotifyOauthError as oauth_err:
                 logger.error(f"Token yenileme sırasında OAuth hatası: {oauth_err}. Refresh token geçersiz olabilir. Token dosyası siliniyor."); os.remove(TOKEN_FILE); return None
            except Exception as refresh_err: logger.error(f"Token yenileme sırasında beklenmedik hata: {refresh_err}", exc_info=True); return None

        access_token = token_info.get('access_token')
        if not access_token: logger.error("Token bilgisinde access_token bulunamadı."); return None
        new_spotify_client = spotipy.Spotify(auth=access_token)
        try:
            user_info = new_spotify_client.current_user()
            logger.info(f"Spotify istemcisi başarıyla oluşturuldu/doğrulandı. Kullanıcı: {user_info.get('display_name', '?')}")
            spotify_client = new_spotify_client
            return spotify_client
        except spotipy.SpotifyException as e:
            logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası ({e.http_status}): {e.msg}. Token geçersiz olabilir.")
            if e.http_status == 401 or e.http_status == 403: logger.warning("Yetkilendirme hatası alındı. Token dosyası siliniyor."); os.remove(TOKEN_FILE)
            return None
        except Exception as e: logger.error(f"Yeni Spotify istemcisi ile doğrulama sırasında bilinmeyen hata: {e}", exc_info=True); return None
    except spotipy.SpotifyOauthError as e: logger.error(f"Spotify OAuth hatası: {e}. API anahtarları veya URI yanlış olabilir."); return None
    except Exception as e: logger.error(f"Spotify istemcisi alınırken genel hata: {e}", exc_info=True); return None

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            flash("Bu sayfaya erişmek için yönetici girişi yapmalısınız.", "warning")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function


def check_song_filters(track_uri, spotify_client):
    """
    Verilen track_uri'nin filtrelere uyup uymadığını kontrol eder.
    URI formatında ('spotify:track:...') girdi bekler.
    Dönüş: (bool: is_allowed, str: reason)
    """
    global settings
    if not spotify_client: return False, "Spotify bağlantısı yok."
    if not track_uri or not isinstance(track_uri, str) or not track_uri.startswith('spotify:track:'):
        logger.error(f"check_song_filters: Geçersiz track_uri formatı: {track_uri}")
        return False, f"Geçersiz şarkı URI formatı: {track_uri}"

    logger.debug(f"Filtre kontrolü başlatılıyor: {track_uri}")
    try:
        song_info = spotify_client.track(track_uri, market='TR')
        if not song_info: return False, f"Şarkı bulunamadı (URI: {track_uri})."
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []);
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists];
        primary_artist_uri = artist_uris[0] if artist_uris else None
        logger.debug(f"Şarkı bilgileri: {song_name}, Sanatçılar: {artist_names} ({artist_uris})")

        track_blacklist_uris = settings.get('track_blacklist', [])
        track_whitelist_uris = settings.get('track_whitelist', [])
        artist_blacklist_uris = settings.get('artist_blacklist', [])
        artist_whitelist_uris = settings.get('artist_whitelist', [])
        genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
        genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]

        track_filter_mode = settings.get('track_filter_mode', 'blacklist')
        logger.debug(f"Şarkı filtresi modu: {track_filter_mode}")
        if track_filter_mode == 'whitelist':
            if not track_whitelist_uris:
                logger.debug("Filtre takıldı: Şarkı beyaz listesi boş.")
                return False, 'Şarkı beyaz listesi aktif ama boş.'
            if track_uri not in track_whitelist_uris:
                logger.debug(f"Filtre takıldı: Şarkı ({track_uri}) beyaz listede değil. Beyaz Liste: {track_whitelist_uris}")
                return False, 'Bu şarkı beyaz listede değil.'
        elif track_filter_mode == 'blacklist':
             if track_uri in track_blacklist_uris:
                logger.debug(f"Filtre takıldı: Şarkı ({track_uri}) kara listede. Kara Liste: {track_blacklist_uris}")
                return False, 'Bu şarkı kara listede.'
        logger.debug(f"Şarkı filtresinden geçti: {track_uri}")

        artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
        logger.debug(f"Sanatçı filtresi modu: {artist_filter_mode}")
        if artist_filter_mode == 'blacklist':
            if any(a_uri in artist_blacklist_uris for a_uri in artist_uris if a_uri):
                blocked_artist_info = next(((a_uri, a_name) for a_uri, a_name in zip(artist_uris, artist_names) if a_uri in artist_blacklist_uris), (None, "?"))
                logger.debug(f"Filtre takıldı: Sanatçı ({blocked_artist_info[1]} - {blocked_artist_info[0]}) kara listede.")
                return False, f"'{blocked_artist_info[1]}' sanatçısı kara listede."
        elif artist_filter_mode == 'whitelist':
            if not artist_whitelist_uris:
                logger.debug("Filtre takıldı: Sanatçı beyaz listesi boş.")
                return False, 'Sanatçı beyaz listesi aktif ama boş.'
            if not any(a_uri in artist_whitelist_uris for a_uri in artist_uris if a_uri):
                logger.debug(f"Filtre takıldı: Sanatçı ({artist_names}) beyaz listede değil. Beyaz Liste: {artist_whitelist_uris}")
                return False, 'Bu sanatçı beyaz listede değil.'
        logger.debug("Sanatçı filtresinden geçti.")

        genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
        logger.debug(f"Tür filtresi modu: {genre_filter_mode}")
        run_genre_check = (genre_filter_mode == 'blacklist' and genre_blacklist) or \
                          (genre_filter_mode == 'whitelist' and genre_whitelist)

        if run_genre_check:
            artist_genres = []
            if primary_artist_uri:
                try:
                    artist_info = spotify_client.artist(primary_artist_uri)
                    artist_genres = [g.lower() for g in artist_info.get('genres', [])]
                    logger.debug(f"Sanatçı türleri ({primary_artist_uri}): {artist_genres}")
                except Exception as e: logger.warning(f"Tür filtresi: Sanatçı türleri alınamadı ({primary_artist_uri}): {e}")

            if not artist_genres: logger.warning(f"Tür filtresi uygulanamıyor (türler yok): {song_name}. İzin veriliyor.")
            else:
                if genre_filter_mode == 'blacklist':
                    if any(genre in genre_blacklist for genre in artist_genres):
                        blocked_genre = next((genre for genre in artist_genres if genre in genre_blacklist), "?")
                        logger.debug(f"Filtre takıldı: Tür ({blocked_genre}) kara listede.")
                        return False, f"'{blocked_genre}' türü kara listede."
                elif genre_filter_mode == 'whitelist':
                    if not genre_whitelist:
                         logger.debug("Filtre takıldı: Tür beyaz listesi boş.")
                         return False, 'Tür beyaz listesi aktif ama boş.'
                    if not any(genre in genre_whitelist for genre in artist_genres):
                        logger.debug(f"Filtre takıldı: Tür ({artist_genres}) beyaz listede değil. Beyaz Liste: {genre_whitelist}")
                        return False, 'Bu tür beyaz listede değil.'
            logger.debug("Tür filtresinden geçti.")
        else:
             logger.debug("Tür filtresi uygulanmadı (mod blacklist/whitelist değil veya ilgili liste boş).")

        logger.debug(f"Filtre kontrolü tamamlandı: İzin verildi - {track_uri}")
        return True, "Filtrelerden geçti."

    except spotipy.SpotifyException as e:
        logger.error(f"Filtre kontrolü sırasında Spotify hatası (URI={track_uri}): {e}")
        if e.http_status == 400: return False, f"Geçersiz Spotify Şarkı URI: {track_uri}"
        return False, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"Filtre kontrolü sırasında hata (URI={track_uri}): {e}", exc_info=True)
        return False, "Filtre kontrolü sırasında bilinmeyen hata."

@app.route('/')
def index():
    """Ana sayfayı gösterir."""
    return render_template('index.html', allowed_genres=ALLOWED_GENRES)

@app.route('/admin')
def admin():
    """Admin giriş sayfasını veya paneli gösterir."""
    if session.get('admin_logged_in'): return redirect(url_for('admin_panel'))
    return render_template('admin.html',csrf_token=generate_csrf())

@app.route('/admin-login', methods=['POST'])
@limiter.limit("3 per minute")
def admin_login():
    """Admin giriş isteğini işler."""
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123")
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True; logger.info("Admin girişi başarılı")
        flash("Yönetim paneline hoş geldiniz!", "success"); return redirect(url_for('admin_panel'))
    else:
        logger.warning("Başarısız admin girişi denemesi"); flash("Yanlış şifre girdiniz.", "danger")
        return redirect(url_for('admin'))

@app.route('/logout')
@admin_login_required
def logout():
    """Admin çıkış işlemini yapar."""
    global spotify_client; spotify_client = None; session.clear()
    logger.info("Admin çıkışı yapıldı."); flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    """Yönetim panelini gösterir. Ayarları ve listeleri şablona gönderir."""
    global auto_advance_enabled, settings, song_queue
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None
    filtered_queue = []
    
    user_playlists = []
    paginated_playlists = []
    page = request.args.get('page', 1, type=int)
    per_page = 8
    total_pages = 1

    audio_sinks_result = _run_command(['list_sinks'])
    audio_sinks = audio_sinks_result.get('sinks', []) if audio_sinks_result.get('success') else []
    default_audio_sink_name = audio_sinks_result.get('default_sink_name') if audio_sinks_result.get('success') else None
    if not audio_sinks_result.get('success'):
        flash(f"Ses cihazları listelenemedi: {audio_sinks_result.get('error', 'Bilinmeyen hata')}", "danger")

    if spotify:
        spotify_authenticated = True
        session['spotify_authenticated'] = True
        try:
            result = spotify.devices(); spotify_devices = result.get('devices', [])
            
            try:
                all_playlists = []
                results = spotify.current_user_playlists(limit=50)
                all_playlists.extend(results['items'])
                while results['next']:
                    results = spotify.next(results)
                    all_playlists.extend(results['items'])
                user_playlists = all_playlists
                logger.info(f"{len(user_playlists)} adet çalma listesi bulundu.")

                total_items = len(user_playlists)
                total_pages = (total_items + per_page - 1) // per_page
                start = (page - 1) * per_page
                end = start + per_page
                paginated_playlists = user_playlists[start:end]

            except Exception as pl_err:
                logger.warning(f"Kullanıcının çalma listeleri alınamadı: {pl_err}")
                flash("Spotify çalma listeleriniz alınırken bir hata oluştu.", "warning")

            try: user = spotify.current_user(); spotify_user = user.get('display_name', '?'); session['spotify_user'] = spotify_user
            except Exception as user_err: logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}"); session.pop('spotify_user', None)
            
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']; is_playing = playback.get('is_playing', False)
                    track_uri = item.get('uri')
                    if track_uri and track_uri.startswith('spotify:track:'):
                         is_allowed, _ = check_song_filters(track_uri, spotify)
                         track_name = item.get('name', '?'); artists = item.get('artists', [])
                         artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
                         artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
                         images = item.get('album', {}).get('images', []); image_url = images[0].get('url') if images else None
                         currently_playing_info = {
                             'id': track_uri, 'name': track_name, 'artist': artist_name,
                             'artist_ids': artist_uris, 'image_url': image_url, 
                             'is_playing': is_playing, 'is_allowed': is_allowed
                         }
            except Exception as pb_err: logger.warning(f"Çalma durumu alınamadı: {pb_err}")

            for song in song_queue:
                song_uri = song.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, spotify)
                    if is_allowed:
                        if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                             song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song['artist_ids']]
                        filtered_queue.append(song)
        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e.http_status} - {e.msg}")
            spotify_authenticated = False; session['spotify_authenticated'] = False
            if e.http_status in [401, 403]:
                flash("Spotify yetkilendirmesi geçersiz. Lütfen tekrar yetkilendirin.", "warning")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                spotify_client = None
            else: flash(f"Spotify API hatası: {e.msg}", "danger")
        except Exception as e:
            logger.error(f"Admin panelinde beklenmedik hata: {e}", exc_info=True)
            spotify_authenticated = False; session['spotify_authenticated'] = False
            flash("Beklenmedik bir hata oluştu.", "danger")
    else:
        spotify_authenticated = False; session['spotify_authenticated'] = False
        if not os.path.exists(TOKEN_FILE): flash("Spotify hesabınızı bağlamak için yetkilendirme yapın.", "info")
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
        paginated_playlists=paginated_playlists,
        page=page,
        total_pages=total_pages,
        active_playlist_uri=settings.get('active_playlist_uri'),
        csrf_token=generate_csrf()
    )
