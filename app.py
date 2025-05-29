# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse ve URI kontrolü için (artık helpers'ta _ensure_spotify_uri içinde)
# subprocess # ex.py ve spotifyd için (artık helpers'ta _run_command içinde)
from functools import wraps
<<<<<<< HEAD
import requests # Last.fm API çağrıları için eklendi
import hashlib # Last.fm API imzası için eklendi
from urllib.parse import urlencode # Last.fm API imzası için

# flash mesajları için import
=======

>>>>>>> main
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
# from spotipy.oauth2 import SpotifyOAuth # Artık spotify_client_handler içinde
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

<<<<<<< HEAD
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
=======
# --- Yeni Modül Importları ---
import config # Yapılandırma sabitleri
from helpers import _ensure_spotify_uri, _run_command # Yardımcı fonksiyonlar
from app_settings import load_app_settings, save_app_settings # Uygulama ayarları yönetimi
from spotify_client_handler import ( # Spotify istemcisi ve yetkilendirme yönetimi
    get_spotify_client,
    create_spotify_oauth_manager,
    save_spotify_token,
    # load_spotify_token, # Genellikle get_spotify_client içinde kullanılır, direkt çağrı nadir
    clear_spotify_client
)

# --- Logging Ayarları ---
>>>>>>> main
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
<<<<<<< HEAD
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


# --- Yeni Last.fm Şarkı Öneri Fonksiyonu (API için) ---
def get_lastfm_song_suggestion():
    global settings # spotify_client global'den değil, get_spotify_client() ile alınacak

    # Spotify bağlantısını al/kontrol et
    current_spotify_client = get_spotify_client()
    if not current_spotify_client:
        logger.warning("get_lastfm_song_suggestion: Spotify client not available.")
        return None, "Spotify bağlantısı yok."

    # Last.fm yapılandırmasını kontrol et
    lastfm_username = settings.get('lastfm_username')
    if not LASTFM_API_KEY:
        logger.error("get_lastfm_song_suggestion: Last.fm API Key (LASTFM_API_KEY) .env dosyasında bulunamadı.")
        return None, "Last.fm API anahtarı yapılandırılmamış."
    if not lastfm_username:
        logger.warning("get_lastfm_song_suggestion: Last.fm kullanıcı adı ayarlarda tanımlanmamış.")
        return None, "Last.fm kullanıcı adı eksik."
    
    if not LASTFM_SHARED_SECRET: # Session key almak için shared secret gerekli
        logger.error("get_lastfm_song_suggestion: Last.fm Shared Secret .env dosyasında ayarlanmamış.")
        return None, "Last.fm yapılandırması eksik (Shared Secret)."

    lastfm_sk = get_lastfm_session_key_for_user(lastfm_username)
    if not lastfm_sk:
        logger.info(f"get_lastfm_song_suggestion: Last.fm session key for user '{lastfm_username}' not found.")
        # API endpoint'i olduğu için flash mesajı yok, sadece log ve return.
        return None, f"'{lastfm_username}' kullanıcısı için Last.fm bağlantısı gerekli."

    logger.info(f"get_lastfm_song_suggestion: Attempting to get recommendation from Last.fm for user: {lastfm_username}")
    recent_fm_tracks = get_lastfm_recent_tracks(lastfm_username, LASTFM_API_KEY, limit=5)

    if not recent_fm_tracks:
        logger.warning(f"get_lastfm_song_suggestion: Last.fm'den {lastfm_username} için son çalınan şarkılar alınamadı.")
        return None, "Last.fm'den son çalınan şarkılar alınamadı."

    seed_track_uris = []
    for fm_track in recent_fm_tracks:
        uri = find_spotify_uri_from_lastfm_track(fm_track['name'], fm_track['artist'], current_spotify_client)
        if uri: seed_track_uris.append(uri)
        if len(seed_track_uris) >= 5: break
    
    if not seed_track_uris:
        logger.warning(f"get_lastfm_song_suggestion: Son Last.fm şarkıları için Spotify URI'leri bulunamadı ({lastfm_username}).")
        return None, "Spotify URI bulunamadı."

    logger.info(f"get_lastfm_song_suggestion: Using {len(seed_track_uris)} seed URIs for Spotify recommendation: {seed_track_uris}")
    try:
        recs = current_spotify_client.recommendations(seed_tracks=seed_track_uris[:min(len(seed_track_uris),5)], limit=10, market='TR')
        if recs and recs['tracks']:
            for suggested_track in recs['tracks']:
                suggested_uri = suggested_track.get('uri')
                if not suggested_uri: continue
                
                is_allowed, reason = check_song_filters(suggested_uri, current_spotify_client)
                if not is_allowed:
                    logger.info(f"get_lastfm_song_suggestion: Öneri filtrelendi ({reason}): {suggested_track.get('name')}")
                    continue
                
                track_name_rec = suggested_track.get('name', 'Bilinmeyen Şarkı')
                artist_list = suggested_track.get('artists', [])
                artist_name_rec = ', '.join([a.get('name') for a in artist_list]) if artist_list else 'Bilinmeyen Sanatçı'
                images = suggested_track.get('album', {}).get('images', [])
                image_url_rec = images[0].get('url') if images else None # Genellikle en büyük resim ilk sırada olur, veya sondaki daha küçük olabilir. İhtiyaca göre seç.

                recommendation_details = {
                    'id': suggested_uri,
                    'name': track_name_rec,
                    'artist': artist_name_rec,
                    'image_url': image_url_rec
                }
                logger.info(f"get_lastfm_song_suggestion: Uygun öneri bulundu: '{track_name_rec}'")
                return recommendation_details, f"Öneri bulundu: '{track_name_rec}'."
            
            logger.info("get_lastfm_song_suggestion: Filtrelerden geçen uygun Last.fm önerisi bulunamadı.")
            return None, "Uygun öneri yok."
        else:
            logger.warning("get_lastfm_song_suggestion: Spotify'dan Last.fm geçmişine göre öneri alınamadı.")
            return None, "Spotify önerisi yok."
            
    except spotipy.SpotifyException as e:
        logger.error(f"get_lastfm_song_suggestion: Spotify recommendation error (Last.fm): {e}")
        # Token hatası ise global client'ı resetle (get_spotify_client() sonraki çağrıda yenilemeyi dener)
        if e.http_status in [401, 403]: 
            global spotify_client # spotify_client'ı global olarak işaretle
            spotify_client = None 
            if os.path.exists(TOKEN_FILE): # Token dosyasını silmek daha iyi olabilir
                try: os.remove(TOKEN_FILE); logger.info("Token dosyası silindi (SpotifyException nedeniyle).")
                except OSError as rm_err: logger.error(f"Token dosyası silinemedi: {rm_err}")
        return None, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"get_lastfm_song_suggestion: Unexpected error: {e}", exc_info=True)
        return None, "Beklenmedik bir hata oluştu."


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
=======
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin') # config'e taşınabilir
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = config.BLUETOOTH_SCAN_DURATION
app.jinja_env.globals['ALLOWED_GENRES'] = config.ALLOWED_GENRES


# --- Global Değişkenler (Bu adımda app.py'de kalanlar) ---
# spotify_client global'i artık spotify_client_handler.get_spotify_client() ile yönetiliyor.
song_queue = []
user_requests = {} # IP adresi başına istek sayısını tutar
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] }
settings = load_app_settings() # Ayarları başlangıçta yükle (app_settings.py'dan)
auto_advance_enabled = True


# --- Spotifyd Yardımcı Fonksiyonları (Hala app.py'de, _run_command'ı güncelleyerek kullanıyor) ---
def get_spotifyd_pid():
    """Çalışan spotifyd süreçlerinin PID'sini bulur."""
    result = _run_command(["pgrep", "spotifyd"], config.EX_SCRIPT_PATH, timeout=5) # config.EX_SCRIPT_PATH eklendi
>>>>>>> main
    if result.get('success'):
         pids = result.get('output', '').split("\n") if result.get('output') else []
         logger.debug(f"Found spotifyd PIDs: {pids}")
         return pids[0] if pids and pids[0] else None # Sadece ilk PID'yi döndür
    else:
         logger.error(f"Failed to get spotifyd PID: {result.get('error')}")
         return None

def restart_spotifyd():
<<<<<<< HEAD
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
=======
    """Spotifyd servisini ex.py aracılığıyla yeniden başlatır."""
    logger.info("Attempting to restart spotifyd via ex.py...")
    result = _run_command(['restart_spotifyd'], config.EX_SCRIPT_PATH) # config.EX_SCRIPT_PATH eklendi
    return result.get('success', False), result.get('message', result.get('error', 'Bilinmeyen hata'))


