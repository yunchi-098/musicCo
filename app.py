# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse ve URI kontrolü için
import subprocess # ex.py ve spotifyd için
from functools import wraps
import requests # Last.fm API çağrıları için eklendi
import hashlib # Last.fm API imzası için eklendi
from urllib.parse import urlencode # Last.fm API imzası için

# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi
from datetime import datetime, timedelta
# from pymongo import MongoClient # Kullanılmıyorsa kaldırılabilir
# from bson.objectid import ObjectId # Kullanılmıyorsa kaldırılabilir
import sqlite3
import bcrypt # Şifre hashleme için eklendi
from dotenv import load_dotenv # .env dosyası için eklendi

# .env dosyasını yükle
load_dotenv()

# --- Last.fm API Yapılandırması ---
LASTFM_API_KEY = os.getenv('LASTFM_API_KEY')
LASTFM_SHARED_SECRET = os.getenv('LASTFM_SHARED_SECRET') # .env dosyasından yüklenecek
LASTFM_API_URL = "http://ws.audioscrobbler.com/2.0/"
LASTFM_REDIRECT_URI = os.getenv('LASTFM_REDIRECT_URI') # .env dosyasından yüklenecek
LASTFM_SESSION_FILE = 'lastfm_session.json'
# ---------------------------------

# --- Yapılandırılabilir Ayarlar ---
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', 'YOUR_SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', 'YOUR_SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:9187/callback')

SPOTIFY_SCOPE = 'user-read-playback-state user-read-private user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12 # Saniye cinsinden Bluetooth tarama süresi
EX_SCRIPT_PATH = 'ex.py' # ex.py betiğinin yolu
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
# ---------------------------------

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24)) # .env'den veya rastgele
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION
app.jinja_env.globals['ALLOWED_GENRES'] = ALLOWED_GENRES

# --- Last.fm Yardımcı Fonksiyonları ---
def _generate_lastfm_signature(params, secret):
    """Last.fm API çağrıları için imza oluşturur."""
    # Parametreleri anahtarlarına göre alfabetik olarak sırala
    sorted_params = sorted(params.items())
    # String'i oluştur: anahtar1değer1anahtar2değer2...
    signature_string = "".join([f"{k}{v}" for k, v in sorted_params])
    # API secret'ını ekle
    signature_string += secret
    # MD5 hash'ini al
    return hashlib.md5(signature_string.encode('utf-8')).hexdigest()

def load_lastfm_session():
    """Last.fm session key'ini dosyadan yükler."""
    if os.path.exists(LASTFM_SESSION_FILE):
        try:
            with open(LASTFM_SESSION_FILE, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
                # Temel anahtarların varlığını kontrol et
                if 'username' in session_data and 'session_key' in session_data:
                    logger.info(f"Last.fm session dosyadan yüklendi: {LASTFM_SESSION_FILE}")
                    return session_data
                else:
                    logger.warning(f"Last.fm session dosyasında ({LASTFM_SESSION_FILE}) eksik anahtarlar var. Dosya siliniyor.")
                    try: os.remove(LASTFM_SESSION_FILE)
                    except OSError as e: logger.error(f"Last.fm session dosyası silinemedi: {e}")
                    return None
        except json.JSONDecodeError as e:
            logger.error(f"Last.fm session dosyası ({LASTFM_SESSION_FILE}) bozuk JSON içeriyor: {e}. Dosya siliniyor.")
            try: os.remove(LASTFM_SESSION_FILE)
            except OSError as e_rm: logger.error(f"Bozuk Last.fm session dosyası silinemedi: {e_rm}")
            return None
        except Exception as e:
            logger.error(f"Last.fm session dosyası okuma hatası ({LASTFM_SESSION_FILE}): {e}", exc_info=True)
            return None
    return None

def save_lastfm_session(username, session_key):
    """Last.fm session key'ini dosyaya kaydeder."""
    session_data = {
        'username': username,
        'session_key': session_key,
        'retrieved_at': datetime.utcnow().isoformat()
    }
    try:
        with open(LASTFM_SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=4)
        logger.info(f"Last.fm session '{username}' için kaydedildi: {LASTFM_SESSION_FILE}")
        return True
    except Exception as e:
        logger.error(f"Last.fm session kaydetme hatası: {e}", exc_info=True)
        return False

def get_lastfm_session_key_for_user(target_username):
    """Yapılandırılmış kullanıcı için geçerli bir Last.fm session key döndürür."""
    if not target_username:
        return None
    session_data = load_lastfm_session()
    if session_data and session_data.get('username', '').lower() == target_username.lower() and session_data.get('session_key'):
        # Burada token geçerlilik süresi kontrolü Last.fm için genellikle yapılmaz, session key'ler uzun ömürlüdür.
        # İstenirse 'retrieved_at' ile bir süre kontrolü eklenebilir.
        return session_data['session_key']
    return None

# --- Spotify Auth Decorator (Mevcut) ---
def spotify_auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_spotify_client(): # Bu fonksiyon token kontrolü ve yenileme yapar
            session['next_url'] = request.url # Yetkilendirme sonrası geri dönülecek URL
            flash("Bu işlem için Spotify bağlantısı gerekli. Lütfen bağlanın.", "info")
            logger.warning(f"Spotify yetkilendirmesi gerekli, {url_for('spotify_auth_prompt')}'e yönlendiriliyor.")
            return redirect(url_for('spotify_auth_prompt'))
        return f(*args, **kwargs)
    return decorated_function

# --- Admin Giriş Decorator'ı (Mevcut) ---
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin'): # 'admin_logged_in' yerine 'admin' kullanılıyor gibi duruyor
            session['next_url'] = request.url
            flash("Bu sayfaya erişmek için admin girişi yapmalısınız.", "warning")
            return redirect(url_for('admin_login')) # 'admin' yerine 'admin_login' olmalı
        return f(*args, **kwargs)
    return decorated_function


# --- Yardımcı Fonksiyon: Spotify URI İşleme (Mevcut) ---
def _ensure_spotify_uri(item_id, item_type):
    if not item_id or not isinstance(item_id, str): return None
    item_id = item_id.strip()
    actual_item_type = 'track' if item_type in ['song', 'track'] else item_type
    prefix = f"spotify:{actual_item_type}:"
    if item_id.startswith(prefix): return item_id
    if ":" not in item_id: return f"{prefix}{item_id}"
    if actual_item_type == 'track' and '/track/' in item_id:
        match = re.search(r'/track/([a-zA-Z0-9]+)', item_id)
        if match: return f"spotify:track:{match.group(1)}"
    elif actual_item_type == 'artist' and '/artist/' in item_id:
        match = re.search(r'/artist/([a-zA-Z0-9]+)', item_id)
        if match: return f"spotify:artist:{match.group(1)}"
    logger.warning(f"Tanınmayan veya geçersiz Spotify {actual_item_type} ID/URI formatı: {item_id}")
    return None

# --- Komut Çalıştırma (Mevcut) ---
def _run_command(command, timeout=30):
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
        err_msg = f"Komut bulunamadı: {full_command[0]}."
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

# --- Spotifyd Yardımcı Fonksiyonları (Mevcut) ---
def get_spotifyd_pid():
    result = _run_command(["pgrep", "spotifyd"], timeout=5)
    if result.get('success'):
         pids = result.get('output', '').split("\n") if result.get('output') else []
         logger.debug(f"Found spotifyd PIDs: {pids}")
         return pids[0] if pids and pids[0] else None # Sadece ilk PID'yi döndür
    else:
         logger.error(f"Failed to get spotifyd PID: {result.get('error')}")
         return None

def restart_spotifyd():
    try:
        pid = get_spotifyd_pid()
        if pid:
            logger.info(f"Mevcut spotifyd süreci (PID: {pid}) sonlandırılıyor...")
            kill_result = _run_command(["kill", pid], timeout=5)
            if not kill_result.get('success'):
                 logger.warning(f"spotifyd (PID: {pid}) sonlandırılamadı: {kill_result.get('error')}. Devam ediliyor...")
            time.sleep(2)
        logger.info("spotifyd başlatılıyor...")
        # subprocess.Popen kullanarak arka planda başlatma ve logları ayırma
        process = subprocess.Popen(['spotifyd', '--no-daemon'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3) # Servisin başlaması için bekle
        
        # Sürecin hala çalışıp çalışmadığını kontrol et (isteğe bağlı)
        if process.poll() is not None: # Eğer süreç sonlandıysa, bir hata oluşmuştur
            stdout, stderr = process.communicate()
            logger.error(f"Spotifyd başlatılamadı. Çıktı:\n{stdout}\nHata:\n{stderr}")
            return False, f"Spotifyd başlatılamadı. Detaylar için loglara bakın."

        new_pid = get_spotifyd_pid()
        if new_pid:
            logger.info(f"Spotifyd başarıyla yeniden başlatıldı (Yeni PID: {new_pid})")
            return True, "Spotifyd başarıyla yeniden başlatıldı."
        else: # poll() None döndürse bile pgrep ile bulunamayabilir, bu durumu da ele al
            logger.error("Spotifyd başlatıldı ancak PID bulunamadı. Durum belirsiz.")
            return False, "Spotifyd başlatıldı ancak PID bulunamadı."
    except Exception as e:
        logger.error(f"Spotifyd yeniden başlatma hatası: {e}", exc_info=True)
        return False, f"Spotifyd yeniden başlatma hatası: {str(e)}"

# --- Ayarlar Yönetimi (Mevcut, Last.fm username içeriyor) ---
def load_settings():
    default_settings = {
        'max_queue_length': 20, 'max_user_requests': 5, 'active_device_id': None,
        'genre_filter_mode': 'blacklist', 'artist_filter_mode': 'blacklist', 'song_filter_mode': 'blacklist',
        'genre_blacklist': [], 'genre_whitelist': [],
        'artist_blacklist': [], 'artist_whitelist': [],
        'track_blacklist': [], 'track_whitelist': [],
        'lastfm_username': None,
    }
    settings_to_use = default_settings.copy()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: loaded = json.load(f)
            if 'song_blacklist' in loaded: loaded['track_blacklist'] = loaded.pop('song_blacklist')
            if 'song_whitelist' in loaded: loaded['track_whitelist'] = loaded.pop('song_whitelist')
            if 'song_filter_mode' in loaded: loaded['track_filter_mode'] = loaded.pop('song_filter_mode')
            settings_to_use.update(loaded)
            updated = False
            for key, default_value in default_settings.items():
                if key not in settings_to_use:
                    settings_to_use[key] = default_value; updated = True
            if 'active_genres' in settings_to_use: del settings_to_use['active_genres']; updated = True
            for key_list_type in [('artist_blacklist', 'artist'), ('artist_whitelist', 'artist'), ('track_blacklist', 'track'), ('track_whitelist', 'track')]:
                key, item_type = key_list_type
                if key in settings_to_use:
                    original_list = settings_to_use[key]
                    if original_list is None: original_list = []; settings_to_use[key] = []; updated = True
                    if not isinstance(original_list, list): original_list = []; settings_to_use[key] = []; updated = True
                    
                    converted_list = []; changed_in_list = False
                    for item in original_list:
                        uri = _ensure_spotify_uri(item, item_type)
                        if uri: converted_list.append(uri)
                        if uri != item : changed_in_list = True # Format değişti veya geçersiz öğe atlandı
                    if changed_in_list or len(converted_list) != len(original_list):
                        settings_to_use[key] = sorted(list(set(converted_list))); updated = True
            if updated: save_settings(settings_to_use)
            logger.info(f"Ayarlar yüklendi: {SETTINGS_FILE}")
        except Exception as e: logger.error(f"Ayar dosyası ({SETTINGS_FILE}) okunamadı: {e}. Varsayılanlar kullanılacak."); settings_to_use = default_settings.copy()
    else: logger.info(f"Ayar dosyası bulunamadı, varsayılanlar oluşturuluyor."); settings_to_use = default_settings.copy(); save_settings(settings_to_use)
    return settings_to_use

def save_settings(current_settings):
    try:
        settings_to_save = current_settings.copy()
        for key in ['genre_blacklist', 'genre_whitelist']:
            if key in settings_to_save: settings_to_save[key] = sorted(list(set([g.lower() for g in settings_to_save.get(key, []) if isinstance(g, str) and g.strip()])))
        for key_list_type in [('artist_blacklist', 'artist'), ('artist_whitelist', 'artist'), ('track_blacklist', 'track'), ('track_whitelist', 'track')]:
            key, item_type = key_list_type
            if key in settings_to_save:
                cleaned_uris = set()
                current_list = settings_to_save.get(key, [])
                if current_list is None: current_list = []
                if not isinstance(current_list, list): current_list = []
                for item in current_list:
                    uri = _ensure_spotify_uri(item, item_type)
                    if uri: cleaned_uris.add(uri)
                settings_to_save[key] = sorted(list(cleaned_uris))
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Ayarlar kaydedildi: {SETTINGS_FILE}")
    except Exception as e: logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)

# --- Global Değişkenler (Mevcut) ---
spotify_client = None
song_queue = []
user_requests = {}
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] }
settings = load_settings()
auto_advance_enabled = True

