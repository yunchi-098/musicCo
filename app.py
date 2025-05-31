# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse ve URI kontrolü için
import subprocess # ex.py ve spotifyd için
from functools import wraps
import requests
import hashlib
from urllib.parse import urlencode

# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi
from datetime import datetime, timedelta, timezone
import sqlite3
import bcrypt # Şifre hashleme için eklendi
from dotenv import load_dotenv # .env dosyası için eklendi

# .env dosyasını yükle
load_dotenv()

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

<<<<<<< HEAD
=======
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


>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
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
    global settings, spotify_client
    
    # Spotify bağlantısını al/kontrol et
    current_spotify_client = get_spotify_client()
    if not current_spotify_client:
        logger.warning("recommend_and_play_from_lastfm: Spotify client not available.")
        return False, "Spotify bağlantısı yok."

    # Last.fm yapılandırmasını kontrol et
    lastfm_username = settings.get('lastfm_username')
    if not LASTFM_API_KEY:
        logger.error("Last.fm API Key (LASTFM_API_KEY) .env dosyasında bulunamadı.")
        return False, "Last.fm API anahtarı ayarlanmamış."
    if not lastfm_username:
        logger.warning("Last.fm kullanıcı adı ayarlarda tanımlanmamış.")
        return False, "Last.fm kullanıcı adı eksik."
    
    if not LASTFM_SHARED_SECRET or not LASTFM_REDIRECT_URI:
        logger.error("Last.fm Shared Secret veya Redirect URI .env dosyasında ayarlanmamış.")
        return False, "Last.fm yapılandırması eksik."

    lastfm_sk = get_lastfm_session_key_for_user(lastfm_username)
    if not lastfm_sk:
        logger.info(f"Last.fm session key for user '{lastfm_username}' not found.")
        return False, "Last.fm bağlantısı gerekli."

    logger.info(f"Attempting to get recommendation from Last.fm for user: {lastfm_username}")
    recent_fm_tracks = get_lastfm_recent_tracks(lastfm_username, LASTFM_API_KEY, limit=5)

    if not recent_fm_tracks:
        logger.warning("Last.fm'den son çalınan şarkılar alınamadı.")
        return False, "Last.fm'den şarkı alınamadı."

    seed_track_uris = []
    for fm_track in recent_fm_tracks:
        uri = find_spotify_uri_from_lastfm_track(fm_track['name'], fm_track['artist'], current_spotify_client)
        if uri: seed_track_uris.append(uri)
        if len(seed_track_uris) >= 5: break
    
    if not seed_track_uris:
        logger.warning("Son Last.fm şarkıları için Spotify URI'leri bulunamadı.")
        return False, "Spotify URI bulunamadı."

    logger.info(f"Using {len(seed_track_uris)} seed URIs for Spotify recommendation: {seed_track_uris}")
    try:
        recs = current_spotify_client.recommendations(seed_tracks=seed_track_uris[:min(len(seed_track_uris),5)], limit=10, market='TR')
        if recs and recs['tracks']:
            for suggested_track in recs['tracks']:
                suggested_uri = suggested_track.get('uri')
                if not suggested_uri: continue
                is_allowed, reason = check_song_filters(suggested_uri, current_spotify_client)
                if not is_allowed: 
                    logger.info(f"Last.fm rec filtered ({reason}): {suggested_track.get('name')}")
                    continue
                
                active_device_id = settings.get('active_device_id')
                if not active_device_id:
                    try:
                        devices_info = current_spotify_client.devices()
                        active_devices = [d for d in devices_info['devices'] if d.get('is_active')] if devices_info and devices_info['devices'] else []
                        if active_devices: active_device_id = active_devices[0]['id']
                        elif devices_info and devices_info['devices']:
                            active_device_id = devices_info['devices'][0]['id']
                            current_spotify_client.transfer_playback(device_id=active_device_id, force_play=False)
                            time.sleep(1)
                        else:
                            logger.error("Aktif Spotify cihazı bulunamadı.")
                            return False, "Spotify cihazı yok."
                    except Exception as dev_ex:
                        logger.error(f"Spotify cihaz hatası: {dev_ex}")
                        return False, "Spotify cihaz hatası."

                track_name_rec = suggested_track.get('name', 'Bilinmeyen Şarkı')
                logger.info(f"Playing Last.fm recommended: '{track_name_rec}' ({suggested_uri}) on {active_device_id}")
                current_spotify_client.start_playback(device_id=active_device_id, uris=[suggested_uri])
                update_time_profile(suggested_uri, current_spotify_client)
                return True, f"'{track_name_rec}' çalınıyor."
            
            logger.info("Filtrelerden geçen uygun Last.fm önerisi bulunamadı.")
            return False, "Uygun öneri yok."
        else:
            logger.warning("Spotify'dan Last.fm geçmişine göre öneri alınamadı.")
            return False, "Spotify önerisi yok."
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify recommendation/playback error (Last.fm): {e}")
        if e.http_status in [401, 403]:
            global spotify_client
            spotify_client = None
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
        return False, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"Unexpected error in recommend_and_play_from_lastfm: {e}", exc_info=True)
        return False, "Beklenmedik hata."