# --- Admin Giriş Decorator'ı (Hala app.py'de) ---
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            flash("Bu sayfaya erişmek için yönetici girişi yapmalısınız.", "warning")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Zaman Profili ve Öneri Fonksiyonları (Hala app.py'de) ---
>>>>>>> main
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
<<<<<<< HEAD
        track_info = spotify.track(track_uri, market='TR')
        if not track_info: return
        primary_artist_uri = _ensure_spotify_uri(track_info['artists'][0]['id'], 'artist') if track_info.get('artists') else None
        profile_entry = {'track_uri': track_uri, 'artist_uri': primary_artist_uri}
        if profile_entry not in time_profiles[profile_name]:
            time_profiles[profile_name].append(profile_entry)
            time_profiles[profile_name] = time_profiles[profile_name][-5:] # Son 5'i tut
            logger.info(f"'{profile_name}' profiline eklendi: '{track_info.get('name')}'")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken hata: {e}", exc_info=True)
=======
        track_info = spotify.track(track_uri, market='TR') # Spotify istemcisi argüman olarak geliyor
        if not track_info: logger.warning(f"Şarkı detayı alınamadı: {track_uri}"); return
        track_name = track_info.get('name', '?'); artists = track_info.get('artists')
        primary_artist_uri = _ensure_spotify_uri(artists[0].get('id'), 'artist') if artists and artists[0].get('id') else None
        # primary_artist_name = artists[0].get('name') if artists else '?' # Kullanılmıyor gibi
        profile_entry = {'track_uri': track_uri, 'artist_uri': primary_artist_uri}
        if profile_entry not in time_profiles[profile_name]:
            time_profiles[profile_name].append(profile_entry)
            if len(time_profiles[profile_name]) > 5: time_profiles[profile_name] = time_profiles[profile_name][-5:]
            logger.info(f"'{profile_name}' profiline eklendi: '{track_name}' ({track_uri})")
        else:
            logger.debug(f"'{profile_name}' profilinde zaten var: {track_uri}")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken hata (URI: {track_uri}): {e}", exc_info=True)
>>>>>>> main

def suggest_song_for_time(spotify):
    global time_profiles, song_queue
    if not spotify: return None
    profile_name = get_current_time_profile(); profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None
<<<<<<< HEAD
    seed_tracks, seed_artists = [], []
    for entry in reversed(profile_data):
        if entry.get('track_uri') and entry['track_uri'] not in seed_tracks: seed_tracks.append(entry['track_uri'])
        if entry.get('artist_uri') and entry['artist_uri'] not in seed_artists: seed_artists.append(entry['artist_uri'])
        if len(seed_tracks) + len(seed_artists) >= 5: break
    if not seed_tracks and not seed_artists: return None
=======

    seed_tracks = []; seed_artists = []
    for entry in reversed(profile_data):
        if entry.get('track_uri') and entry['track_uri'] not in seed_tracks:
            seed_tracks.append(entry['track_uri'])
        if entry.get('artist_uri') and entry['artist_uri'] not in seed_artists:
            seed_artists.append(entry['artist_uri'])
        if len(seed_tracks) + len(seed_artists) >= 5: break

    if not seed_tracks and not seed_artists: logger.warning(f"'{profile_name}' profili öneri için tohum içermiyor."); return None

>>>>>>> main
    try:
        recs = spotify.recommendations(seed_tracks=seed_tracks[:min(len(seed_tracks), 5-len(seed_artists))], seed_artists=seed_artists[:min(len(seed_artists), 5-len(seed_tracks))], limit=5, market='TR')
        if recs and recs.get('tracks'):
<<<<<<< HEAD
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
=======
            for suggested_track in recs['tracks']:
                 suggested_uri = suggested_track.get('uri')
                 if not suggested_uri: continue
                 if not any(song.get('id') == suggested_uri for song in song_queue):
                    is_allowed, _ = check_song_filters(suggested_uri, spotify) # spotify client'ı buradan alıyor
                    if is_allowed:
                        logger.info(f"'{profile_name}' için öneri bulundu ve filtreden geçti: '{suggested_track.get('name')}' ({suggested_uri})")
                        artists_data = suggested_track.get('artists', []);
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists_data if a.get('id')]
                        artist_names = [a.get('name') for a in artists_data]
                        images = suggested_track.get('album', {}).get('images', [])
                        image_url = images[-1].get('url') if images else None
                        return {
                            'id': suggested_uri, 'name': suggested_track.get('name'),
                            'artist': ', '.join(artist_names), 'artist_ids': artist_uris,
                            'image_url': image_url
                        }
                    else:
                         logger.info(f"'{profile_name}' için öneri bulundu ancak filtrelere takıldı: '{suggested_track.get('name')}' ({suggested_uri})")
            logger.info(f"'{profile_name}' önerileri kuyrukta mevcut veya filtrelere takıldı.")
        else: logger.info(f"'{profile_name}' için öneri alınamadı."); return None
    except Exception as e: logger.error(f"'{profile_name}' için öneri alınırken hata: {e}", exc_info=True); return None
    return None

# --- Şarkı Filtreleme Yardımcı Fonksiyonu (Hala app.py'de) ---
def check_song_filters(track_uri, spotify_client_instance): # Parametre adı değişti
    """
    Verilen track_uri'nin filtrelere uyup uymadığını kontrol eder.
    """
    global settings # settings global'i load_app_settings ile yükleniyor
    if not spotify_client_instance: return False, "Spotify bağlantısı yok."
    if not track_uri or not isinstance(track_uri, str) or not track_uri.startswith('spotify:track:'):
        logger.error(f"check_song_filters: Geçersiz track_uri formatı: {track_uri}")
        return False, f"Geçersiz şarkı URI formatı: {track_uri}"

    logger.debug(f"Filtre kontrolü başlatılıyor: {track_uri}")
    try:
        song_info = spotify_client_instance.track(track_uri, market='TR')
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
        logger.debug(f"Şarkı ('track') filtresi modu: {track_filter_mode}")
        if track_filter_mode == 'whitelist':
            if not track_whitelist_uris:
                logger.debug("Filtre takıldı: Şarkı beyaz listesi boş.")
                return False, 'Şarkı beyaz listesi aktif ama boş.'
            if track_uri not in track_whitelist_uris:
                logger.debug(f"Filtre takıldı: Şarkı ({track_uri}) beyaz listede değil.")
                return False, 'Bu şarkı beyaz listede değil.'
        elif track_filter_mode == 'blacklist':
             if track_uri in track_blacklist_uris:
                logger.debug(f"Filtre takıldı: Şarkı ({track_uri}) kara listede.")
                return False, 'Bu şarkı kara listede.'
        logger.debug(f"Şarkı ('track') filtresinden geçti: {track_uri}")

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
                logger.debug(f"Filtre takıldı: Sanatçı ({artist_names}) beyaz listede değil.")
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
                    artist_info = spotify_client_instance.artist(primary_artist_uri)
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
                        logger.debug(f"Filtre takıldı: Tür ({artist_genres}) beyaz listede değil.")
                        return False, 'Bu tür beyaz listede değil.'
            logger.debug("Tür filtresinden geçti.")
        else:
             logger.debug("Tür filtresi uygulanmadı (mod blacklist/whitelist değil veya ilgili liste boş).")

        logger.debug(f"Filtre kontrolü tamamlandı: İzin verildi - {track_uri}")
>>>>>>> main
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

# --- Flask Rotaları (İçleri güncellenmeli) ---

@app.route('/')
def index():
<<<<<<< HEAD
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
=======
    return render_template('index.html', allowed_genres=config.ALLOWED_GENRES)

@app.route('/admin')
def admin():
    if session.get('admin_logged_in'): return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    if request.form.get('password') == config.ADMIN_PASSWORD: # config'den
        session['admin_logged_in'] = True; logger.info("Admin girişi başarılı")
        flash("Yönetim paneline hoş geldiniz!", "success"); return redirect(url_for('admin_panel'))
    else:
        logger.warning("Başarısız admin girişi denemesi"); flash("Yanlış şifre girdiniz.", "danger")
        return redirect(url_for('admin'))