# --- Spotify Token Yönetimi (Mevcut) ---
def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f: token_info = json.load(f)
            if 'access_token' in token_info and 'refresh_token' in token_info: logger.info(f"Token dosyadan yüklendi."); return token_info
            else: logger.warning(f"Token dosyasında eksik anahtarlar. Siliniyor."); os.remove(TOKEN_FILE); return None
        except Exception as e: logger.error(f"Token dosyası okuma hatası: {e}. Siliniyor."); os.remove(TOKEN_FILE); return None
    return None

def save_token(token_info):
    try:
        if not token_info or 'access_token' not in token_info or 'refresh_token' not in token_info: logger.error("Kaydedilecek token bilgisi eksik."); return False
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f: json.dump(token_info, f, indent=4)
        logger.info(f"Token dosyaya kaydedildi."); return True
    except Exception as e: logger.error(f"Token kaydetme hatası: {e}"); return False

def get_spotify_auth():
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('YOUR_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('YOUR_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
         logger.critical("Spotify API bilgileri (CLIENT_ID, SECRET, REDIRECT_URI) .env içinde doğru ayarlanmamış!")
         raise ValueError("Spotify API bilgileri eksik veya yanlış (.env kontrol edin)!")
    return SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPE, open_browser=False, cache_path=None) # cache_path=None önemli

def get_spotify_client():
    global spotify_client
    if spotify_client:
        try: spotify_client.current_user(); logger.debug("Mevcut Spotify istemcisi geçerli."); return spotify_client
        except Exception: spotify_client = None # Hata varsa yeniden oluştur
    
    token_info = load_token()
    if not token_info: logger.info("Geçerli Spotify token bulunamadı."); return None

    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(f"SpotifyOAuth oluşturulamadı: {e}"); return None

    if auth_manager.is_token_expired(token_info):
        logger.info("Spotify token süresi dolmuş, yenileniyor...")
        try:
            # spotipy'nin token'ı dahili olarak yönetmesine izin vermek için,
            # auth_manager'a token'ı verip refresh_access_token'ı çağıralım.
            # Bu, auth_manager.token'ı güncelleyecektir.
            auth_manager.token = token_info # Önceki token'ı ayarla
            new_token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            if not new_token_info or not isinstance(new_token_info, dict) or 'access_token' not in new_token_info:
                logger.error("Token yenilenemedi (API'den boş veya geçersiz yanıt). Token dosyası siliniyor.")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                return None
            logger.info("Spotify Token başarıyla yenilendi.")
            if not save_token(new_token_info): logger.error("Yenilenen token kaydedilemedi!")
            token_info = new_token_info # Güncellenmiş token'ı kullan
        except spotipy.SpotifyOauthError as oauth_err:
            logger.error(f"Token yenileme sırasında OAuth hatası: {oauth_err}. Refresh token geçersiz olabilir. Token dosyası siliniyor.")
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            return None
        except Exception as refresh_err: logger.error(f"Token yenileme sırasında beklenmedik hata: {refresh_err}", exc_info=True); return None
    
    if 'access_token' not in token_info: logger.error("Token bilgisinde access_token yok."); return None
    
    try:
        new_spotify_client = spotipy.Spotify(auth=token_info['access_token'])
        user_info = new_spotify_client.current_user() # Test call
        logger.info(f"Spotify istemcisi başarıyla oluşturuldu/doğrulandı. Kullanıcı: {user_info.get('display_name', '?')}")
        spotify_client = new_spotify_client
        return spotify_client
    except spotipy.SpotifyException as e:
        logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası ({e.http_status}): {e.msg}.")
        if e.http_status in [401, 403]: logger.warning("Yetkilendirme hatası. Token dosyası siliniyor."); os.remove(TOKEN_FILE)
        return None
    except Exception as e: logger.error(f"Spotify istemcisi alınırken genel hata: {e}", exc_info=True); return None


# --- Zaman Profili ve Öneri Fonksiyonları (Mevcut) ---
def get_current_time_profile():
    hour = datetime.now().hour # Yerel saat yerine UTC kullanmak daha tutarlı olabilir sunucu ortamında
    if 6 <= hour < 12: return 'sabah'
    elif 12 <= hour < 18: return 'oglen'
    elif 18 <= hour < 24: return 'aksam'
    else: return 'gece'

def update_time_profile(track_uri, spotify):
    global time_profiles
    if not spotify or not track_uri or not track_uri.startswith('spotify:track:'): return
    profile_name = get_current_time_profile()
    try:
        track_info = spotify.track(track_uri, market='TR')
        if not track_info: return
        primary_artist_uri = _ensure_spotify_uri(track_info['artists'][0]['id'], 'artist') if track_info.get('artists') else None
        profile_entry = {'track_uri': track_uri, 'artist_uri': primary_artist_uri}
        if profile_entry not in time_profiles[profile_name]:
            time_profiles[profile_name].append(profile_entry)
            time_profiles[profile_name] = time_profiles[profile_name][-5:] # Son 5'i tut
            logger.info(f"'{profile_name}' profiline eklendi: '{track_info.get('name')}'")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken hata: {e}", exc_info=True)

def suggest_song_for_time(spotify):
    global time_profiles, song_queue
    if not spotify: return None
    profile_name = get_current_time_profile(); profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None
    seed_tracks, seed_artists = [], []
    for entry in reversed(profile_data):
        if entry.get('track_uri') and entry['track_uri'] not in seed_tracks: seed_tracks.append(entry['track_uri'])
        if entry.get('artist_uri') and entry['artist_uri'] not in seed_artists: seed_artists.append(entry['artist_uri'])
        if len(seed_tracks) + len(seed_artists) >= 5: break
    if not seed_tracks and not seed_artists: return None
    try:
        recs = spotify.recommendations(seed_tracks=seed_tracks[:min(len(seed_tracks), 5-len(seed_artists))], seed_artists=seed_artists[:min(len(seed_artists), 5-len(seed_tracks))], limit=5, market='TR')
        if recs and recs.get('tracks'):
            for track in recs['tracks']:
                uri = track.get('uri')
                if uri and not any(s.get('id') == uri for s in song_queue):
                    is_allowed, _ = check_song_filters(uri, spotify)
                    if is_allowed:
                        logger.info(f"'{profile_name}' için öneri (filtreden geçti): '{track.get('name')}'")
                        images = track.get('album', {}).get('images', [])
                        return {'id': uri, 'name': track.get('name'), 'artist': ', '.join([a.get('name') for a in track.get('artists', [])]), 'artist_ids': [_ensure_spotify_uri(a.get('id'), 'artist') for a in track.get('artists', []) if a.get('id')], 'image_url': images[-1].get('url') if images else None}
    except Exception as e: logger.error(f"'{profile_name}' için öneri alınırken hata: {e}", exc_info=True)
    return None