# --- Flask Rotaları ---

@app.route('/')
def index():
    return render_template('index.html')

# --- Spotify Yetkilendirme ---
@app.route('/spotify/auth')
def spotify_auth_prompt():
    return render_template('spotify_auth.html')

@app.route('/spotify/callback')
def spotify_callback():
    return handle_spotify_callback()

# --- Spotify Kontrol ---
@app.route('/spotify/control')
@spotify_auth_required
def spotify_control():
    return render_template('spotify_control.html')

# --- Spotify API ---
@app.route('/api/spotify/play', methods=['POST'])
@spotify_auth_required
def api_spotify_play():
    return handle_spotify_play()

@app.route('/api/spotify/pause', methods=['POST'])
@spotify_auth_required
def api_spotify_pause():
    return handle_spotify_pause()

@app.route('/api/spotify/next', methods=['POST'])
@spotify_auth_required
def api_spotify_next():
    return handle_spotify_next()

@app.route('/api/spotify/previous', methods=['POST'])
@spotify_auth_required
def api_spotify_previous():
    return handle_spotify_previous()

@app.route('/api/spotify/volume', methods=['POST'])
@spotify_auth_required
def api_spotify_volume():
    return handle_spotify_volume()

@app.route('/api/spotify/seek', methods=['POST'])
@spotify_auth_required
def api_spotify_seek():
    return handle_spotify_seek()

@app.route('/api/spotify/status', methods=['GET'])
@spotify_auth_required
def api_spotify_status():
    return handle_spotify_status()

@app.route('/api/spotify/recent', methods=['GET'])
@spotify_auth_required
def api_spotify_recent():
    return handle_spotify_recent()

@app.route('/api/spotify/recommend', methods=['POST'])
@spotify_auth_required
def api_spotify_recommend():
    return handle_spotify_recommend()

# --- Bluetooth Kontrol ---
@app.route('/bluetooth/control')
def bluetooth_control():
    return render_template('bluetooth_control.html')

@app.route('/api/bluetooth/scan', methods=['POST'])
def api_bluetooth_scan():
    return handle_bluetooth_scan()

@app.route('/api/bluetooth/connect', methods=['POST'])
def api_bluetooth_connect():
    return handle_bluetooth_connect()

@app.route('/api/bluetooth/disconnect', methods=['POST'])
def api_bluetooth_disconnect():
    return handle_bluetooth_disconnect()

@app.route('/api/bluetooth/status', methods=['GET'])
def api_bluetooth_status():
    return handle_bluetooth_status()

# --- Ayarlar ---
@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    return handle_settings()

# --- Hata Yönetimi ---
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

<<<<<<< HEAD
@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500
=======
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

@app.route('/api/suggestion')
@spotify_auth_required # Spotify bağlantısı ve yetkilendirmesi bu API için gerekli
# @admin_login_required # Bu API admin olmayan kullanıcılar tarafından da kullanılabilir mi? Şimdilik evet.
                         # Eğer sadece admin içinse, bu satırı aktif et.