@app.route('/logout')
>>>>>>> main
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
    global settings
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
    return render_template('admin.html') # admin.html yerine admin_login.html kullanılıyor

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
<<<<<<< HEAD
    session.pop('admin', None)
    session.pop('spotify_authenticated', None) # Spotify session bilgilerini de temizle
    session.pop('spotify_user', None)
    # Last.fm session'ı (dosyadaki) silmek yerine, sadece Flask session'ından admin'i çıkarıyoruz.
    # Last.fm bağlantısını kesmek için ayrı bir buton/işlem olabilir.
=======
    clear_spotify_client() # spotify_client = None yerine
    session.clear()
>>>>>>> main
    logger.info("Admin çıkışı yapıldı."); flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin_login'))


@app.route('/admin-panel')
@admin_login_required # Bu decorator artık session['next_url'] kullanıyor
def admin_panel():
<<<<<<< HEAD
    global auto_advance_enabled, settings, song_queue
    
    # Spotify bağlantısını al/kontrol et
    current_spotify_client = get_spotify_client() # Bu fonksiyon token'ı yenileyebilir veya None dönebilir
    spotify_authenticated = bool(current_spotify_client)
    session['spotify_authenticated'] = spotify_authenticated # Session'ı güncelle
    
=======
    global auto_advance_enabled, settings, song_queue # settings artık load_app_settings ile yükleniyor
    spotify = get_spotify_client() # spotify_client_handler'dan
>>>>>>> main
    spotify_devices = []
    spotify_user = None
    currently_playing_info = None
    filtered_queue = []
<<<<<<< HEAD
    audio_sinks_result = _run_command(['list_sinks'])
=======

    audio_sinks_result = _run_command(['list_sinks'], config.EX_SCRIPT_PATH) # config.EX_SCRIPT_PATH eklendi
>>>>>>> main
    audio_sinks = audio_sinks_result.get('sinks', []) if audio_sinks_result.get('success') else []
    default_audio_sink_name = audio_sinks_result.get('default_sink_name') if audio_sinks_result.get('success') else None
    if not audio_sinks_result.get('success'):
        flash(f"Ses cihazları listelenemedi: {audio_sinks_result.get('error', 'Bilinmeyen hata')}", "danger")

    if current_spotify_client:
        try:
<<<<<<< HEAD
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
=======
            result = spotify.devices(); spotify_devices = result.get('devices', [])
            try: 
                user = spotify.current_user(); spotify_user = user.get('display_name', '?'); 
                session['spotify_user'] = spotify_user
            except Exception as user_err: 
                logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}"); 
                session.pop('spotify_user', None)
            
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']; is_playing = playback.get('is_playing', False)
                    track_uri = item.get('uri')
                    if track_uri and track_uri.startswith('spotify:track:'):
                         is_allowed, _ = check_song_filters(track_uri, spotify) # spotify client'ı paslıyoruz
                         track_name = item.get('name', '?'); artists_data = item.get('artists', [])
                         artist_name = ', '.join([a.get('name') for a in artists_data]) if artists_data else '?'
                         artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists_data if a.get('id')]
                         images = item.get('album', {}).get('images', []); image_url = images[0].get('url') if images else None
                         currently_playing_info = {
                             'id': track_uri, 'name': track_name, 'artist': artist_name,
                             'artist_ids': artist_uris, 'image_url': image_url, 'is_playing': is_playing,
                             'is_allowed': is_allowed
                         }
                         logger.debug(f"Şu An Çalıyor (Admin): {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'} - Filtre İzin: {is_allowed}")
            except Exception as pb_err: logger.warning(f"Çalma durumu alınamadı: {pb_err}")

            for song_item in song_queue: # song_queue global'den geliyor
                song_uri = song_item.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, spotify)
                    if is_allowed:
                        if 'artist_ids' in song_item and isinstance(song_item['artist_ids'], list):
                             song_item['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song_item['artist_ids']]
                        filtered_queue.append(song_item)
                    else:
                        logger.debug(f"Admin Paneli: Kuyruktaki şarkı filtrelendi: {song_item.get('name')} ({song_uri})")
                else:
                     logger.warning(f"Admin Paneli: Kuyrukta geçersiz şarkı formatı: {song_item}")

        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e.http_status} - {e.msg}")
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            if e.http_status == 401 or e.http_status == 403:
                flash("Spotify yetkilendirmesi geçersiz veya süresi dolmuş. Lütfen tekrar yetkilendirin.", "warning")
                if os.path.exists(config.TOKEN_FILE): # config'den
                    logger.warning("Geçersiz token dosyası siliniyor."); os.remove(config.TOKEN_FILE)
                clear_spotify_client() # Client'ı temizle
            else: flash(f"Spotify API hatası: {e.msg}", "danger")
        except Exception as e:
            logger.error(f"Admin panelinde beklenmedik hata: {e}", exc_info=True)
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            flash("Beklenmedik bir hata oluştu.", "danger")
    else:
        spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
        if not os.path.exists(config.TOKEN_FILE): # config'den
            flash("Spotify hesabınızı bağlamak için lütfen yetkilendirme yapın.", "info")

    return render_template(
        'admin_panel.html',
        settings=settings, # settings global'i
        spotify_devices=spotify_devices,
        queue=filtered_queue,
        all_genres=config.ALLOWED_GENRES, # config'den
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        audio_sinks=audio_sinks, default_audio_sink_name=default_audio_sink_name,
        currently_playing_info=currently_playing_info,
        auto_advance_enabled=auto_advance_enabled # global'den
    )

>>>>>>> main
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
<<<<<<< HEAD
        flash(f'Spotify duraklatma hatası: {e.msg}', 'danger')
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
=======
        logger.error(f"Spotify duraklatma hatası: {e}")
        if e.http_status == 401 or e.http_status == 403: 
            flash('Spotify yetkilendirme hatası.', 'danger');
            clear_spotify_client()
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
        elif e.http_status == 404: flash(f'Duraklatma hatası: Cihaz bulunamadı ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE': flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        else: flash(f'Spotify duraklatma hatası: {e.msg}', 'danger')
    except Exception as e: logger.error(f"Duraklatma sırasında genel hata: {e}", exc_info=True); flash('Müzik duraklatılırken bir hata oluştu.', 'danger')
>>>>>>> main
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
<<<<<<< HEAD
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


=======
        logger.error(f"Spotify sürdürme hatası: {e}")
        if e.http_status == 401 or e.http_status == 403: 
            flash('Spotify yetkilendirme hatası.', 'danger');
            clear_spotify_client()
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
        elif e.http_status == 404: flash(f'Sürdürme hatası: Cihaz bulunamadı ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE': flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        elif e.reason == 'PREMIUM_REQUIRED': flash('Bu işlem için Spotify Premium gerekli.', 'warning')
        else: flash(f'Spotify sürdürme hatası: {e.msg}', 'danger')
    except Exception as e: logger.error(f"Sürdürme sırasında genel hata: {e}", exc_info=True); flash('Müzik sürdürülürken bir hata oluştu.', 'danger')
    return redirect(url_for('admin_panel'))

>>>>>>> main
@app.route('/refresh-devices')
@admin_login_required
@spotify_auth_required # Cihazları almak için Spotify bağlantısı gerekir
def refresh_devices():
<<<<<<< HEAD
    current_spotify_client = get_spotify_client()
    global settings
=======
    global settings # save_app_settings için settings global'ini kullanıyoruz
    spotify = get_spotify_client()
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
>>>>>>> main
    try:
        result = current_spotify_client.devices(); devices = result.get('devices', [])
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device and not any(d['id'] == active_spotify_connect_device for d in devices):
<<<<<<< HEAD
            
            current_settings = load_settings()
            current_settings['active_device_id'] = None; save_settings(current_settings)
            settings = current_settings
            flash('Ayarlardaki aktif Spotify Connect cihazı artık mevcut değil.', 'warning')
        flash('Spotify Connect cihaz listesi yenilendi.', 'info')
    except spotipy.SpotifyException as e: # Hata durumunu yakala
        flash(f"Spotify cihazları yenilenirken hata: {e.msg}", "danger")
        if e.http_status in [401, 403]: global spotify_client; spotify_client = None; os.remove(TOKEN_FILE); return redirect(url_for('spotify_auth_prompt'))
=======
            logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device}) listede yok. Ayar temizleniyor.")
            current_settings = settings.copy() # Ayarları kopyala
            current_settings['active_device_id'] = None
            save_app_settings(current_settings) # app_settings'den
            settings = load_app_settings() # Ayarları yeniden yükle
            flash('Ayarlardaki aktif Spotify Connect cihazı artık mevcut değil.', 'warning')
        flash('Spotify Connect cihaz listesi yenilendi.', 'info')
    except Exception as e:
        logger.error(f"Spotify Connect Cihazlarını yenilerken hata: {e}")
        flash('Spotify Connect cihaz listesi yenilenirken bir hata oluştu.', 'danger')
        if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
            clear_spotify_client()
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
>>>>>>> main
    return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings_route(): # İsim çakışmasını önlemek için
    global settings
    try:
<<<<<<< HEAD
        current_settings = load_settings()
=======
        logger.info("Ayarlar güncelleniyor...")
        current_settings = settings.copy() # Mevcut global settings'i kopyala
>>>>>>> main
        current_settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        current_settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        current_settings['active_device_id'] = request.form.get('active_spotify_connect_device_id') or None
        current_settings['genre_filter_mode'] = request.form.get('genre_filter_mode', 'blacklist')
        current_settings['artist_filter_mode'] = request.form.get('artist_filter_mode', 'blacklist')
<<<<<<< HEAD
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
=======
        current_settings['track_filter_mode'] = request.form.get('song_filter_mode', 'blacklist') # Formdan song gelir ama track olarak saklanır
        
        save_app_settings(current_settings) # app_settings modülünden
        settings = load_app_settings() # Global settings'i güncelle
        logger.info(f"Ayarlar güncellendi: {settings}")
>>>>>>> main
        flash("Ayarlar başarıyla güncellendi.", "success")
    except ValueError: flash("Geçersiz sayısal değer girildi!", "danger")
    except Exception as e: logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True); flash("Ayarlar güncellenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))

<<<<<<< HEAD

=======
@app.route('/spotify-auth')
@admin_login_required
def spotify_auth_route_v2(): # İsim çakışmasını önlemek için
    if os.path.exists(config.TOKEN_FILE): logger.warning("Mevcut token varken yeniden yetkilendirme.")
    try: 
        auth_manager = create_spotify_oauth_manager() # spotify_client_handler'dan
        auth_url = auth_manager.get_authorize_url()
        logger.info("Spotify yetkilendirme URL'sine yönlendiriliyor.")
        return redirect(auth_url)
    except ValueError as e: 
        logger.error(f"Spotify yetkilendirme hatası: {e}")
        flash(f"Spotify Yetkilendirme Hatası: {e}", "danger")
        return redirect(url_for('admin_panel'))
    except Exception as e: 
        logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True)
        flash("Spotify yetkilendirme başlatılamadı.", "danger")
        return redirect(url_for('admin_panel'))

@app.route('/callback')
def callback():
    try: 
        auth_manager = create_spotify_oauth_manager() # spotify_client_handler'dan
    except ValueError as e: 
        logger.error(f"Callback hatası: {e}"); return f"Callback Hatası: {e}", 500
    
    if 'error' in request.args: 
        error = request.args.get('error')
        logger.error(f"Spotify yetkilendirme hatası (callback): {error}")
        return f"Spotify Yetkilendirme Hatası: {error}", 400
    if 'code' not in request.args: 
        logger.error("Callback'te 'code' yok.")
        return "Geçersiz callback isteği.", 400
    
    code = request.args.get('code')
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False) # Cache'i kontrol etme, her zaman yeni al
        if not token_info: 
            logger.error("Spotify'dan token alınamadı.")
            return "Token alınamadı.", 500
        
        if isinstance(token_info, str) or not isinstance(token_info, dict): # Spotipy bazen sadece str dönebilir veya format hatalı olabilir
            logger.error(f"get_access_token beklenmedik formatta veri döndürdü: {type(token_info)}")
            return "Token bilgisi alınırken hata oluştu.", 500

        if save_spotify_token(token_info): # spotify_client_handler'dan
            clear_spotify_client() # Yeni token ile istemciyi yeniden oluşturmaya zorla
            logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
            if session.get('admin_logged_in'): 
                flash("Spotify yetkilendirmesi başarıyla tamamlandı!", "success")
                return redirect(url_for('admin_panel'))
            else: 
                return redirect(url_for('index'))
        else: 
            logger.error("Alınan token dosyaya kaydedilemedi.")
            return "Token kaydedilirken bir hata oluştu.", 500
    except spotipy.SpotifyOauthError as e: 
        logger.error(f"Spotify token alırken OAuth hatası: {e}", exc_info=True)
        return f"Token alınırken yetkilendirme hatası: {e}", 500
    except Exception as e: 
        logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True)
        return "Token işlenirken bir hata oluştu.", 500

>>>>>>> main
@app.route('/search', methods=['POST'])
@spotify_auth_required # Arama için Spotify bağlantısı gerekir
def search():
<<<<<<< HEAD
    current_spotify_client = get_spotify_client()
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track')
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400
=======
    global settings # settings global'i
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track')
    logger.info(f"Arama isteği: '{search_query}' (Tip: {search_type})")
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400

    spotify = get_spotify_client() # spotify_client_handler'dan
    if not spotify: 
        logger.error("Arama: Spotify istemcisi yok.")
        return jsonify({'error': 'Spotify bağlantısı yok.'}), 503

>>>>>>> main
    try:
        items_from_spotify = []
        if search_type == 'artist': results = current_spotify_client.search(q=search_query, type='artist', limit=20, market='TR'); items_from_spotify = results.get('artists', {}).get('items', [])
        elif search_type == 'track': results = current_spotify_client.search(q=search_query, type='track', limit=20, market='TR'); items_from_spotify = results.get('tracks', {}).get('items', [])
        else: return jsonify({'error': 'Geçersiz arama tipi.'}), 400
        
        filtered_items = []
<<<<<<< HEAD
        for item in items_from_spotify:
            if not item or not item.get('uri'): continue
            is_allowed = True; reason = ""
            if search_type == 'track': is_allowed, reason = check_song_filters(item['uri'], current_spotify_client)
            elif search_type == 'artist': # Sanatçı ve tür filtreleri (mevcut kodunuzdaki gibi)
                artist_uri_to_check = item['uri']; artist_name = item.get('name')
                # ... (sanatçı ve tür filtreleme mantığı buraya gelecek, check_song_filters gibi ayrı bir fonksiyona taşınabilir) ...
                # Şimdilik basitleştirilmiş:
=======
        for item_data in items: # item flask'tan geliyor olabilir, karışmasın
            if not item_data: continue
            item_uri = item_data.get('uri')
            if not item_uri: continue

            is_allowed = True; reason = ""
            if search_type == 'track':
                is_allowed, reason = check_song_filters(item_uri, spotify) # spotify client'ı paslıyoruz
            elif search_type == 'artist':
                artist_uri_to_check = item_uri
                artist_name = item_data.get('name')
>>>>>>> main
                artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
                if artist_filter_mode == 'blacklist' and item['uri'] in settings.get('artist_blacklist', []): is_allowed = False
                if artist_filter_mode == 'whitelist' and (not settings.get('artist_whitelist', []) or item['uri'] not in settings.get('artist_whitelist', [])): is_allowed = False

<<<<<<< HEAD
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
=======
                if artist_filter_mode == 'blacklist':
                    if artist_uri_to_check in artist_blacklist_uris: is_allowed = False; reason = f"'{artist_name}' kara listede."
                elif artist_filter_mode == 'whitelist':
                    if not artist_whitelist_uris: is_allowed = False; reason = "Sanatçı beyaz listesi boş."
                    elif artist_uri_to_check not in artist_whitelist_uris: is_allowed = False; reason = f"'{artist_name}' beyaz listede değil."
                
                if is_allowed: # Sanatçıdan geçtiyse türü kontrol et
                    genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
                    genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
                    genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]
                    run_genre_check = (genre_filter_mode == 'blacklist' and genre_blacklist) or \
                                      (genre_filter_mode == 'whitelist' and genre_whitelist)
                    if run_genre_check:
                        artist_genres = [g.lower() for g in item_data.get('genres', [])]
                        if not artist_genres: logger.warning(f"Tür filtresi uygulanamıyor (türler yok): {artist_name}")
                        else:
                            if genre_filter_mode == 'blacklist':
                                if any(genre in genre_blacklist for genre in artist_genres):
                                    blocked_genre = next((genre for genre in artist_genres if genre in genre_blacklist), "?"); is_allowed = False; reason = f"'{blocked_genre}' türü kara listede."
                            elif genre_filter_mode == 'whitelist':
                                if not genre_whitelist: is_allowed = False; reason = "Tür beyaz listesi boş."
                                elif not any(genre in genre_whitelist for genre in artist_genres): is_allowed = False; reason = "Bu tür beyaz listede değil."
            
            if is_allowed: filtered_items.append(item_data)
            else: logger.debug(f"Arama sonucu filtrelendi ({reason}): {item_data.get('name')} ({item_uri})")

        search_results = []
        limit = 10
        for item_res in filtered_items[:limit]: # item_data ile karışmasın
            item_id = item_res.get('id')
            item_uri_res = item_res.get('uri')
            if not item_id or not item_uri_res: continue

            result_data = {'id': item_id, 'uri': item_uri_res, 'name': item_res.get('name')}
            images = item_res.get('images', [])
            if not images and 'album' in item_res: images = item_res.get('album', {}).get('images', [])
            result_data['image'] = images[-1].get('url') if images else None

            if search_type == 'artist':
                 result_data['genres'] = item_res.get('genres', [])
            elif search_type == 'track':
                 artists_s = item_res.get('artists', []);
                 result_data['artist'] = ', '.join([a.get('name') for a in artists_s])
                 result_data['artist_ids'] = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists_s if a.get('id')]
                 result_data['album'] = item_res.get('album', {}).get('name')
            search_results.append(result_data)

        logger.info(f"Filtrelenmiş {search_type} arama sonucu: {len(search_results)} öğe.")
        return jsonify({'results': search_results})

    except Exception as e:
        logger.error(f"Spotify araması hatası ({search_type}): {e}", exc_info=True)
        return jsonify({'error': 'Arama sırasında sorun oluştu.'}), 500