# --- Şarkı Filtreleme (Mevcut) ---
def check_song_filters(track_uri, spotify_client_instance): # Parametre adı değiştirildi
    global settings
    if not spotify_client_instance: return False, "Spotify bağlantısı yok."
    if not track_uri or not track_uri.startswith('spotify:track:'): return False, f"Geçersiz şarkı URI: {track_uri}"
    try:
        song_info = spotify_client_instance.track(track_uri, market='TR')
        if not song_info: return False, f"Şarkı bulunamadı: {track_uri}"
        
        track_filter_mode = settings.get('track_filter_mode', 'blacklist')
        track_bl = settings.get('track_blacklist', []); track_wl = settings.get('track_whitelist', [])
        if track_filter_mode == 'whitelist' and (not track_wl or track_uri not in track_wl): return False, 'Şarkı beyaz listede değil.'
        if track_filter_mode == 'blacklist' and track_uri in track_bl: return False, 'Şarkı kara listede.'

        artist_uris = [_ensure_spotify_uri(a['id'], 'artist') for a in song_info.get('artists', []) if a.get('id')]
        artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
        artist_bl = settings.get('artist_blacklist', []); artist_wl = settings.get('artist_whitelist', [])
        if artist_filter_mode == 'blacklist' and any(a_uri in artist_bl for a_uri in artist_uris if a_uri): return False, 'Sanatçı kara listede.'
        if artist_filter_mode == 'whitelist' and (not artist_wl or not any(a_uri in artist_wl for a_uri in artist_uris if a_uri)): return False, 'Sanatçı beyaz listede değil.'
        
        genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
        genre_bl = [g.lower() for g in settings.get('genre_blacklist', [])]; genre_wl = [g.lower() for g in settings.get('genre_whitelist', [])]
        run_genre_check = (genre_filter_mode == 'blacklist' and genre_bl) or (genre_filter_mode == 'whitelist' and genre_wl)
        if run_genre_check and artist_uris:
            try: artist_info = spotify_client_instance.artist(artist_uris[0]) # İlk sanatçının türleri
            except: artist_info = None
            if artist_info and artist_info.get('genres'):
                artist_genres = [g.lower() for g in artist_info['genres']]
                if genre_filter_mode == 'blacklist' and any(g in genre_bl for g in artist_genres): return False, 'Tür kara listede.'
                if genre_filter_mode == 'whitelist' and (not genre_wl or not any(g in genre_wl for g in artist_genres)): return False, 'Tür beyaz listede değil.'
        return True, "Filtrelerden geçti."
    except Exception as e: logger.error(f"Filtre kontrol hatası ({track_uri}): {e}", exc_info=True); return False, "Filtreleme hatası."


# --- Last.fm Şarkı Öneri Fonksiyonları (Mevcut, API Key & Username kullanıyor) ---
def get_lastfm_recent_tracks(username, api_key, limit=5):
    if not username or not api_key:
        logger.error("Last.fm username or API key missing for get_lastfm_recent_tracks.")
        return None
    params = {'method': 'user.getrecenttracks', 'user': username, 'api_key': api_key, 'format': 'json', 'limit': limit + 1}
    try:
        response = requests.get(LASTFM_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if 'recenttracks' in data and 'track' in data['recenttracks']:
            tracks = []
            retrieved_tracks = data['recenttracks']['track']
            if not isinstance(retrieved_tracks, list): retrieved_tracks = [retrieved_tracks]
            for track_data in retrieved_tracks:
                if len(tracks) >= limit: break
                if track_data.get('@attr', {}).get('nowplaying') == 'true': continue
                artist_info = track_data.get('artist'); artist_name = artist_info.get('#text') if isinstance(artist_info, dict) else None
                track_name = track_data.get('name')
                if track_name and artist_name: tracks.append({'name': track_name, 'artist': artist_name})
            logger.info(f"Fetched {len(tracks)} tracks from Last.fm for user {username}.")
            return tracks[:limit]
        elif 'error' in data: logger.error(f"Error from Last.fm (user: {username}): {data.get('message')} (Code: {data.get('error')})"); return None
        else: logger.error(f"Unexpected response from Last.fm for user {username}."); return None
    except Exception as e: logger.error(f"Last.fm API request failed for user {username}: {e}"); return None

def find_spotify_uri_from_lastfm_track(track_name, artist_name, spotify_client_instance): # Parametre adı değişti
    if not spotify_client_instance: return None
    query = f"track:{track_name} artist:{artist_name}"
    try:
        results = spotify_client_instance.search(q=query, type='track', limit=1, market='TR')
        if results and results['tracks']['items']: return results['tracks']['items'][0]['uri']
    except Exception as e: logger.error(f"Spotify search error for '{track_name}' by '{artist_name}': {e}")
    return None

def recommend_and_play_from_lastfm():
    global settings, spotify_client # spotify_client global'den alınacak
    
    # Spotify bağlantısını al/kontrol et
    current_spotify_client = get_spotify_client() # Bu fonksiyon token'ı yenileyebilir
    if not current_spotify_client:
        flash("Spotify bağlantısı yok. Lütfen önce Spotify'a bağlanın.", "danger")
        logger.warning("recommend_and_play_from_lastfm: Spotify client not available.")
        return False, "Spotify bağlantısı yok."

    # Last.fm yapılandırmasını kontrol et
    lastfm_username = settings.get('lastfm_username')
    if not LASTFM_API_KEY:
        logger.error("Last.fm API Key (LASTFM_API_KEY) .env dosyasında bulunamadı.")
        flash("Last.fm API anahtarı yapılandırılmamış.", "danger")
        return False, "Last.fm API anahtarı ayarlanmamış."
    if not lastfm_username:
        flash("Last.fm kullanıcı adı ayarlarda tanımlanmamış.", "warning")
        return False, "Last.fm kullanıcı adı eksik."
    
    # YENİ: Last.fm session key kontrolü
    if not LASTFM_SHARED_SECRET or not LASTFM_REDIRECT_URI:
        logger.error("Last.fm Shared Secret veya Redirect URI .env dosyasında ayarlanmamış.")
        flash("Last.fm yapılandırması eksik (Shared Secret/Redirect URI). Lütfen .env dosyasını kontrol edin.", "danger")
        return False, "Last.fm yapılandırması eksik."

    lastfm_sk = get_lastfm_session_key_for_user(lastfm_username)
    if not lastfm_sk:
        logger.info(f"Last.fm session key for user '{lastfm_username}' not found. Prompting for auth.")
        session['next_url_lastfm'] = url_for('recommend_lastfm_route') # Auth sonrası buraya dön
        flash(f"'{lastfm_username}' kullanıcısı için Last.fm bağlantısı gerekli. Lütfen Last.fm'e bağlanın.", "info")
        # Doğrudan redirect yerine, admin panelinde bir mesaj gösterip, admin'in butona basmasını sağlamak daha iyi olabilir.
        # Şimdilik, işlemi durdurup flash mesajı gösterelim. Admin panelinde bir buton olmalı.
        return False, "Last.fm bağlantısı gerekli."


    logger.info(f"Attempting to get recommendation from Last.fm for user: {lastfm_username} (using API Key)")
    recent_fm_tracks = get_lastfm_recent_tracks(lastfm_username, LASTFM_API_KEY, limit=5)

    if not recent_fm_tracks:
        flash("Last.fm'den son çalınan şarkılar alınamadı.", "warning")
        return False, "Last.fm'den şarkı alınamadı."

    seed_track_uris = []
    for fm_track in recent_fm_tracks:
        uri = find_spotify_uri_from_lastfm_track(fm_track['name'], fm_track['artist'], current_spotify_client)
        if uri: seed_track_uris.append(uri)
        if len(seed_track_uris) >= 5: break
    
    if not seed_track_uris:
        flash("Son Last.fm şarkıları için Spotify URI'leri bulunamadı.", "warning")
        return False, "Spotify URI bulunamadı."

    logger.info(f"Using {len(seed_track_uris)} seed URIs for Spotify recommendation: {seed_track_uris}")
    try:
        recs = current_spotify_client.recommendations(seed_tracks=seed_track_uris[:min(len(seed_track_uris),5)], limit=10, market='TR') # Max 5 seed
        if recs and recs['tracks']:
            for suggested_track in recs['tracks']:
                suggested_uri = suggested_track.get('uri')
                if not suggested_uri: continue
                is_allowed, reason = check_song_filters(suggested_uri, current_spotify_client)
                if not is_allowed: logger.info(f"Last.fm rec filtered ({reason}): {suggested_track.get('name')}"); continue
                
                active_device_id = settings.get('active_device_id')
                # Cihaz kontrolü ve transfer mantığı (mevcut kodunuzdaki gibi)
                if not active_device_id:
                    try:
                        devices_info = current_spotify_client.devices()
                        active_devices = [d for d in devices_info['devices'] if d.get('is_active')] if devices_info and devices_info['devices'] else []
                        if active_devices: active_device_id = active_devices[0]['id']
                        elif devices_info and devices_info['devices']:
                            active_device_id = devices_info['devices'][0]['id']
                            current_spotify_client.transfer_playback(device_id=active_device_id, force_play=False); time.sleep(1)
                        else: flash("Aktif Spotify cihazı bulunamadı.", "danger"); return False, "Spotify cihazı yok."
                    except Exception as dev_ex: flash(f"Spotify cihaz hatası: {dev_ex}", "danger"); return False, "Spotify cihaz hatası."

                track_name_rec = suggested_track.get('name', 'Bilinmeyen Şarkı')
                logger.info(f"Playing Last.fm recommended: '{track_name_rec}' ({suggested_uri}) on {active_device_id}")
                current_spotify_client.start_playback(device_id=active_device_id, uris=[suggested_uri])
                update_time_profile(suggested_uri, current_spotify_client)
                flash(f"Last.fm önerisi: '{track_name_rec}' çalınıyor.", "success")
                return True, f"'{track_name_rec}' çalınıyor."
            flash("Filtrelerden geçen uygun Last.fm önerisi bulunamadı.", "info")
            return False, "Uygun öneri yok."
        else:
            flash("Spotify'dan Last.fm geçmişine göre öneri alınamadı.", "warning")
            return False, "Spotify önerisi yok."
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify recommendation/playback error (Last.fm): {e}")
        flash(f"Spotify hatası (Last.fm öneri): {e.msg}", "danger")
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE) # Token hatası ise resetle
        return False, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"Unexpected error in recommend_and_play_from_lastfm: {e}", exc_info=True)
        flash("Last.fm önerisi işlenirken beklenmedik hata.", "danger")
        return False, "Beklenmedik hata."

# --- Flask Rotaları ---

@app.route('/')
def index():
    # Ana sayfa için Spotify yetkilendirmesi gerekip gerekmediğini kontrol et.
    # Eğer genel kullanıcı arayüzü Spotify'a bağlıysa, burada da yönlendirme yapılabilir.
    # Şimdilik, sadece admin paneli ve özellikler için yetkilendirme zorunlu.
    return render_template('index.html', allowed_genres=ALLOWED_GENRES)