def api_get_suggestion():
    """Yerel çalma geçmişine dayalı bir şarkı önerisi döndürür (API)."""
    suggestion_dict, message = get_spotify_recommendation_from_local_history()
    if suggestion_dict:
        return jsonify({'success': True, 'suggestion': suggestion_dict, 'message': message})
    else:
        # Hata durumunda uygun HTTP durum kodu da döndürülebilir,
        # örn: if "bağlantısı yok" in message or "yapılandırması eksik" in message: status_code = 503 (Service Unavailable)
        # şimdilik sadece success: False dönüyoruz.
        return jsonify({'success': False, 'suggestion': None, 'message': message})

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
                else: # Kuyruk boş, otomatik öneri dene
                    logger.info("Arka plan: Kuyruk boş, yerel geçmişten öneri deneniyor...")
                    played_from_local, local_msg = recommend_and_play_from_local_history()
                    if played_from_local:
                        logger.info(f"Arka plan (yerel öneri): {local_msg}")
                        last_played_song_uri_from_queue = None
                    else:
                        logger.info(f"Arka plan: Yerel öneri başarısız/bulunamadı ({local_msg}). Last.fm'den öneri deneniyor...")
                        if settings.get('lastfm_username') and get_lastfm_session_key_for_user(settings.get('lastfm_username')):
                            played_from_lastfm, lastfm_msg = recommend_and_play_from_lastfm()
                            # recommend_and_play_from_lastfm already logs and flashes, so just check success
                            if played_from_lastfm:
                                logger.info(f"Arka plan (Last.fm öneri): {lastfm_msg}")
                                last_played_song_uri_from_queue = None
                            else:
                                logger.info(f"Arka plan: Last.fm önerisi de başarısız/bulunamadı ({lastfm_msg}).")
                        else:
                            logger.info("Arka plan: Last.fm yapılandırılmamış veya bağlı değil.")
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
                    else: # Kuyruk boş, otomatik öneri dene
                        logger.info(f"Arka plan: '{current_item.get('name')}' bitti, kuyruk boş. Yerel geçmişten öneri deneniyor...")
                        played_from_local, local_msg = recommend_and_play_from_local_history()
                        if played_from_local:
                            logger.info(f"Arka plan (yerel öneri): {local_msg}")
                            last_played_song_uri_from_queue = None
                        else:
                            logger.info(f"Arka plan: '{current_item.get('name')}' bitti. Yerel öneri başarısız/bulunamadı ({local_msg}). Last.fm'den öneri deneniyor...")
                            if settings.get('lastfm_username') and get_lastfm_session_key_for_user(settings.get('lastfm_username')):
                                played_from_lastfm, lastfm_msg = recommend_and_play_from_lastfm()
                                if played_from_lastfm:
                                    logger.info(f"Arka plan (Last.fm öneri): {lastfm_msg}")
                                    last_played_song_uri_from_queue = None
                                else:
                                    logger.info(f"Arka plan: Last.fm önerisi de başarısız/bulunamadı ({lastfm_msg}). Spotify sıradakine geçiyor.")
                                    current_spotify_client.next_track(device_id=settings.get('active_device_id'))
                                    last_played_song_uri_from_queue = None
                            else:
                                logger.info(f"Arka plan: Last.fm yapılandırılmamış veya bağlı değil. Spotify sıradakine geçiyor.")
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

def get_recent_spotify_tracks_from_db(limit: int = 5) -> list[str]:
    """
    Veritabanından en son çalınan benzersiz Spotify track_id'lerini alır.
    """
    conn = None
    track_ids = []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = "SELECT DISTINCT track_id FROM played_tracks ORDER BY played_at DESC LIMIT ?"
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        track_ids = [row[0] for row in rows if row[0] and row[0].startswith('spotify:track:')]
        logger.info(f"Veritabanından {len(track_ids)} adet son çalınan Spotify track_id alındı (limit: {limit}).")
    except sqlite3.Error as e:
        logger.error(f"Veritabanından son çalınan şarkıları alırken SQLite hatası: {e}")
        return [] # Hata durumunda boş liste dön
    except Exception as e:
        logger.error(f"Veritabanından son çalınan şarkıları alırken beklenmedik hata: {e}", exc_info=True)
        return [] # Hata durumunda boş liste dön
    finally:
        if conn:
            conn.close()
    return track_ids