>>>>>>> main

@app.route('/add-song', methods=['POST'])
@admin_login_required
@spotify_auth_required # Şarkı eklemek için Spotify bağlantısı gerekir
def add_song():
<<<<<<< HEAD
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

=======
    global song_queue, settings # settings ve song_queue global
    song_input = request.form.get('song_id', '').strip()
    if not song_input: flash("Şarkı ID/URL girin.", "warning"); return redirect(url_for('admin_panel'))

    track_uri = _ensure_spotify_uri(song_input, 'track') # helpers'dan
    if not track_uri: flash("Geçersiz Spotify Şarkı ID veya URL formatı.", "danger"); return redirect(url_for('admin_panel'))

    if len(song_queue) >= settings.get('max_queue_length', 20): flash("Kuyruk dolu!", "warning"); return redirect(url_for('admin_panel'))

    spotify = get_spotify_client() # spotify_client_handler'dan
    if not spotify: flash("Spotify yetkilendirmesi gerekli.", "warning"); return redirect(url_for('spotify_auth_route_v2')) # Rota adını güncelledik

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: flash(f"Şarkı bulunamadı (URI: {track_uri}).", "danger"); return redirect(url_for('admin_panel'))

        artists = song_info.get('artists');
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        song_queue.append({
            'id': track_uri, 'name': song_info.get('name', '?'),
            'artist': ', '.join([a.get('name') for a in artists]),
            'artist_ids': artist_uris, 'added_by': 'admin', 'added_at': time.time()
        })
        logger.info(f"Şarkı eklendi (Admin - Filtresiz): {track_uri} - {song_info.get('name')}")
        flash(f"'{song_info.get('name')}' eklendi.", "success");
        update_time_profile(track_uri, spotify) # spotify client'ı paslıyoruz
    except spotipy.SpotifyException as e:
        logger.error(f"Admin eklerken Spotify hatası (URI={track_uri}): {e}")
        if e.http_status == 401 or e.http_status == 403: flash("Spotify yetkilendirme hatası.", "danger"); return redirect(url_for('spotify_auth_route_v2'))
        elif e.http_status == 400: flash(f"Geçersiz Spotify URI: {track_uri}", "danger")
        else: flash(f"Spotify hatası: {e.msg}", "danger")
    except Exception as e: logger.error(f"Admin eklerken genel hata (URI={track_uri}): {e}", exc_info=True); flash("Şarkı eklenirken hata.", "danger")
    return redirect(url_for('admin_panel'))


>>>>>>> main
@app.route('/add-to-queue', methods=['POST'])
@spotify_auth_required # Kullanıcı eklemesi için de Spotify bağlantısı gerekir
def add_to_queue():
<<<<<<< HEAD
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
=======
    global settings, song_queue, user_requests # Globaller
    if not request.is_json: return jsonify({'error': 'Geçersiz format.'}), 400
    data = request.get_json();
    track_identifier = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: identifier={track_identifier}")
    if not track_identifier: return jsonify({'error': 'Eksik ID.'}), 400

    track_uri = _ensure_spotify_uri(track_identifier, 'track') # helpers'dan
    if not track_uri:
        logger.error(f"Kullanıcı ekleme: Geçersiz ID formatı: {track_identifier}")
        return jsonify({'error': 'Geçersiz şarkı ID formatı.'}), 400

    if len(song_queue) >= settings.get('max_queue_length', 20): 
        logger.warning("Kuyruk dolu."); return jsonify({'error': 'Kuyruk dolu.'}), 429

    user_ip = request.remote_addr; max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: 
        logger.warning(f"Limit aşıldı: {user_ip}"); return jsonify({'error': f'İstek limitiniz ({max_requests}) doldu.'}), 429

    spotify = get_spotify_client() # spotify_client_handler'dan
    if not spotify: 
        logger.error("Ekleme: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503

    is_allowed, reason = check_song_filters(track_uri, spotify) # spotify client'ı paslıyoruz
    if not is_allowed:
        logger.info(f"Reddedildi ({reason}): {track_uri}")
        return jsonify({'error': reason}), 403

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: return jsonify({'error': 'Şarkı bilgisi alınamadı (tekrar kontrol).'}), 500
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []);
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists]

        logger.info(f"Filtrelerden geçti: {song_name} ({track_uri})")
        update_time_profile(track_uri, spotify) # spotify client'ı paslıyoruz

        song_queue.append({
            'id': track_uri, 'name': song_name,
            'artist': ', '.join(artist_names), 'artist_ids': artist_uris,
            'added_by': user_ip, 'added_at': time.time()
        })
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        logger.info(f"Şarkı eklendi (Kullanıcı: {user_ip}): {song_name}. Kuyruk: {len(song_queue)}")
        return jsonify({'success': True, 'message': f"'{song_name}' kuyruğa eklendi!"})

    except spotipy.SpotifyException as e:
        logger.error(f"Kullanıcı eklerken Spotify hatası (URI={track_uri}): {e}")
        if e.http_status == 401 or e.http_status == 403: return jsonify({'error': 'Spotify yetkilendirme sorunu.'}), 503
        elif e.http_status == 400: return jsonify({'error': f"Geçersiz Spotify URI: {track_uri}"}), 400
        else: return jsonify({'error': f"Spotify hatası: {e.msg}"}), 500
    except Exception as e:
        logger.error(f"Kuyruğa ekleme hatası (URI: {track_uri}): {e}", exc_info=True)
        return jsonify({'error': 'Şarkı eklenirken bilinmeyen bir sorun oluştu.'}), 500
>>>>>>> main

@app.route('/remove-song/<path:song_id_str>', methods=['POST'])
@admin_login_required
# Spotify bağlantısı gerektirmez, sadece kendi kuyruğumuzdan siler.
def remove_song(song_id_str):
    global song_queue;
<<<<<<< HEAD
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track')
    if not song_uri_to_remove: flash(f"Geçersiz şarkı ID formatı: {song_id_str}", "danger"); return redirect(url_for('admin_panel'))
=======
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track') # helpers'dan
    if not song_uri_to_remove:
        flash(f"Geçersiz şarkı ID formatı: {song_id_str}", "danger")
        return redirect(url_for('admin_panel'))

    logger.debug(f"Kuyruktan kaldırılacak URI: {song_uri_to_remove}")