# --- Spotify Auth Rotaları (Yeni/Güncellenmiş) ---
@app.route('/spotify-auth-prompt')
@admin_login_required # Sadece adminler Spotify'ı bağlayabilmeli
def spotify_auth_prompt():
    """Kullanıcıyı Spotify'a bağlanmaya teşvik eden bir sayfa gösterir."""
    return render_template('spotify_auth_prompt.html')

@app.route('/spotify-do-auth')
@admin_login_required
def spotify_do_auth(): # Eski /spotify-auth rotası
    """Spotify yetkilendirme akışını başlatır."""
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('YOUR_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('YOUR_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        flash("Spotify API bilgileri sunucuda doğru şekilde ayarlanmamış. Lütfen .env dosyasını kontrol edin.", "danger")
        logger.critical("Spotify API bilgileri (CLIENT_ID, SECRET, REDIRECT_URI) .env içinde doğru ayarlanmamış!")
        return redirect(url_for('admin_panel'))
    try:
        auth_manager = get_spotify_auth()
        auth_url = auth_manager.get_authorize_url()
        logger.info(f"Redirecting to Spotify for authorization: {auth_url}")
        return redirect(auth_url)
    except ValueError as e: # get_spotify_auth() hata fırlatırsa
        flash(f"Spotify Yetkilendirme Hatası: {e}", "danger")
        return redirect(url_for('admin_panel'))
    except Exception as e:
        logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True)
        flash("Spotify yetkilendirme başlatılamadı.", "danger")
        return redirect(url_for('admin_panel'))

@app.route('/callback') # Bu Spotify callback'i
def callback():
    """Spotify yetkilendirmesinden sonra çağrılır."""
    try:
        auth_manager = get_spotify_auth()
    except ValueError as e:
        logger.error(f"Spotify Callback hatası (OAuth setup): {e}")
        flash(f"Spotify Bağlantı Hatası: {e}", "danger")
        return redirect(url_for('admin_login' if not session.get('admin') else 'admin_panel'))

    if 'error' in request.args:
        error_msg = request.args['error']
        logger.error(f"Spotify yetkilendirme hatası (callback): {error_msg}")
        flash(f"Spotify Yetkilendirme Reddedildi: {error_msg}", "warning")
        return redirect(url_for('admin_panel' if session.get('admin') else 'index'))

    code = request.args.get('code')
    if not code:
        logger.error("Spotify callback'te 'code' parametresi eksik.")
        flash("Spotify bağlantısı sırasında geçersiz yanıt alındı.", "danger")
        return redirect(url_for('admin_panel' if session.get('admin') else 'index'))

    try:
        token_info = auth_manager.get_access_token(code, check_cache=False) # Cache kullanma
        if not token_info or not isinstance(token_info, dict) or 'access_token' not in token_info:
            logger.error("Spotify'dan token alınamadı veya format yanlış.")
            flash("Spotify'dan geçerli token alınamadı.", "danger")
            return redirect(url_for('admin_panel'))

        if save_token(token_info):
            global spotify_client; spotify_client = None # İstemciyi yeniden oluşturmaya zorla
            logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
            flash("Spotify bağlantısı başarıyla kuruldu!", "success")
            next_url = session.pop('next_url', None) # Saklanan URL'yi al
            return redirect(next_url or url_for('admin_panel')) # Öncelikli URL'ye veya admin paneline git
        else:
            logger.error("Alınan Spotify token dosyaya kaydedilemedi.")
            flash("Spotify token kaydedilirken bir hata oluştu.", "danger")
            return redirect(url_for('admin_panel'))
    except spotipy.SpotifyOauthError as e:
        logger.error(f"Spotify token alırken OAuth hatası: {e}", exc_info=True)
        flash(f"Token alınırken Spotify yetkilendirme hatası: {e}", "danger")
    except Exception as e:
        logger.error(f"Spotify token alırken/kaydederken genel hata: {e}", exc_info=True)
        flash("Spotify token işlenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))


# --- Last.fm Auth Rotaları (YENİ) ---
@app.route('/admin/lastfm-auth-prompt')
@admin_login_required
def lastfm_auth_prompt():
    """Kullanıcıyı Last.fm'e bağlanmaya teşvik eden bir sayfa gösterir."""
    if not LASTFM_API_KEY or not LASTFM_SHARED_SECRET or not LASTFM_REDIRECT_URI:
        flash("Last.fm API bilgileri (API Key, Shared Secret, Redirect URI) sunucuda tam olarak ayarlanmamış. Lütfen .env dosyasını kontrol edin.", "danger")
        return redirect(url_for('admin_panel'))
    return render_template('lastfm_auth_prompt.html', lastfm_api_key=LASTFM_API_KEY, lastfm_callback_uri=LASTFM_REDIRECT_URI)

@app.route('/admin/lastfm-do-auth')
@admin_login_required
def lastfm_do_auth():
    """Last.fm yetkilendirme akışını başlatır."""
    if not LASTFM_API_KEY or not LASTFM_SHARED_SECRET or not LASTFM_REDIRECT_URI:
        flash("Last.fm API bilgileri eksik. Lütfen .env dosyasını kontrol edin.", "danger")
        return redirect(url_for('admin_panel'))
    
    # Kullanıcıyı Last.fm yetkilendirme sayfasına yönlendir
    # Not: Last.fm &cb= parametresini doğrudan kullanmaz, bunun yerine API ayarlarınızdaki callback'e yönlendirir.
    # Ancak, bazı dokümanlar &cb kullanımını önerir, bu yüzden ekleyelim.
    auth_url = f"http://www.last.fm/api/auth/?api_key={LASTFM_API_KEY}&cb={LASTFM_REDIRECT_URI}"
    logger.info(f"Redirecting to Last.fm for authorization: {auth_url}")
    session['lastfm_intended_username'] = settings.get('lastfm_username') # Callback'te doğrulamak için
    return redirect(auth_url)

@app.route('/lastfm_callback')
@admin_login_required # Sadece admin bu callback'i işlemeli
def lastfm_callback():
    """Last.fm yetkilendirmesinden sonra çağrılır."""
    token = request.args.get('token')
    intended_username = session.pop('lastfm_intended_username', None)
    configured_username = settings.get('lastfm_username')

    if not token:
        flash("Last.fm yetkilendirme token'ı alınamadı.", "danger")
        logger.error("Last.fm callback'te 'token' parametresi eksik.")
        return redirect(url_for('admin_panel'))

    if not LASTFM_API_KEY or not LASTFM_SHARED_SECRET:
        flash("Last.fm API Key veya Shared Secret ayarlanmamış.", "danger")
        logger.error("LASTFM_API_KEY or LASTFM_SHARED_SECRET is not set for getSession.")
        return redirect(url_for('admin_panel'))

    params = {
        'method': 'auth.getSession',
        'api_key': LASTFM_API_KEY,
        'token': token,
        'format': 'json' # JSON formatında yanıt isteyelim
    }
    api_sig = _generate_lastfm_signature({'method': params['method'], 'api_key': params['api_key'], 'token': params['token']}, LASTFM_SHARED_SECRET)
    params['api_sig'] = api_sig

    try:
        response = requests.post(LASTFM_API_URL, data=params, timeout=10) # GET de çalışabilir, POST daha güvenli
        response.raise_for_status() # HTTP hatalarını fırlat
        data = response.json()

        if 'session' in data and 'key' in data['session'] and 'name' in data['session']:
            session_key = data['session']['key']
            username_from_lastfm = data['session']['name']

            # Kullanıcı adını doğrula (isteğe bağlı ama iyi bir pratik)
            if configured_username and username_from_lastfm.lower() != configured_username.lower():
                flash(f"Last.fm'den dönen kullanıcı adı ({username_from_lastfm}) ayarlardaki kullanıcı ({configured_username}) ile eşleşmiyor. Session kaydedilmedi.", "warning")
                logger.warning(f"Last.fm auth username mismatch: API returned '{username_from_lastfm}', settings has '{configured_username}'.")
                return redirect(url_for('admin_panel'))
            
            if not configured_username: # Eğer ayarlarda username yoksa, API'den geleni kullan ve kaydet
                logger.info(f"Last.fm username not in settings, using from API: {username_from_lastfm}")
                global settings
                current_settings = load_settings()
                current_settings['lastfm_username'] = username_from_lastfm
                save_settings(current_settings)
                settings = current_settings # Globali güncelle

            if save_lastfm_session(username_from_lastfm, session_key):
                flash(f"Last.fm kullanıcısı '{username_from_lastfm}' için bağlantı başarıyla kuruldu!", "success")
                logger.info(f"Last.fm session key for '{username_from_lastfm}' successfully obtained and saved.")
            else:
                flash("Last.fm session key kaydedilirken bir hata oluştu.", "danger")
        elif 'error' in data:
            flash(f"Last.fm'den session key alınamadı: {data.get('message', 'Bilinmeyen hata')} (Kod: {data.get('error')})", "danger")
            logger.error(f"Error getting Last.fm session key: {data.get('message')} (Code: {data.get('error')})")
        else:
            flash("Last.fm'den beklenmedik yanıt formatı (session key).", "danger")
            logger.error(f"Unexpected response format from Last.fm getSession: {data}")

    except requests.RequestException as e:
        flash(f"Last.fm API'sine bağlanırken hata: {e}", "danger")
        logger.error(f"Error requesting Last.fm session key: {e}", exc_info=True)
    except json.JSONDecodeError as e:
        flash("Last.fm API yanıtı işlenirken hata.", "danger")
        logger.error(f"Error decoding Last.fm getSession response: {e}", exc_info=True)
    except Exception as e:
        flash(f"Last.fm session key alınırken genel bir hata oluştu: {e}", "danger")
        logger.error(f"Generic error getting Last.fm session key: {e}", exc_info=True)
        
    next_url = session.pop('next_url_lastfm', url_for('admin_panel'))
    return redirect(next_url)


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if session.get('admin'):
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        password = request.form.get('password')
        if not password: flash('Şifre gerekli', 'error'); return redirect(url_for('admin'))
        hashed_password = get_admin_password()
        if hashed_password and verify_password(password, hashed_password):
            session['admin'] = True; flash('Başarıyla giriş yapıldı', 'success'); return redirect(url_for('admin_panel'))
        else: flash('Geçersiz şifre veya admin şifresi ayarlanmamış.', 'error'); return redirect(url_for('admin'))
    return render_template('admin_login.html') # admin.html yerine admin_login.html kullanılıyor

@app.route('/admin/login', methods=['GET', 'POST']) # Bu rota zaten admin() ile aynı işlevi görüyor, birleştirilebilir.
def admin_login():
    if session.get('admin'): return redirect(url_for('admin_panel')) # Zaten giriş yapmışsa panele yönlendir
    if request.method == 'POST':
        password = request.form.get('password')
        if not password: flash('Şifre gerekli', 'error'); return redirect(url_for('admin_login'))
        hashed_password = get_admin_password()
        if hashed_password and verify_password(password, hashed_password):
            session['admin'] = True; flash('Başarıyla giriş yapıldı', 'success')
            next_url = session.pop('next_url', url_for('admin_panel')) # Saklanan URL'yi al veya panele git
            return redirect(next_url)
        else: flash('Geçersiz şifre veya admin şifresi ayarlanmamış.', 'error'); return redirect(url_for('admin_login'))
    return render_template('admin_login.html')


@app.route('/logout') # Admin çıkışı için @admin_login_required olmamalı, herkes çıkış yapabilmeli (eğer giriş yapmışsa)
def logout():
    session.pop('admin', None)
    session.pop('spotify_authenticated', None) # Spotify session bilgilerini de temizle
    session.pop('spotify_user', None)
    # Last.fm session'ı (dosyadaki) silmek yerine, sadece Flask session'ından admin'i çıkarıyoruz.
    # Last.fm bağlantısını kesmek için ayrı bir buton/işlem olabilir.
    logger.info("Admin çıkışı yapıldı."); flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin_login'))


@app.route('/admin-panel')
@admin_login_required # Bu decorator artık session['next_url'] kullanıyor
def admin_panel():
    global auto_advance_enabled, settings, song_queue
    
    # Spotify bağlantısını al/kontrol et
    current_spotify_client = get_spotify_client() # Bu fonksiyon token'ı yenileyebilir veya None dönebilir
    spotify_authenticated = bool(current_spotify_client)
    session['spotify_authenticated'] = spotify_authenticated # Session'ı güncelle
    
    spotify_devices = []
    spotify_user = None
    currently_playing_info = None
    filtered_queue = []
    audio_sinks_result = _run_command(['list_sinks'])
    audio_sinks = audio_sinks_result.get('sinks', []) if audio_sinks_result.get('success') else []
    default_audio_sink_name = audio_sinks_result.get('default_sink_name') if audio_sinks_result.get('success') else None
    if not audio_sinks_result.get('success'):
        flash(f"Ses cihazları listelenemedi: {audio_sinks_result.get('error', 'Bilinmeyen hata')}", "danger")

    if current_spotify_client:
        try:
            result = current_spotify_client.devices(); spotify_devices = result.get('devices', [])
            user = current_spotify_client.current_user(); spotify_user = user.get('display_name', '?'); session['spotify_user'] = spotify_user
            playback = current_spotify_client.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']; track_uri = item.get('uri')
                if track_uri and track_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(track_uri, current_spotify_client)
                    images = item.get('album', {}).get('images', [])
                    currently_playing_info = {
                        'id': track_uri, 'name': item.get('name'), 'artist': ', '.join([a.get('name') for a in item.get('artists', [])]),
                        'artist_ids': [_ensure_spotify_uri(a.get('id'), 'artist') for a in item.get('artists', []) if a.get('id')],
                        'image_url': images[0].get('url') if images else None, 'is_playing': playback.get('is_playing', False),
                        'is_allowed': is_allowed
                    }
            for song in song_queue: # Kuyruğu filtrele
                song_uri = song.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, current_spotify_client)
                    if is_allowed: filtered_queue.append(song)
        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e.http_status} - {e.msg}")
            if e.http_status in [401, 403]:
                flash("Spotify yetkilendirmesi geçersiz/süresi dolmuş. Lütfen tekrar bağlanın.", "warning")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                global spotify_client; spotify_client = None; spotify_authenticated = False; session['spotify_authenticated'] = False
            else: flash(f"Spotify API hatası: {e.msg}", "danger")
        except Exception as e: logger.error(f"Admin panelinde Spotify verileri alınırken hata: {e}", exc_info=True)
    else: # current_spotify_client None ise
        spotify_authenticated = False; session['spotify_authenticated'] = False
        if not os.path.exists(TOKEN_FILE): # Token dosyası hiç yoksa
             pass # Artık spotify_auth_required decorator'ı yönlendirme yapacak.
                  # flash("Spotify hesabınızı bağlamak için lütfen yetkilendirme yapın.", "info")
    
    # Last.fm Durumu
    lastfm_api_key_set = bool(LASTFM_API_KEY)
    lastfm_config_complete = bool(LASTFM_API_KEY and LASTFM_SHARED_SECRET and LASTFM_REDIRECT_URI)
    lastfm_username_configured = settings.get('lastfm_username')
    lastfm_session_key = get_lastfm_session_key_for_user(lastfm_username_configured) if lastfm_username_configured else None
    lastfm_connected = bool(lastfm_session_key)

    return render_template(
        'admin_panel.html',
        settings=settings, spotify_devices=spotify_devices, queue=filtered_queue,
        all_genres=ALLOWED_GENRES, spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        audio_sinks=audio_sinks, default_audio_sink_name=default_audio_sink_name,
        currently_playing_info=currently_playing_info, auto_advance_enabled=auto_advance_enabled,
        LASTFM_API_KEY_SET=lastfm_api_key_set, # Bu artık çok anlamlı değil, config_complete daha iyi
        lastfm_config_complete=lastfm_config_complete,
        lastfm_username_configured=lastfm_username_configured,
        lastfm_connected=lastfm_connected
    )