def get_spotify_recommendation_from_local_history():
    """
    Yerel veritabanındaki çalma geçmişine göre Spotify'dan şarkı önerisi alır.
    Çalma işlemi yapmaz.
    """
    global spotify_client # For resetting on auth error

    current_spotify_client = get_spotify_client()
    if not current_spotify_client:
        logger.warning("get_spotify_recommendation_from_local_history: Spotify client not available.")
        return None, "Spotify bağlantısı yok."

    seed_track_uris = get_recent_spotify_tracks_from_db(limit=5)
    if not seed_track_uris:
        logger.info("get_spotify_recommendation_from_local_history: Veritabanında öneri için yeterli çalma geçmişi bulunamadı.")
        return None, "Veritabanında yeterli çalma geçmişi bulunamadı."

    logger.info(f"get_spotify_recommendation_from_local_history: Using {len(seed_track_uris)} seed URIs from local DB for Spotify recommendation: {seed_track_uris}")

    try:
        # Spotify API'si en fazla 5 seed kabul eder (track, artist, genre toplamı).
        # get_recent_spotify_tracks_from_db zaten 5 ile limitliyor.
        recs = current_spotify_client.recommendations(seed_tracks=seed_track_uris, limit=10, market='TR')

        if recs and recs.get('tracks'):
            for suggested_track in recs['tracks']:
                suggested_uri = suggested_track.get('uri')
                if not suggested_uri:
                    continue

                is_allowed, reason = check_song_filters(suggested_uri, current_spotify_client)
                if not is_allowed:
                    logger.info(f"get_spotify_recommendation_from_local_history: Öneri filtrelendi ({reason}): {suggested_track.get('name')}")
                    continue

                track_name_rec = suggested_track.get('name', 'Bilinmeyen Şarkı')
                artists = suggested_track.get('artists', [])
                artist_name_rec = ', '.join([a.get('name') for a in artists]) if artists else 'Bilinmeyen Sanatçı'
                images = suggested_track.get('album', {}).get('images', [])
                # Use last image for consistency (often smaller, good for lists)
                image_url_rec = images[-1].get('url') if images else None

                recommendation_details = {
                    'id': suggested_uri,
                    'name': track_name_rec,
                    'artist': artist_name_rec,
                    'image_url': image_url_rec
                }
                logger.info(f"get_spotify_recommendation_from_local_history: Uygun öneri bulundu: '{track_name_rec}'")
                return recommendation_details, "Dinleme geçmişinize göre bir şarkı önerisi bulundu."

            logger.info("get_spotify_recommendation_from_local_history: Filtrelerden geçen uygun bir öneri bulunamadı (yerel geçmişten).")
            return None, "Filtrelerden geçen uygun bir öneri bulunamadı."
        else:
            logger.warning("get_spotify_recommendation_from_local_history: Spotify'dan çalma geçmişine göre öneri alınamadı.")
            return None, "Spotify'dan öneri alınamadı."

    except spotipy.SpotifyException as e:
        logger.error(f"get_spotify_recommendation_from_local_history: Spotify API Hatası: {e.http_status} - {e.msg}", exc_info=True)
        if e.http_status in [401, 403]:
            spotify_client = None # Reset global client
            if os.path.exists(TOKEN_FILE):
                try:
                    os.remove(TOKEN_FILE)
                    logger.info(f"Token dosyası ({TOKEN_FILE}) silindi (SpotifyException nedeniyle).")
                except OSError as rm_err:
                    logger.error(f"Token dosyası ({TOKEN_FILE}) silinemedi: {rm_err}")
        return None, f"Spotify API Hatası: {e.msg}"
    except Exception as e:
        logger.error(f"get_spotify_recommendation_from_local_history: Beklenmedik hata: {e}", exc_info=True)
        return None, "Öneri alınırken beklenmedik bir hata oluştu."