>>>>>>> main
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
<<<<<<< HEAD
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
=======
    global song_queue # song_queue global'den
    currently_playing_info = None
    filtered_queue = []
    spotify = get_spotify_client() # spotify_client_handler'dan

    if spotify:
        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']; is_playing = playback.get('is_playing', False)
                track_uri = item.get('uri')
                if track_uri and track_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(track_uri, spotify) # spotify client'ı paslıyoruz
                    if is_allowed:
                        track_name = item.get('name'); artists = item.get('artists', [])
                        artist_name = ', '.join([a.get('name') for a in artists]); images = item.get('album', {}).get('images', [])
                        image_url = images[-1].get('url') if images else None
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
                        currently_playing_info = {
                            'id': track_uri, 'name': track_name, 'artist': artist_name,
                            'artist_ids': artist_uris, 'image_url': image_url, 'is_playing': is_playing
                        }
                        logger.debug(f"Şu An Çalıyor (Kuyruk): {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'}")
                    else:
                         logger.debug(f"Kuyruk Sayfası: Çalan şarkı filtrelendi: {item.get('name')} ({track_uri})")
        except spotipy.SpotifyException as e:
            logger.warning(f"Çalma durumu hatası (Kuyruk): {e}")
            if e.http_status == 401 or e.http_status == 403: 
                clear_spotify_client()
                if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE) # config'den
        except Exception as e: logger.error(f"Çalma durumu genel hatası (Kuyruk): {e}", exc_info=True)

        for song_item_q in song_queue: # song_queue global'den
            song_uri = song_item_q.get('id')
            if song_uri and song_uri.startswith('spotify:track:'):
                is_allowed, _ = check_song_filters(song_uri, spotify) # spotify client'ı paslıyoruz
                if is_allowed:
                    if 'artist_ids' in song_item_q and isinstance(song_item_q['artist_ids'], list):
                         song_item_q['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song_item_q['artist_ids']]
                    filtered_queue.append(song_item_q)
                else:
                     logger.debug(f"Kuyruk Sayfası: Kuyruktaki şarkı filtrelendi: {song_item_q.get('name')} ({song_uri})")
            else:
                 logger.warning(f"Kuyruk Sayfası: Kuyrukta geçersiz şarkı formatı: {song_item_q}")
    return render_template('queue.html', queue=filtered_queue, currently_playing_info=currently_playing_info)

@app.route('/api/queue')
def api_get_queue():
    global song_queue, settings # Globaller
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue), 'max_length': settings.get('max_queue_length', 20)})

# --- Ses/Bluetooth API Rotaları (ex.py'yi Çağıran) ---
# Bu rotalar _run_command'ı config.EX_SCRIPT_PATH ile kullanacak şekilde güncellendi.
@app.route('/api/audio-sinks')
@admin_login_required
def api_audio_sinks():
    logger.info("API: Ses sink listesi isteniyor (ex.py aracılığıyla)...")
    result = _run_command(['list_sinks'], config.EX_SCRIPT_PATH)
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code
>>>>>>> main

@app.route('/api/set-audio-sink', methods=['POST'])
@admin_login_required
def api_set_audio_sink():
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
<<<<<<< HEAD
    sink_identifier = request.get_json().get('sink_identifier')
    if sink_identifier is None: return jsonify({'success': False, 'error': 'Sink ID gerekli'}), 400
    result = _run_command(['set_audio_sink', '--identifier', str(sink_identifier)])
    # Başarılıysa güncel listeleri de döndür (mevcut kodunuzdaki gibi)
    return jsonify(result), 200 if result.get('success') else 500

# ... Diğer Bluetooth API rotaları (discover, pair, disconnect) benzer şekilde kalabilir ...
=======
    data = request.get_json()
    sink_identifier = data.get('sink_identifier')
    if sink_identifier is None: return jsonify({'success': False, 'error': 'Sink tanımlayıcısı gerekli'}), 400
    logger.info(f"API: Varsayılan ses sink ayarlama: {sink_identifier} (ex.py)...")
    result = _run_command(['set_audio_sink', '--identifier', str(sink_identifier)], config.EX_SCRIPT_PATH)
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'], config.EX_SCRIPT_PATH)
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'], config.EX_SCRIPT_PATH)
         if sinks_list_res.get('success'):
              final_result['sinks'] = sinks_list_res.get('sinks', [])
              final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
         if bt_list_res.get('success'):
              all_bt = bt_list_res.get('devices', [])
              final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
         else: final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code

@app.route('/api/discover-bluetooth')
@admin_login_required
def api_discover_bluetooth():
    scan_duration = request.args.get('duration', config.BLUETOOTH_SCAN_DURATION, type=int) # config'den
    logger.info(f"API: Bluetooth keşfi (Süre: {scan_duration}s, ex.py)...")
    result = _run_command(['discover_bluetooth', '--duration', str(scan_duration)], config.EX_SCRIPT_PATH)
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code

@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    device_path = data.get('device_path')
    if not device_path: return jsonify({'success': False, 'error': 'device_path gerekli'}), 400
    logger.info(f"API: Bluetooth eşleştirme/bağlama: {device_path} (ex.py)...")
    result = _run_command(['pair_bluetooth', '--path', device_path], config.EX_SCRIPT_PATH)
    # ... (geri kalan final_result ve list_sinks/discover_bluetooth çağrıları da config.EX_SCRIPT_PATH kullanmalı)
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'], config.EX_SCRIPT_PATH)
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'], config.EX_SCRIPT_PATH)
         if sinks_list_res.get('success'):
              final_result['sinks'] = sinks_list_res.get('sinks', [])
              final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
         if bt_list_res.get('success'):
              all_bt = bt_list_res.get('devices', [])
              final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
         else: final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code


@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    device_path = data.get('device_path')
    if not device_path: return jsonify({'success': False, 'error': 'device_path gerekli'}), 400
    logger.info(f"API: Bluetooth bağlantısını kesme: {device_path} (ex.py)...")
    result = _run_command(['disconnect_bluetooth', '--path', device_path], config.EX_SCRIPT_PATH)
    # ... (geri kalan final_result ve list_sinks/discover_bluetooth çağrıları da config.EX_SCRIPT_PATH kullanmalı)
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'], config.EX_SCRIPT_PATH)
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'], config.EX_SCRIPT_PATH)
         if sinks_list_res.get('success'):
              final_result['sinks'] = sinks_list_res.get('sinks', [])
              final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
         if bt_list_res.get('success'):
              all_bt = bt_list_res.get('devices', [])
              final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
         else: final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code

@app.route('/api/switch-to-alsa', methods=['POST'])
@admin_login_required
def api_switch_to_alsa():
    logger.info("API: ALSA ses çıkışına geçiş isteniyor (ex.py aracılığıyla)...")
    result = _run_command(['switch_to_alsa'], config.EX_SCRIPT_PATH)
    # ... (geri kalan final_result ve list_sinks/discover_bluetooth çağrıları da config.EX_SCRIPT_PATH kullanmalı)
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'], config.EX_SCRIPT_PATH)
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'], config.EX_SCRIPT_PATH)
         if sinks_list_res.get('success'):
              final_result['sinks'] = sinks_list_res.get('sinks', [])
              final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
         if bt_list_res.get('success'):
              all_bt = bt_list_res.get('devices', [])
              final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
         else: final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code
>>>>>>> main

@app.route('/api/restart-spotifyd', methods=['POST'])
@admin_login_required
def api_restart_spotifyd():
<<<<<<< HEAD
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
=======
    logger.info("API: Spotifyd yeniden başlatma isteği alındı (ex.py aracılığıyla)...")
    success, message = restart_spotifyd() # Bu fonksiyon zaten _run_command'ı doğru çağırıyor
    status_code = 200 if success else 500
    response_data = {'success': success}
    if success: response_data['message'] = message
    else: response_data['error'] = message
    sinks_list_res = _run_command(['list_sinks'], config.EX_SCRIPT_PATH)
    bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'], config.EX_SCRIPT_PATH)
    if sinks_list_res.get('success'):
        response_data['sinks'] = sinks_list_res.get('sinks', [])
        response_data['default_sink_name'] = sinks_list_res.get('default_sink_name')
    if bt_list_res.get('success'):
        all_bt = bt_list_res.get('devices', [])
        response_data['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
    else: response_data['bluetooth_devices'] = []
    return jsonify(response_data), status_code

# --- Filtre Yönetimi API Rotaları ---
@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); item_type = data.get('type'); identifier = data.get('identifier')
    actual_item_type = 'track' if item_type in ['song', 'track'] else 'artist'
    if actual_item_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz öğe tipi (artist veya track).'}), 400

    item_uri = _ensure_spotify_uri(identifier, actual_item_type) # helpers'dan
    if not item_uri: return jsonify({'success': False, 'error': f"Geçersiz Spotify {actual_item_type} ID/URI."}), 400

>>>>>>> main
    list_key = f"{actual_item_type}_blacklist"
    try:
        current_settings = settings.copy() # Global settings'i kullan
        target_list = current_settings.get(list_key, [])
        if item_uri not in target_list:
<<<<<<< HEAD
            target_list.append(item_uri); current_settings[list_key] = target_list; save_settings(current_settings)
            settings = current_settings; # Globali güncelle
