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

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# --- Uygulama Başlatma ---
if __name__ == '__main__':
    app.run(debug=True)