def recommend_and_play_from_local_history():
    """
    Yerel DB geçmişinden şarkı önerisi alır ve çalmaya çalışır.
    Flash mesajları yerine loglama ve (başarı_durumu, mesaj) tuple'ı döndürür.
    """
    global spotify_client, settings # For settings and client reset

    suggestion_dict, message = get_spotify_recommendation_from_local_history()

    if not suggestion_dict:
        logger.info(f"recommend_and_play_from_local_history: Öneri alınamadı. Sebep: {message}")
        return False, message # Propagate the message from the suggestion function

    current_spotify_client = get_spotify_client()
    if not current_spotify_client:
        # This case should ideally be caught by get_spotify_recommendation_from_local_history,
        # but as a safeguard:
        logger.warning("recommend_and_play_from_local_history: Spotify client not available for playback.")
        return False, "Spotify bağlantısı yok."

    suggested_uri = suggestion_dict.get('id')
    track_name_to_play = suggestion_dict.get('name', 'Bilinmeyen Şarkı')
    artist_name_to_play = suggestion_dict.get('artist', 'Bilinmeyen Sanatçı')

    try:
        active_device_id = settings.get('active_device_id')
        if not active_device_id:
            logger.info("recommend_and_play_from_local_history: Aktif Spotify cihazı ayarlarda kayıtlı değil, tespit ediliyor...")
            try:
                devices_info = current_spotify_client.devices()
                active_devices = [d for d in devices_info['devices'] if d.get('is_active')] if devices_info and devices_info.get('devices') else []

                if active_devices:
                    active_device_id = active_devices[0]['id']
                    logger.info(f"recommend_and_play_from_local_history: Aktif cihaz bulundu: {active_device_id}")
                elif devices_info and devices_info.get('devices'):
                    active_device_id = devices_info['devices'][0]['id'] # İlk cihazı seç
                    logger.info(f"recommend_and_play_from_local_history: Aktif cihaz bulunamadı, ilk cihaz ({active_device_id}) kullanılıyor ve playback aktarılıyor.")
                    current_spotify_client.transfer_playback(device_id=active_device_id, force_play=False)
                    time.sleep(1) # Transferin tamamlanması için kısa bir bekleme
                else:
                    logger.error("recommend_and_play_from_local_history: Hiç Spotify Connect cihazı bulunamadı.")
                    return False, "Aktif Spotify cihazı bulunamadı."
            except Exception as dev_ex:
                logger.error(f"recommend_and_play_from_local_history: Spotify cihazları alınırken/aktarılırken hata: {dev_ex}", exc_info=True)
                return False, f"Spotify cihaz hatası: {str(dev_ex)}"

        logger.info(f"recommend_and_play_from_local_history: Playing local history recommended: '{track_name_to_play}' ({suggested_uri}) on device {active_device_id}")
        current_spotify_client.start_playback(device_id=active_device_id, uris=[suggested_uri])

        update_time_profile(suggested_uri, current_spotify_client)
        save_played_track({'id': suggested_uri, 'name': track_name_to_play, 'artist': artist_name_to_play})

        return True, f"Yerel geçmişten önerilen '{track_name_to_play}' çalınıyor."

    except spotipy.SpotifyException as e:
        logger.error(f"recommend_and_play_from_local_history: Spotify API Hatası (Öneri Çalma): {e.http_status} - {e.msg}", exc_info=True)
        if e.http_status in [401, 403]:
            spotify_client = None # Reset global client
            if os.path.exists(TOKEN_FILE):
                try:
                    os.remove(TOKEN_FILE)
                    logger.info(f"Token dosyası ({TOKEN_FILE}) silindi (SpotifyException çalma sırasında).")
                except OSError as rm_err:
                    logger.error(f"Token dosyası ({TOKEN_FILE}) silinemedi: {rm_err}")
        return False, f"Spotify API Hatası (Öneri Çalma): {e.msg}"
    except Exception as e:
        logger.error(f"recommend_and_play_from_local_history: Şarkı çalınırken beklenmedik bir hata oluştu: {e}", exc_info=True)
        return False, "Şarkı çalınırken beklenmedik bir hata oluştu."

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
>>>>>>> 3b94088bfe038549908848c0a93d49069274f022

# --- Uygulama Başlatma ---
if __name__ == '__main__':
    app.run(debug=True)