=======
            target_list.append(item_uri); current_settings[list_key] = target_list; 
            save_app_settings(current_settings) # app_settings'den
            settings = load_app_settings() # Global settings'i güncelle
            logger.info(f"Hızlı Engelleme: '{item_uri}' ({actual_item_type}) kara listeye eklendi.")
>>>>>>> main
            return jsonify({'success': True, 'message': f"'{identifier}' kara listeye eklendi."})
        return jsonify({'success': True, 'message': f"'{identifier}' zaten kara listede."})
    except Exception as e: return jsonify({'success': False, 'error': f"Engelleme hatası: {e}"}), 500

<<<<<<< HEAD
# ... Diğer filtre API rotaları (add-to-list, remove-from-list) benzer şekilde kalabilir ...

=======
@app.route('/api/add-to-list', methods=['POST'])
@admin_login_required
def api_add_to_list():
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); filter_type = data.get('filter_type'); list_type = data.get('list_type'); item_val = data.get('item')

    actual_filter_type = 'track' if filter_type == 'song' else filter_type
    if actual_filter_type not in ['genre', 'artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item_val or not isinstance(item_val, str) or not item_val.strip(): return jsonify({'success': False, 'error': 'Eklenecek öğe boş olamaz.'}), 400

    item_val = item_val.strip(); processed_item = None
    if actual_filter_type == 'genre':
        processed_item = item_val.lower()
    elif actual_filter_type in ['artist', 'track']:
        processed_item = _ensure_spotify_uri(item_val, actual_filter_type) # helpers'dan
        if not processed_item: return jsonify({'success': False, 'error': f"Geçersiz Spotify {actual_filter_type} ID/URI formatı."}), 400

    if not processed_item: return jsonify({'success': False, 'error': 'İşlenecek öğe oluşturulamadı.'}), 500

    list_key = f"{actual_filter_type}_{list_type}"
    try:
        current_settings = settings.copy() # Global settings'i kullan
        target_list = current_settings.get(list_key, [])
        if target_list is None: target_list = []

        if processed_item not in target_list:
            target_list.append(processed_item); current_settings[list_key] = target_list; 
            save_app_settings(current_settings) # app_settings'den
            settings = load_app_settings() # Global settings'i güncelle
            logger.info(f"Listeye Ekleme: '{processed_item}' -> '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item_val}' listeye eklendi.", 'updated_list': settings[list_key]})
        else:
            logger.info(f"Listeye Ekleme: '{processed_item}' zaten '{list_key}' listesinde.")
            return jsonify({'success': True, 'message': f"'{item_val}' zaten listede.", 'updated_list': target_list})
    except Exception as e: logger.error(f"Listeye ekleme hatası ({list_key}, {item_val}): {e}", exc_info=True); return jsonify({'success': False, 'error': f"Listeye öğe eklenirken hata: {e}"}), 500

@app.route('/api/remove-from-list', methods=['POST'])
@admin_login_required
def api_remove_from_list():
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); filter_type = data.get('filter_type'); list_type = data.get('list_type'); item_val = data.get('item')

    actual_filter_type = 'track' if filter_type == 'song' else filter_type
    if actual_filter_type not in ['genre', 'artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item_val or not isinstance(item_val, str) or not item_val.strip(): return jsonify({'success': False, 'error': 'Çıkarılacak öğe boş olamaz.'}), 400

    item_val = item_val.strip(); item_to_remove = None
    if actual_filter_type == 'genre':
        item_to_remove = item_val.lower()
    elif actual_filter_type in ['artist', 'track']:
        item_to_remove = _ensure_spotify_uri(item_val, actual_filter_type) # helpers'dan

    if not item_to_remove: return jsonify({'success': False, 'error': f"Geçersiz öğe formatı: {item_val}"}), 400

    list_key = f"{actual_filter_type}_{list_type}"
    try:
        current_settings = settings.copy() # Global settings'i kullan
        target_list = current_settings.get(list_key, [])
        if target_list is None: target_list = []

        if item_to_remove in target_list:
            target_list.remove(item_to_remove); current_settings[list_key] = target_list; 
            save_app_settings(current_settings) # app_settings'den
            settings = load_app_settings() # Global settings'i güncelle
            logger.info(f"Listeden Çıkarma: '{item_to_remove}' <- '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item_val}' listeden çıkarıldı.", 'updated_list': target_list})
        else:
            logger.info(f"Listeden Çıkarma: '{item_to_remove}' '{list_key}' listesinde bulunamadı.")
            return jsonify({'success': False, 'error': f"'{item_val}' listede bulunamadı.", 'updated_list': target_list}), 404
    except Exception as e: logger.error(f"Listeden çıkarma hatası ({list_key}, {item_val}): {e}", exc_info=True); return jsonify({'success': False, 'error': f"Listeden öğe çıkarılırken hata: {e}"}), 500