# --- Çalma Kontrol Rotaları (spotify_auth_required ile korunmalı) ---
@app.route('/player/pause')
@admin_login_required
@spotify_auth_required
def player_pause():
    global auto_advance_enabled; current_spotify_client = get_spotify_client() # Yeniden al
    # current_spotify_client None olamaz çünkü decorator kontrol etti
    active_spotify_connect_device_id = settings.get('active_device_id')
    try:
        current_spotify_client.pause_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = False; flash('Müzik duraklatıldı ve otomatik geçiş kapatıldı.', 'success')
    except spotipy.SpotifyException as e:
        flash(f'Spotify duraklatma hatası: {e.msg}', 'danger')
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
    return redirect(url_for('admin_panel'))

@app.route('/player/resume')
@admin_login_required
@spotify_auth_required
def player_resume():
    current_spotify_client = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    try:
        current_spotify_client.start_playback(device_id=active_spotify_connect_device_id)
        global auto_advance_enabled; auto_advance_enabled = True
        flash('Çalma devam ediyor ve otomatik geçiş açık.', 'success')
    except spotipy.SpotifyException as e:
        flash(f'Spotify devam ettirme hatası: {e.msg}', 'danger')
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
    return redirect(url_for('admin_panel'))

@app.route('/player/skip')
@admin_login_required
@spotify_auth_required
def player_skip():
    current_spotify_client = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    try:
        # Önce kuyruktan bir şarkı çalmayı dene (Spotify Connect kuyruğu değil, kendi app kuyruğumuz)
        if song_queue:
            next_song_obj = song_queue.pop(0) # İlk şarkıyı al ve kuyruktan çıkar
            song_uri_to_play = next_song_obj.get('id')
            is_allowed, _ = check_song_filters(song_uri_to_play, current_spotify_client)
            if is_allowed:
                current_spotify_client.start_playback(device_id=active_spotify_connect_device_id, uris=[song_uri_to_play])
                flash(f"Kuyruktan '{next_song_obj.get('name')}' çalınıyor.", "success")
                update_time_profile(song_uri_to_play, current_spotify_client) # Zaman profiline ekle
                save_played_track({'id': song_uri_to_play, 'name': next_song_obj.get('name'), 'artist': next_song_obj.get('artist')}) # Çalınanları kaydet
            else:
                flash(f"'{next_song_obj.get('name')}' filtrelere takıldığı için atlandı.", "warning")
                # Filtreye takılırsa Spotify'ın kendi sıradakine geçmesini sağla
                current_spotify_client.next_track(device_id=active_spotify_connect_device_id)
                flash('Sıradaki (Spotify) şarkıya geçildi.', 'info')
        else: # Bizim kuyruğumuz boşsa, Spotify'ın kendi sıradakine geç
            current_spotify_client.next_track(device_id=active_spotify_connect_device_id)
            flash('Sıradaki (Spotify) şarkıya geçildi.', 'success')
        global auto_advance_enabled; auto_advance_enabled = True # Skip sonrası otomatik geçişi tekrar aç
    except spotipy.SpotifyException as e:
        flash(f'Spotify şarkı değiştirme hatası: {e.msg}', 'danger')
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
    return redirect(url_for('admin_panel'))