@app.route('/api/spotify/genres')
@admin_login_required
def api_spotify_genres():
    spotify = get_spotify_client() # spotify_client_handler'dan
    if not spotify: return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503
    try:
        genres = spotify.recommendation_genre_seeds()
        return jsonify({'success': True, 'genres': genres.get('genres', [])})
    except Exception as e:
        logger.error(f"Spotify türleri alınırken hata: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Spotify türleri alınamadı.'}), 500

>>>>>>> main
@app.route('/api/spotify/details', methods=['POST'])
@admin_login_required
@spotify_auth_required # Detayları almak için Spotify bağlantısı gerekir
def api_spotify_details():
<<<<<<< HEAD
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

@app.route('/api/lastfm-suggestion')
@spotify_auth_required # Spotify bağlantısı ve yetkilendirmesi bu API için gerekli
# @admin_login_required # Bu API admin olmayan kullanıcılar tarafından da kullanılabilir mi? Şimdilik evet.
                         # Eğer sadece admin içinse, bu satırı aktif et.
def api_lastfm_suggestion():
    """Last.fm geçmişine dayalı bir şarkı önerisi döndürür (API)."""
    suggestion_dict, message = get_lastfm_song_suggestion()
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

=======
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    uris = data.get('ids', [])
    id_type = data.get('type')
    logger.debug(f"Received /api/spotify/details request: type={id_type}, uris_count={len(uris)}")
    if uris: logger.debug(f"First few URIs: {uris[:5]}")

    if not uris or not isinstance(uris, list): return jsonify({'success': False, 'error': 'Geçerli URI listesi gerekli.'}), 400
    actual_id_type = 'track' if id_type == 'song' else id_type
    if actual_id_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz tip (artist veya track).'}), 400

    spotify = get_spotify_client() # spotify_client_handler'dan
    if not spotify: return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503

    details_map = {}
    batch_size = 50
    valid_uris = [_ensure_spotify_uri(uri, actual_id_type) for uri in uris] # helpers'dan
    valid_uris = [uri for uri in valid_uris if uri]

    if not valid_uris:
        logger.warning("No valid Spotify URIs found in the request.")
        return jsonify({'success': True, 'details': {}})
    logger.debug(f"Fetching details for {len(valid_uris)} valid URIs (type: {actual_id_type})...")

    try:
        for i in range(0, len(valid_uris), batch_size):
            batch_uris = valid_uris[i:i + batch_size]
            if not batch_uris: continue
            logger.debug(f"Processing batch {i//batch_size + 1} with URIs: {batch_uris}")
            results = None; items_list = [] # items flask objesiyle karışmasın
            try:
                if actual_id_type == 'artist':
                    results = spotify.artists(batch_uris)
                    items_list = results.get('artists', []) if results else []
                elif actual_id_type == 'track':
                    results = spotify.tracks(batch_uris, market='TR')
                    items_list = results.get('tracks', []) if results else []
            except spotipy.SpotifyException as e:
                logger.error(f"Spotify API error during batch fetch (type: {actual_id_type}, batch: {batch_uris}): {e}")
                if e.http_status == 400: logger.error("Likely caused by invalid URIs in the batch."); continue
                else: raise e # Diğer hataları yeniden fırlat

            if items_list:
                for item_detail in items_list: # item flask objesiyle karışmasın
                    if item_detail:
                        item_uri_detail = item_detail.get('uri')
                        item_name_detail = item_detail.get('name')
                        if item_uri_detail and item_name_detail:
                            if actual_id_type == 'track':
                                artists_det = item_detail.get('artists', [])
                                artist_name_det = ', '.join([a.get('name') for a in artists_det]) if artists_det else ''
                                details_map[item_uri_detail] = f"{item_name_detail} - {artist_name_det}"
                            else: # Artist
                                details_map[item_uri_detail] = item_name_detail
                        else: logger.warning(f"Missing URI or Name in item: {item_detail}")
                    else: logger.warning("Received a null item in the batch response.")
        logger.debug(f"Successfully fetched details for {len(details_map)} items.")
        return jsonify({'success': True, 'details': details_map})
    except spotipy.SpotifyException as e:
         logger.error(f"Spotify API error processing details (type: {actual_id_type}): {e}", exc_info=True)
         return jsonify({'success': False, 'error': f'Spotify API hatası: {e.msg}'}), e.http_status or 500
    except Exception as e:
        logger.error(f"Error fetching Spotify details (type: {actual_id_type}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Spotify detayları alınırken bilinmeyen bir hata oluştu.'}), 500

# --- Arka Plan Şarkı Çalma İş Parçacığı (Hala app.py'de) ---
def background_queue_player():
    global song_queue, user_requests, settings, auto_advance_enabled # Globaller
    logger.info("Arka plan şarkı çalma/öneri görevi başlatılıyor...")
    last_played_song_uri = None; last_suggested_song_uri = None
>>>>>>> main
    while True:
        time.sleep(5) # Her 5 saniyede bir kontrol et
        try:
<<<<<<< HEAD
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
=======
            spotify = get_spotify_client() # spotify_client_handler'dan
            active_spotify_connect_device_id = settings.get('active_device_id') # settings global'i
            if not spotify or not active_spotify_connect_device_id: time.sleep(10); continue
            
            current_playback = None
            try: 
                current_playback = spotify.current_playback(additional_types='track,episode', market='TR')
            except spotipy.SpotifyException as pb_err:
                logger.error(f"Arka plan: Playback kontrol hatası: {pb_err}")
                if pb_err.http_status == 401 or pb_err.http_status == 403: 
                    clear_spotify_client() # Client'ı temizle
                    if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE) # config'den
                time.sleep(10); continue
            except Exception as pb_err: 
                logger.error(f"Arka plan: Playback kontrol genel hata: {pb_err}", exc_info=True); time.sleep(15); continue

            is_playing_now = False; current_track_uri_now = None
            if current_playback:
                is_playing_now = current_playback.get('is_playing', False); item_pb = current_playback.get('item')
                current_track_uri_now = item_pb.get('uri') if item_pb else None

            if auto_advance_enabled and not is_playing_now: # auto_advance_enabled global'i
                if song_queue: # song_queue global'i
                    logger.info(f"Arka plan: Çalma durdu, otomatik ilerleme aktif. Kuyruktan çalınıyor...")
                    next_song = song_queue.pop(0)
                    next_song_uri = next_song.get('id')

                    if not next_song_uri or not next_song_uri.startswith('spotify:track:'):
                        logger.warning(f"Arka plan: Kuyrukta geçersiz URI formatı: {next_song_uri}"); continue
                    if next_song_uri == last_played_song_uri:
                        logger.debug(f"Şarkı ({next_song.get('name')}) zaten son çalınandı, atlanıyor."); last_played_song_uri = None; time.sleep(1); continue

                    logger.info(f"Arka plan: Çalınacak: {next_song.get('name')} ({next_song_uri})")
                    try:
                        spotify.start_playback(device_id=active_spotify_connect_device_id, uris=[next_song_uri])
                        logger.info(f"===> Şarkı çalmaya başlandı: {next_song.get('name')}")
                        last_played_song_uri = next_song_uri; last_suggested_song_uri = None
                        user_ip_addr = next_song.get('added_by') # user_requests global'i
                        if user_ip_addr and user_ip_addr != 'admin' and user_ip_addr != 'auto-time':
                             user_requests[user_ip_addr] = max(0, user_requests.get(user_ip_addr, 0) - 1)
                             logger.debug(f"Kullanıcı {user_ip_addr} limiti azaltıldı: {user_requests.get(user_ip_addr)}")
                        time.sleep(1); continue
                    except spotipy.SpotifyException as start_err:
                        logger.error(f"Arka plan: Şarkı başlatılamadı ({next_song_uri}): {start_err}")
                        song_queue.insert(0, next_song)
                        if start_err.http_status == 401 or start_err.http_status == 403: 
                            clear_spotify_client()
                            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
                        elif start_err.http_status == 404 and 'device_id' in str(start_err).lower():
                             logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device_id}) bulunamadı.");
                             temp_settings = settings.copy() # settings global'i
                             temp_settings['active_device_id'] = None; 
                             save_app_settings(temp_settings) # app_settings'den
                             settings = load_app_settings() # Global settings'i güncelle
                        elif start_err.http_status == 400:
                             logger.error(f"Arka plan: Geçersiz URI nedeniyle şarkı başlatılamadı: {next_song_uri}")
                        time.sleep(5); continue
                    except Exception as start_err: 
                        logger.error(f"Arka plan: Şarkı başlatılırken genel hata ({next_song_uri}): {start_err}", exc_info=True); 
                        song_queue.insert(0, next_song); time.sleep(10); continue
                else: # Kuyruk boşsa öneri yap
                    suggested_song_info = suggest_song_for_time(spotify) # spotify client'ı paslıyoruz
                    if suggested_song_info and suggested_song_info.get('id') != last_suggested_song_uri:
                        suggested_uri = suggested_song_info['id']
                        logger.info(f"Otomatik öneri bulundu: {suggested_song_info['name']} ({suggested_uri})")
                        song_queue.append({ # song_queue global'i
                            'id': suggested_uri, 'name': suggested_song_info['name'],
                            'artist': suggested_song_info.get('artist', '?'),
                            'artist_ids': suggested_song_info.get('artist_ids', []),
                            'added_by': 'auto-time', 'added_at': time.time()
                        })
                        last_suggested_song_uri = suggested_uri
                        logger.info(f"Otomatik öneri kuyruğa eklendi: {suggested_song_info['name']}")
                    else:
                        time.sleep(15)
            elif is_playing_now:
                 if current_track_uri_now and current_track_uri_now != last_played_song_uri:
                     logger.debug(f"Arka plan: Yeni şarkı algılandı: {current_track_uri_now}");
                     last_played_song_uri = current_track_uri_now; last_suggested_song_uri = None
                     update_time_profile(current_track_uri_now, spotify) # spotify client'ı paslıyoruz
                 time.sleep(5)
            else: # Otomatik ilerleme kapalı ve müzik çalmıyor
                 time.sleep(10)
        except Exception as loop_err: 
            logger.error(f"Arka plan döngü hatası: {loop_err}", exc_info=True); time.sleep(15)

# --- Uygulama Başlangıcı (Hala app.py'de) ---
def check_token_on_startup():
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client() # spotify_client_handler'dan
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Yetkilendirme gerekli olabilir.")
>>>>>>> main

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
<<<<<<< HEAD
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
=======
    logger.info(f"Ayarlar Yüklendi (kaynak: {config.SETTINGS_FILE})") # config'den
    logger.info(f"Harici betik yolu: {config.EX_SCRIPT_PATH}") # config'den

    if not config.SPOTIFY_CLIENT_ID or config.SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not config.SPOTIFY_CLIENT_SECRET or config.SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not config.SPOTIFY_REDIRECT_URI or config.SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.error(f"LÜTFEN config.py dosyasında Spotify API bilgilerinizi ayarlayın!")
    else:
         logger.info("Spotify API bilgileri config.py içinde tanımlı görünüyor.")
         logger.info(f"Kullanılacak Redirect URI: {config.SPOTIFY_REDIRECT_URI}")
         logger.info("!!! BU URI'nin Spotify Developer Dashboard'da kayıtlı olduğundan emin olun !!!")

    if not os.path.exists(config.EX_SCRIPT_PATH): # config'den
        logger.error(f"Kritik Hata: Harici betik '{config.EX_SCRIPT_PATH}' bulunamadı!")
    else:
         logger.info(f"'{config.EX_SCRIPT_PATH}' betiği test ediliyor...")
         test_result = _run_command(['list_sinks'], config.EX_SCRIPT_PATH, timeout=10) # config.EX_SCRIPT_PATH eklendi
         if test_result.get('success'): logger.info(f"'{config.EX_SCRIPT_PATH}' betiği başarıyla çalıştı.")
         else: logger.warning(f"'{config.EX_SCRIPT_PATH}' betiği hatası: {test_result.get('error')}.")

    check_token_on_startup()
    start_queue_player()

    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişilebilir.")
    logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişilebilir.")

    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
>>>>>>> main