@app.route('/refresh-devices')
@admin_login_required
@spotify_auth_required # Cihazları almak için Spotify bağlantısı gerekir
def refresh_devices():
    current_spotify_client = get_spotify_client()
    try:
        result = current_spotify_client.devices(); devices = result.get('devices', [])
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device and not any(d['id'] == active_spotify_connect_device for d in devices):
            global settings
            current_settings = load_settings()
            current_settings['active_device_id'] = None; save_settings(current_settings)
            settings = current_settings
            flash('Ayarlardaki aktif Spotify Connect cihazı artık mevcut değil.', 'warning')
        flash('Spotify Connect cihaz listesi yenilendi.', 'info')
    except spotipy.SpotifyException as e: # Hata durumunu yakala
        flash(f"Spotify cihazları yenilenirken hata: {e.msg}", "danger")
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
    return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    global settings
    try:
        current_settings = load_settings()
        current_settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        current_settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        current_settings['active_device_id'] = request.form.get('active_spotify_connect_device_id') or None
        current_settings['genre_filter_mode'] = request.form.get('genre_filter_mode', 'blacklist')
        current_settings['artist_filter_mode'] = request.form.get('artist_filter_mode', 'blacklist')
        current_settings['track_filter_mode'] = request.form.get('song_filter_mode', 'blacklist') # song_filter_mode -> track_filter_mode
        
        new_lastfm_username = request.form.get('lastfm_username', '').strip() or None
        if current_settings.get('lastfm_username') != new_lastfm_username:
            logger.info(f"Last.fm username changed from '{current_settings.get('lastfm_username')}' to '{new_lastfm_username}'. Associated session key will be cleared if it exists for the old user.")
            # Eğer kullanıcı adı değiştiyse ve eski kullanıcı için bir session varsa, onu temizlemek mantıklı olabilir.
            # Şimdilik, sadece yeni kullanıcı adını kaydediyoruz. get_lastfm_session_key_for_user zaten doğru kullanıcı için kontrol edecek.
            # İstenirse, burada eski session dosyası silinebilir.
            if os.path.exists(LASTFM_SESSION_FILE): # Kullanıcı adı değişirse eski session'ı sil
                 loaded_session = load_lastfm_session()
                 if loaded_session and loaded_session.get('username') != new_lastfm_username:
                      try: os.remove(LASTFM_SESSION_FILE); logger.info("Last.fm username changed, old session file removed.")
                      except OSError as e: logger.error(f"Could not remove old Last.fm session file: {e}")
        current_settings['lastfm_username'] = new_lastfm_username

        save_settings(current_settings)
        settings = current_settings # Global ayarları güncelle
        flash("Ayarlar başarıyla güncellendi.", "success")
    except ValueError: flash("Geçersiz sayısal değer girildi!", "danger")
    except Exception as e: logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True); flash("Ayarlar güncellenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))


@app.route('/search', methods=['POST'])
@spotify_auth_required # Arama için Spotify bağlantısı gerekir
def search():
    current_spotify_client = get_spotify_client()
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track')
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400
    try:
        items_from_spotify = []
        if search_type == 'artist': results = current_spotify_client.search(q=search_query, type='artist', limit=20, market='TR'); items_from_spotify = results.get('artists', {}).get('items', [])
        elif search_type == 'track': results = current_spotify_client.search(q=search_query, type='track', limit=20, market='TR'); items_from_spotify = results.get('tracks', {}).get('items', [])
        else: return jsonify({'error': 'Geçersiz arama tipi.'}), 400
        
        filtered_items = []
        for item in items_from_spotify:
            if not item or not item.get('uri'): continue
            is_allowed = True; reason = ""
            if search_type == 'track': is_allowed, reason = check_song_filters(item['uri'], current_spotify_client)
            elif search_type == 'artist': # Sanatçı ve tür filtreleri (mevcut kodunuzdaki gibi)
                artist_uri_to_check = item['uri']; artist_name = item.get('name')
                # ... (sanatçı ve tür filtreleme mantığı buraya gelecek, check_song_filters gibi ayrı bir fonksiyona taşınabilir) ...
                # Şimdilik basitleştirilmiş:
                artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
                if artist_filter_mode == 'blacklist' and item['uri'] in settings.get('artist_blacklist', []): is_allowed = False
                if artist_filter_mode == 'whitelist' and (not settings.get('artist_whitelist', []) or item['uri'] not in settings.get('artist_whitelist', [])): is_allowed = False

            if is_allowed: filtered_items.append(item)
            else: logger.debug(f"Arama sonucu filtrelendi ({reason}): {item.get('name')}")
        
        search_results_formatted = []
        for item in filtered_items[:10]: # Max 10 sonuç göster
            res_data = {'id': item.get('id'), 'uri': item.get('uri'), 'name': item.get('name')}
            images = item.get('images', []) or item.get('album', {}).get('images', [])
            res_data['image'] = images[-1].get('url') if images else None
            if search_type == 'track': res_data['artist'] = ', '.join([a.get('name') for a in item.get('artists', [])])
            search_results_formatted.append(res_data)
        return jsonify({'results': search_results_formatted})
    except spotipy.SpotifyException as e: # Hata durumunu yakala
        flash(f"Spotify araması sırasında hata: {e.msg}", "danger")
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return jsonify({'error': 'Spotify yetkilendirme hatası, lütfen tekrar bağlanın.', 'redirect_auth': True}), e.http_status
        return jsonify({'error': 'Spotify araması sırasında sorun oluştu.'}), 500
    except Exception as e: logger.error(f"Spotify araması hatası: {e}", exc_info=True); return jsonify({'error': 'Arama sırasında sorun oluştu.'}), 500


@app.route('/add-song', methods=['POST'])
@admin_login_required
@spotify_auth_required # Şarkı eklemek için Spotify bağlantısı gerekir
def add_song():
    global song_queue; current_spotify_client = get_spotify_client()
    song_input = request.form.get('song_id', '').strip()
    track_uri = _ensure_spotify_uri(song_input, 'track')
    if not track_uri: flash("Geçersiz Spotify Şarkı ID/URL.", "danger"); return redirect(url_for('admin_panel'))
    if len(song_queue) >= settings.get('max_queue_length', 20): flash("Kuyruk dolu!", "warning"); return redirect(url_for('admin_panel'))
    try:
        song_info = current_spotify_client.track(track_uri, market='TR')
        if not song_info: flash(f"Şarkı bulunamadı: {track_uri}.", "danger"); return redirect(url_for('admin_panel'))
        # Admin eklemesi filtreleri atlar, ancak isterseniz burada da filtre uygulayabilirsiniz.
        # is_allowed, reason = check_song_filters(track_uri, current_spotify_client)
        # if not is_allowed: flash(f"Şarkı filtrelere takıldı: {reason}", "warning"); return redirect(url_for('admin_panel'))
        
        artists = song_info.get('artists', []); artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        song_queue.append({'id': track_uri, 'name': song_info.get('name', '?'), 'artist': ', '.join([a.get('name') for a in artists]), 'artist_ids': artist_uris, 'added_by': 'admin', 'added_at': time.time()})
        flash(f"'{song_info.get('name')}' eklendi (Admin).", "success");
        update_time_profile(track_uri, current_spotify_client)
    except spotipy.SpotifyException as e: # Hata durumunu yakala
        flash(f"Admin şarkı eklerken Spotify hatası: {e.msg}", "danger")
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
    except Exception as e: logger.error(f"Admin eklerken hata ({track_uri}): {e}", exc_info=True); flash("Şarkı eklenirken hata.", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/add-to-queue', methods=['POST'])
@spotify_auth_required # Kullanıcı eklemesi için de Spotify bağlantısı gerekir
def add_to_queue():
    global settings, song_queue, user_requests; current_spotify_client = get_spotify_client()
    if not request.is_json: return jsonify({'error': 'Geçersiz format.'}), 400
    data = request.get_json(); track_identifier = data.get('track_id')
    track_uri = _ensure_spotify_uri(track_identifier, 'track')
    if not track_uri: return jsonify({'error': 'Geçersiz şarkı ID formatı.'}), 400
    if len(song_queue) >= settings.get('max_queue_length', 20): return jsonify({'error': 'Kuyruk dolu.'}), 429
    user_ip = request.remote_addr; max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: return jsonify({'error': f'İstek limitiniz ({max_requests}) doldu.'}), 429
    
    is_allowed, reason = check_song_filters(track_uri, current_spotify_client)
    if not is_allowed: return jsonify({'error': reason}), 403
    try:
        song_info = current_spotify_client.track(track_uri, market='TR') # Bilgileri tekrar al
        if not song_info: return jsonify({'error': 'Şarkı bilgisi alınamadı.'}), 500
        artists = song_info.get('artists', []); artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        song_queue.append({'id': track_uri, 'name': song_info.get('name', '?'), 'artist': ', '.join([a.get('name') for a in artists]), 'artist_ids': artist_uris, 'added_by': user_ip, 'added_at': time.time()})
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        update_time_profile(track_uri, current_spotify_client)
        return jsonify({'success': True, 'message': f"'{song_info.get('name')}' kuyruğa eklendi!"})
    except spotipy.SpotifyException as e: # Hata durumunu yakala
        logger.error(f"Kullanıcı eklerken Spotify hatası ({track_uri}): {e}")
        if e.http_status in [401, 403]: return jsonify({'error': 'Spotify yetkilendirme sorunu.', 'redirect_auth': True}), e.http_status
        return jsonify({'error': f"Spotify hatası: {e.msg}"}), 500
    except Exception as e: logger.error(f"Kuyruğa ekleme hatası ({track_uri}): {e}", exc_info=True); return jsonify({'error': 'Şarkı eklenirken sorun oluştu.'}), 500

@app.route('/remove-song/<path:song_id_str>', methods=['POST'])
@admin_login_required
# Spotify bağlantısı gerektirmez, sadece kendi kuyruğumuzdan siler.
def remove_song(song_id_str):
    global song_queue;
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track')
    if not song_uri_to_remove: flash(f"Geçersiz şarkı ID formatı: {song_id_str}", "danger"); return redirect(url_for('admin_panel'))
    original_length = len(song_queue)
    song_queue = [song for song in song_queue if song.get('id') != song_uri_to_remove]
    if len(song_queue) < original_length: flash("Şarkı kuyruktan kaldırıldı.", "success")
    else: flash("Şarkı kuyrukta bulunamadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue, user_requests; song_queue = []; user_requests = {}
    flash("Kuyruk temizlendi.", "success"); return redirect(url_for('admin_panel'))

@app.route('/queue')
@spotify_auth_required # Kuyruğu ve çalanı görmek için Spotify bağlantısı gerekir
def view_queue():
    current_spotify_client = get_spotify_client()
    currently_playing_info = None; filtered_queue = []
    try:
        playback = current_spotify_client.current_playback(additional_types='track,episode', market='TR')
        if playback and playback.get('item'):
            item = playback['item']; track_uri = item.get('uri')
            if track_uri and track_uri.startswith('spotify:track:'):
                is_allowed, _ = check_song_filters(track_uri, current_spotify_client)
                if is_allowed: # Sadece izin verilen çalan şarkıyı göster
                    images = item.get('album', {}).get('images', [])
                    currently_playing_info = {'id': track_uri, 'name': item.get('name'), 'artist': ', '.join([a.get('name') for a in item.get('artists', [])]), 'image_url': images[-1].get('url') if images else None, 'is_playing': playback.get('is_playing', False)}
        for song in song_queue:
            song_uri = song.get('id')
            if song_uri and song_uri.startswith('spotify:track:'):
                is_allowed, _ = check_song_filters(song_uri, current_spotify_client)
                if is_allowed: filtered_queue.append(song)
    except spotipy.SpotifyException as e:
        logger.warning(f"Çalma durumu hatası (Kuyruk): {e}")
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt')) # Yetki hatası ise tekrar yönlendir
    except Exception as e: logger.error(f"Çalma durumu genel hatası (Kuyruk): {e}", exc_info=True)
    return render_template('queue.html', queue=filtered_queue, currently_playing_info=currently_playing_info)

# --- API Rotaları (Ses/Bluetooth - Mevcut) ---
# Bu rotalar genellikle @admin_login_required ile korunur, Spotify bağlantısı gerektirmezler.
@app.route('/api/audio-sinks')
@admin_login_required
def api_audio_sinks():
    result = _run_command(['list_sinks']); return jsonify(result), 200 if result.get('success') else 500

@app.route('/api/set-audio-sink', methods=['POST'])
@admin_login_required
def api_set_audio_sink():
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    sink_identifier = request.get_json().get('sink_identifier')
    if sink_identifier is None: return jsonify({'success': False, 'error': 'Sink ID gerekli'}), 400
    result = _run_command(['set_audio_sink', '--identifier', str(sink_identifier)])
    # Başarılıysa güncel listeleri de döndür (mevcut kodunuzdaki gibi)
    return jsonify(result), 200 if result.get('success') else 500

# ... Diğer Bluetooth API rotaları (discover, pair, disconnect) benzer şekilde kalabilir ...

@app.route('/api/restart-spotifyd', methods=['POST'])
@admin_login_required
def api_restart_spotifyd():
    success, message = restart_spotifyd()
    # Başarılıysa güncel listeleri de döndür (mevcut kodunuzdaki gibi)
    return jsonify({'success': success, 'message' if success else 'error': message}), 200 if success else 500


# --- Filtre Yönetimi API Rotaları (Mevcut, @admin_login_required ile korunur) ---
# Bu rotalar Spotify bağlantısı gerektirmez, sadece ayar dosyasını yönetir.
@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    global settings; data = request.get_json(); item_type = data.get('type'); identifier = data.get('identifier')
    actual_item_type = 'track' if item_type in ['song', 'track'] else 'artist'
    if actual_item_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz tip.'}), 400
    item_uri = _ensure_spotify_uri(identifier, actual_item_type)
    if not item_uri: return jsonify({'success': False, 'error': f"Geçersiz Spotify {actual_item_type} ID/URI."}), 400
    list_key = f"{actual_item_type}_blacklist"
    try:
        current_settings = load_settings(); target_list = current_settings.get(list_key, [])
        if item_uri not in target_list:
            target_list.append(item_uri); current_settings[list_key] = target_list; save_settings(current_settings)
            settings = current_settings; # Globali güncelle
            return jsonify({'success': True, 'message': f"'{identifier}' kara listeye eklendi."})
        return jsonify({'success': True, 'message': f"'{identifier}' zaten kara listede."})
    except Exception as e: return jsonify({'success': False, 'error': f"Engelleme hatası: {e}"}), 500

# ... Diğer filtre API rotaları (add-to-list, remove-from-list) benzer şekilde kalabilir ...

@app.route('/api/spotify/details', methods=['POST'])
@admin_login_required
@spotify_auth_required # Detayları almak için Spotify bağlantısı gerekir
def api_spotify_details():
    current_spotify_client = get_spotify_client()
    data = request.get_json(); uris_from_req = data.get('ids', []); id_type = data.get('type')
    actual_id_type = 'track' if id_type == 'song' else id_type
    if not uris_from_req or not isinstance(uris_from_req, list) or actual_id_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz istek.'}), 400
    
    valid_uris = [u for u in [_ensure_spotify_uri(uri, actual_id_type) for uri in uris_from_req] if u]
    if not valid_uris: return jsonify({'success': True, 'details': {}}) # Boş ama başarılı yanıt
    
    details_map = {}; batch_size = 50
    try:
        for i in range(0, len(valid_uris), batch_size):
            batch = valid_uris[i:i + batch_size]
            items = []
            if actual_id_type == 'artist': results = current_spotify_client.artists(batch); items = results.get('artists', []) if results else []
            elif actual_id_type == 'track': results = current_spotify_client.tracks(batch, market='TR'); items = results.get('tracks', []) if results else []
            for item in items:
                if item and item.get('uri') and item.get('name'):
                    details_map[item['uri']] = f"{item['name']}{' - ' + ', '.join([a['name'] for a in item.get('artists',[])]) if actual_id_type == 'track' and item.get('artists') else ''}"
        return jsonify({'success': True, 'details': details_map})
    except spotipy.SpotifyException as e: # Hata durumunu yakala
        logger.error(f"Spotify detayları alınırken API hatası (type: {actual_id_type}): {e}", exc_info=True)
        if e.http_status in [401, 403]: return jsonify({'success': False, 'error': 'Spotify yetkilendirme hatası.', 'redirect_auth': True}), e.http_status
        return jsonify({'success': False, 'error': f'Spotify API hatası: {e.msg}'}), e.http_status or 500
    except Exception as e: logger.error(f"Spotify detayları alınırken hata: {e}", exc_info=True); return jsonify({'success': False, 'error': 'Bilinmeyen hata.'}), 500


# --- Last.fm Öneri Rotası (Güncellendi) ---
@app.route('/admin/recommend-lastfm', methods=['POST'])
@admin_login_required
@spotify_auth_required # Spotify'dan önermek ve çalmak için Spotify bağlantısı da gerekir
def recommend_lastfm_route():
    # recommend_and_play_from_lastfm fonksiyonu zaten Last.fm session kontrolü yapıyor
    # ve gerekirse flash mesajı gösteriyor.
    success, message = recommend_and_play_from_lastfm()
    # Flash mesajları recommend_and_play_from_lastfm içinde hallediliyor.
    return redirect(url_for('admin_panel'))


# --- Arka Plan Şarkı Çalma İş Parçacığı (Mevcut) ---
def background_queue_player():
    global auto_advance_enabled, song_queue, settings
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")
    last_played_song_uri_from_queue = None # Kuyruktan en son çalınan şarkıyı takip et

    while True:
        time.sleep(5) # Her 5 saniyede bir kontrol et
        try:
            if not auto_advance_enabled: continue # Otomatik geçiş kapalıysa devam etme

            current_spotify_client = get_spotify_client() # Her döngüde token'ı kontrol et/yenile
            if not current_spotify_client:
                logger.warning("Arka plan: Spotify bağlantısı yok, 30 saniye bekleniyor...")
                time.sleep(25) # 5 saniye zaten dışarıda var
                continue

            playback = current_spotify_client.current_playback(additional_types='track,episode', market='TR')
            
            # Aktif bir çalma durumu yoksa veya bir şey çalmıyorsa
            if not playback or not playback.get('is_playing') or not playback.get('item'):
                logger.debug("Arka plan: Aktif çalma yok veya duraklatılmış. Kuyruk kontrol ediliyor.")
                if song_queue: # Kuyrukta şarkı varsa ve bir şey çalmıyorsa
                    next_song_obj = song_queue.pop(0)
                    song_uri_to_play = next_song_obj.get('id')
                    is_allowed, _ = check_song_filters(song_uri_to_play, current_spotify_client)
                    if is_allowed:
                        logger.info(f"Arka plan: Kuyruktan '{next_song_obj.get('name')}' çalınıyor...")
                        active_device_id = settings.get('active_device_id') # Ayarlardan cihaz ID'sini al
                        current_spotify_client.start_playback(device_id=active_device_id, uris=[song_uri_to_play])
                        update_time_profile(song_uri_to_play, current_spotify_client)
                        save_played_track({'id': song_uri_to_play, 'name': next_song_obj.get('name'), 'artist': next_song_obj.get('artist')})
                        last_played_song_uri_from_queue = song_uri_to_play
                    else:
                        logger.info(f"Arka plan: Kuyruktaki '{next_song_obj.get('name')}' filtrelere takıldı, atlanıyor.")
                elif settings.get('lastfm_username') and get_lastfm_session_key_for_user(settings.get('lastfm_username')): # Kuyruk boşsa ve LastFM bağlıysa öneri yap
                    logger.info("Arka plan: Kuyruk boş, Last.fm'den öneri deneniyor...")
                    recommend_and_play_from_lastfm() # Bu fonksiyon kendi içinde çalmayı başlatır
                continue # Bir sonraki döngüye geç

            # Bir şey çalıyorsa, şarkının bitip bitmediğini kontrol et
            current_item = playback.get('item')
            if current_item and playback.get('progress_ms') is not None and current_item.get('duration_ms', 0) > 0:
                progress = playback['progress_ms']
                duration = current_item['duration_ms']
                current_playing_uri = current_item.get('uri')

                # Çalınan şarkıyı veritabanına kaydet (sadece bir kez)
                # (Bu mantık save_played_track içine taşınabilir veya burada daha iyi yönetilebilir)
                # save_played_track({'id': current_playing_uri, 'name': current_item.get('name'), 'artist': ', '.join([a.get('name') for a in current_item.get('artists', [])])})


                # Şarkı sonuna yaklaştıysa (örneğin son 3 saniye)
                if duration - progress < 3000: # ms cinsinden
                    logger.info(f"Arka plan: '{current_item.get('name')}' bitmek üzere.")
                    if song_queue: # Kuyrukta şarkı varsa
                        # Eğer şu an çalan şarkı, az önce kuyruktan başlattığımız şarkı değilse (yani kullanıcı değiştirdiyse)
                        # ve kuyrukta şarkı varsa, bir sonrakine geç.
                        # Bu, kuyruktan çalınan şarkının üzerine manuel şarkı çalınırsa, şarkı bitince tekrar kuyruğa dönmesini sağlar.
                        if current_playing_uri == last_played_song_uri_from_queue or not last_played_song_uri_from_queue: # Ya da ilk çalma
                            next_song_obj = song_queue.pop(0)
                            song_uri_to_play = next_song_obj.get('id')
                            is_allowed, _ = check_song_filters(song_uri_to_play, current_spotify_client)
                            if is_allowed:
                                logger.info(f"Arka plan: '{current_item.get('name')}' bitti, kuyruktan '{next_song_obj.get('name')}' çalınıyor...")
                                active_device_id = settings.get('active_device_id')
                                current_spotify_client.start_playback(device_id=active_device_id, uris=[song_uri_to_play])
                                update_time_profile(song_uri_to_play, current_spotify_client)
                                save_played_track({'id': song_uri_to_play, 'name': next_song_obj.get('name'), 'artist': next_song_obj.get('artist')})
                                last_played_song_uri_from_queue = song_uri_to_play
                            else:
                                logger.info(f"Arka plan: Kuyruktaki '{next_song_obj.get('name')}' filtrelere takıldı, atlanıyor.")
                                # Bir sonraki şarkıya geç (Spotify'ın kendi sıradakine)
                                current_spotify_client.next_track(device_id=settings.get('active_device_id'))
                                last_played_song_uri_from_queue = None # Kuyruk dışı bir şey çalacak
                        else: # Kullanıcı kuyruktan çalınan şarkıyı değiştirdi, şarkı bitince Spotify'ın normal akışına bırak
                             logger.info("Arka plan: Kullanıcı şarkıyı değiştirdi, şarkı bitince Spotify'ın sıradakine geçilecek.")
                             current_spotify_client.next_track(device_id=settings.get('active_device_id'))
                             last_played_song_uri_from_queue = None

                    elif settings.get('lastfm_username') and get_lastfm_session_key_for_user(settings.get('lastfm_username')): # Kuyruk boşsa LastFM önerisi
                        logger.info(f"Arka plan: '{current_item.get('name')}' bitti, kuyruk boş, Last.fm'den öneri deneniyor...")
                        recommend_and_play_from_lastfm()
                        last_played_song_uri_from_queue = None # Önerilen şarkı kuyruk dışı
                    else: # Kuyruk boş ve LastFM yoksa, Spotify'ın kendi sıradakine geç
                        logger.info(f"Arka plan: '{current_item.get('name')}' bitti, kuyruk boş, Spotify sıradakine geçiyor.")
                        current_spotify_client.next_track(device_id=settings.get('active_device_id'))
                        last_played_song_uri_from_queue = None
                    
                    time.sleep(5) # Geçiş sonrası kısa bir bekleme
        except spotipy.SpotifyException as e:
            if e.http_status == 401 or e.http_status == 403: # Yetkilendirme hatası
                logger.error(f"Arka plan: Spotify yetkilendirme hatası: {e.msg}. Token dosyası siliniyor.")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                global spotify_client; spotify_client = None
                time.sleep(25) # Yeniden denemeden önce daha uzun bekle
            elif e.http_status == 404 and e.reason == "Device not found": # Cihaz bulunamadı
                 logger.warning(f"Arka plan: Spotify cihazı bulunamadı. Ayarlanan cihaz ID: {settings.get('active_device_id')}")
                 time.sleep(25)
            elif e.http_status == 429: # Rate limit
                 logger.warning(f"Arka plan: Spotify API rate limit aşıldı. Bir süre bekleniyor.")
                 time.sleep(60) # Rate limit için daha uzun bekle
            else:
                logger.error(f"Arka plan görevinde Spotify hatası: {e}", exc_info=True)
                time.sleep(25)
        except requests.RequestException as e: # Last.fm veya diğer ağ hataları
            logger.error(f"Arka plan görevinde ağ hatası: {e}", exc_info=True)
            time.sleep(25)
        except Exception as e:
            logger.error(f"Arka plan görevinde beklenmedik hata: {e}", exc_info=True)
            time.sleep(25)


# --- Veritabanı ve Admin Şifre Fonksiyonları (Mevcut) ---
DB_PATH = 'musicco.db'
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS played_tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, track_id TEXT, track_name TEXT, artist_name TEXT, played_at TEXT)")
        # Admin şifresi için tablo (opsiyonel, .env daha basit olabilir)
        # cursor.execute("CREATE TABLE IF NOT EXISTS admin_users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT)")
        conn.commit(); logger.info("Veritabanı başarıyla başlatıldı/kontrol edildi.")
    except sqlite3.Error as e: logger.error(f"Veritabanı hatası: {e}")
    finally: conn.close() if 'conn' in locals() and conn else None

_last_saved_track_id = None
_last_saved_time = None
TRACK_SAVE_COOLDOWN = timedelta(minutes=1) # Aynı şarkıyı 1 dakika içinde tekrar kaydetme

def save_played_track(track_info):
    global _last_saved_track_id, _last_saved_time
    current_time = datetime.now()
    track_id_to_save = track_info.get('id') or track_info.get('track_id')
    
    if not track_id_to_save: logger.warning("Kaydedilecek şarkı ID'si yok."); return

    # Aynı şarkı kısa süre önce kaydedildiyse tekrar kaydetme
    if _last_saved_track_id == track_id_to_save and _last_saved_time and (current_time - _last_saved_time) < TRACK_SAVE_COOLDOWN:
        logger.debug(f"Şarkı '{track_info.get('name')}' kısa süre önce kaydedildi, tekrar kaydedilmiyor.")
        return

    try:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        cursor.execute("INSERT INTO played_tracks (track_id, track_name, artist_name, played_at) VALUES (?, ?, ?, ?)",
                       (track_id_to_save, track_info.get('name', 'Bilinmeyen'), track_info.get('artist', 'Bilinmeyen'), current_time.isoformat()))
        conn.commit()
        _last_saved_track_id = track_id_to_save
        _last_saved_time = current_time
        logger.info(f"Şarkı veritabanına kaydedildi: {track_info.get('name')}")
    except sqlite3.Error as e: logger.error(f"Şarkı kaydetme SQLite hatası: {e}")
    finally: conn.close() if 'conn' in locals() and conn else None


@app.route('/api/played-tracks')
@admin_login_required
def get_played_tracks_api(): # Rota adı değiştirildi (get_played_tracks -> get_played_tracks_api)
    try:
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        # genre sütunu yoktu, kaldırıldı.
        cursor.execute("SELECT track_name, artist_name, played_at, track_id FROM played_tracks ORDER BY played_at DESC LIMIT 100")
        tracks_data = [{'name': row[0], 'artist': row[1], 'played_at': row[2], 'id': row[3]} for row in cursor.fetchall()]
        return jsonify({'success': True, 'tracks': tracks_data})
    except sqlite3.Error as e: return jsonify({'success': False, 'error': str(e)})
    finally: conn.close() if 'conn' in locals() and conn else None

def get_admin_password():
    return os.getenv('ADMIN_PASSWORD') # .env'den alır

def verify_password(password, hashed_password_from_env):
    if not password or not hashed_password_from_env: return False
    try: # .env'deki hash bcrypt formatında mı kontrol et
        if not hashed_password_from_env.startswith('$2b$'): # Basit bir kontrol
             logger.warning("ADMIN_PASSWORD .env'de bcrypt formatında görünmüyor. Düz metin mi?")
             return password == hashed_password_from_env # Düz metin karşılaştırması (güvensiz)
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password_from_env.encode('utf-8'))
    except Exception as e: logger.error(f"Şifre doğrulama hatası: {e}"); return False

def update_admin_password(new_password):
    try:
        hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        env_path = '.env'
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as file: lines = file.readlines()
        with open(env_path, 'w', encoding='utf-8') as file:
            for line in lines:
                if line.startswith('ADMIN_PASSWORD='): file.write(f'ADMIN_PASSWORD={hashed_password}\n'); found = True
                else: file.write(line)
            if not found: file.write(f'ADMIN_PASSWORD={hashed_password}\n')
        logger.info("Admin şifresi .env dosyasında güncellendi/eklendi.")
        # Ortam değişkenini de güncelle (uygulama yeniden başlatılana kadar geçerli olur)
        os.environ['ADMIN_PASSWORD'] = hashed_password
        return True
    except Exception as e: logger.error(f"Admin şifresi güncellenirken hata: {e}"); return False

@app.route('/change-admin-password', methods=['POST'])
@admin_login_required
def change_admin_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    if not all([current_password, new_password, confirm_password]): flash("Tüm alanları doldurunuz.", "danger"); return redirect(url_for('admin_panel'))
    if new_password != confirm_password: flash("Yeni şifreler eşleşmiyor.", "danger"); return redirect(url_for('admin_panel'))
    if len(new_password) < 8: flash("Yeni şifre en az 8 karakter olmalıdır.", "danger"); return redirect(url_for('admin_panel'))
    
    current_hashed_password = get_admin_password()
    if not current_hashed_password: flash("Mevcut admin şifresi .env dosyasında bulunamadı.", "danger"); return redirect(url_for('admin_panel'))
    if not verify_password(current_password, current_hashed_password): flash("Mevcut şifre yanlış.", "danger"); return redirect(url_for('admin_panel'))
    
    if update_admin_password(new_password): flash("Şifre başarıyla değiştirildi.", "success")
    else: flash("Şifre değiştirilirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))

# --- Uygulama Başlangıcı ---
def check_spotify_token_on_startup(): # Adı değiştirildi
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client() # Bu fonksiyon token'ı yükler ve gerekirse yeniler
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı/yenilendi.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Admin panelinden yetkilendirme gerekebilir.")

def check_lastfm_config_on_startup():
    logger.info("Başlangıçta Last.fm yapılandırması kontrol ediliyor...")
    if not LASTFM_API_KEY: logger.warning("LASTFM_API_KEY .env dosyasında ayarlanmamış.")
    if not LASTFM_SHARED_SECRET: logger.warning("LASTFM_SHARED_SECRET .env dosyasında ayarlanmamış. Session key alma işlemi çalışmayabilir.")
    if not LASTFM_REDIRECT_URI: logger.warning("LASTFM_REDIRECT_URI .env dosyasında ayarlanmamış. Last.fm auth callback çalışmayabilir.")
    
    # Otomatik olarak session key'i kontrol etmeye gerek yok, admin panelinden yapılır.

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("Mekan Müzik Sistemi başlatılıyor...")
    logger.info("=================================================")
    if not os.getenv('FLASK_SECRET_KEY'):
        logger.warning("FLASK_SECRET_KEY .env dosyasında ayarlanmamış. Güvenlik için ayarlamanız önerilir.")
    
    init_db() # Veritabanını başlat/kontrol et
    check_spotify_token_on_startup() # Spotify token'ını kontrol et/yenile
    check_lastfm_config_on_startup() # Last.fm yapılandırmasını kontrol et

    # Arka plan şarkı çalma görevini başlat
    # Bu thread'i daemon=True olarak ayarlamak, ana uygulama kapandığında thread'in de kapanmasını sağlar.
    player_thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    player_thread.start()

    port = int(os.environ.get('PORT', 9187))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    logger.info(f"Uygulama http://0.0.0.0:{port} adresinde {'DEBUG' if debug_mode else 'PRODUCTION'} modunda çalışıyor.")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
