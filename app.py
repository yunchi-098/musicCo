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
# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi
from datetime import datetime
from pymongo import MongoClient
from bson.objectid import ObjectId
import sqlite3

# --- Yapılandırılabilir Ayarlar ---
# !!! BU BİLGİLERİ KENDİ SPOTIFY DEVELOPER BİLGİLERİNİZLE DEĞİŞTİRİN !!!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78' # ÖRNEK - DEĞİŞTİR
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426' # ÖRNEK - DEĞİŞTİR
# !!! BU URI'NIN SPOTIFY DEVELOPER DASHBOARD'DAKİ REDIRECT URI İLE AYNI OLDUĞUNDAN EMİN OLUN !!!
SPOTIFY_REDIRECT_URI = 'http://192.168.36.186:8080/callback' # ÖRNEK - DEĞİŞTİR
SPOTIFY_SCOPE = 'user-read-playback-state user-read-private user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12 # Saniye cinsinden Bluetooth tarama süresi
EX_SCRIPT_PATH = 'ex.py' # ex.py betiğinin yolu
# Kullanıcı arayüzünde gösterilecek varsayılan türler (opsiyonel)
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
# ---------------------------------

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION
app.jinja_env.globals['ALLOWED_GENRES'] = ALLOWED_GENRES

# --- Yardımcı Fonksiyon: Spotify URI İşleme ---
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

    # Unrecognized or invalid format
    logger.warning(f"Tanınmayan veya geçersiz Spotify {actual_item_type} ID/URI formatı: {item_id}")
    return None

# --- Yardımcı Fonksiyon: Komut Çalıştırma (ex.py ve spotifyd için) ---
def _run_command(command, timeout=30):
    """Helper function to run shell commands and return parsed JSON or error."""
    try:
        # Komutun 'python3' ile başlayıp başlamadığını kontrol et
        if command[0] == 'python3' and len(command) > 1 and command[1] == EX_SCRIPT_PATH:
             full_command = command
        elif command[0] == 'spotifyd' or command[0] == 'pgrep':
             full_command = command
        else:
             # Eğer ex.py komutuysa başına python3 ekle
             full_command = ['python3', EX_SCRIPT_PATH] + command

        logger.debug(f"Running command: {' '.join(full_command)}")
        result = subprocess.run(full_command, capture_output=True, text=True, check=True, timeout=timeout, encoding='utf-8')
        logger.debug(f"Command stdout (first 500 chars): {result.stdout[:500]}")
        try:
            # JSON parse etmeyi sadece ex.py çıktısı için yap
            if full_command[0] == 'python3' and full_command[1] == EX_SCRIPT_PATH:
                 if not result.stdout.strip():
                      logger.warning(f"Command {' '.join(full_command)} returned empty output.")
                      return {'success': False, 'error': 'Komut boş çıktı döndürdü.'}
                 return json.loads(result.stdout)
            else: # spotifyd veya pgrep gibi diğer komutlar için ham çıktıyı döndür
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

# --- Spotifyd Yardımcı Fonksiyonları ---
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
    result = _run_command(['restart_spotifyd']) # ex.py'nin kendi komutunu çağırır
    return result.get('success', False), result.get('message', result.get('error', 'Bilinmeyen hata'))

# --- Ayarlar Yönetimi (Filtreler Eklendi) ---
def load_settings():
    """Ayarları dosyadan yükler, eksik filtre ayarları için varsayılanları ekler."""
    default_settings = {
        'max_queue_length': 20, 'max_user_requests': 5, 'active_device_id': None,
        'genre_filter_mode': 'blacklist', 'artist_filter_mode': 'blacklist', 'song_filter_mode': 'blacklist',
        'genre_blacklist': [], 'genre_whitelist': [],
        'artist_blacklist': [], 'artist_whitelist': [], # Bunlar URI listeleri olmalı
        'track_blacklist': [], 'track_whitelist': [], # Anahtar 'track' olmalı
    }
    settings_to_use = default_settings.copy() # Önce varsayılanı al
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: loaded = json.load(f)

            # Eski 'song_' anahtarlarını 'track_' anahtarlarına dönüştür (varsa)
            if 'song_blacklist' in loaded:
                if 'track_blacklist' not in loaded: # Sadece track_blacklist yoksa taşı
                    loaded['track_blacklist'] = loaded.pop('song_blacklist')
                    logger.info("Eski 'song_blacklist' ayarı 'track_blacklist' olarak taşındı.")
                else: # İkisi de varsa song_ olanı sil
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


            # Yüklenen ayarları varsayılanların üzerine yaz
            settings_to_use.update(loaded)
            # Eksik anahtarları tekrar kontrol et (update sonrası)
            updated = False
            for key, default_value in default_settings.items():
                if key not in settings_to_use:
                    logger.info(f"'{key}' ayarı dosyada bulunamadı (update sonrası), varsayılan değer ({default_value}) ekleniyor.")
                    settings_to_use[key] = default_value
                    updated = True
            # Eski 'active_genres' ayarını kaldır (varsa)
            if 'active_genres' in settings_to_use:
                del settings_to_use['active_genres']; logger.info("Eski 'active_genres' ayarı kaldırıldı."); updated = True
            # Listelerin URI formatında olduğundan emin ol (yeni eklenmişse veya eski formattaysa)
            for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
                if key in settings_to_use:
                    item_type = 'track' if 'track' in key else 'artist'
                    original_list = settings_to_use[key]
                    # NoneType hatasını önle
                    if original_list is None:
                        original_list = []
                        settings_to_use[key] = []
                        updated = True

                    converted_list = []
                    changed = False
                    # Listenin gerçekten liste olduğundan emin ol
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
                            if uri != item: changed = True # Format değiştiyse işaretle
                        else:
                            logger.warning(f"Ayarlar yüklenirken '{key}' listesindeki geçersiz öğe atlandı: {item}")
                            changed = True # Geçersiz öğe kaldırıldıysa işaretle
                    if changed:
                        settings_to_use[key] = sorted(list(set(converted_list)))
                        updated = True

            if updated:
                save_settings(settings_to_use) # Eksik anahtar eklendiyse veya format düzeltildiyse kaydet
            logger.info(f"Ayarlar yüklendi: {SETTINGS_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Ayar dosyası ({SETTINGS_FILE}) bozuk JSON içeriyor: {e}. Varsayılanlar kullanılacak.")
            settings_to_use = default_settings.copy() # Hata durumunda varsayılana dön
        except Exception as e:
            logger.error(f"Ayar dosyası ({SETTINGS_FILE}) okunamadı: {e}. Varsayılanlar kullanılacak.")
            settings_to_use = default_settings.copy() # Hata durumunda varsayılana dön
    else:
        logger.info(f"Ayar dosyası bulunamadı, varsayılanlar oluşturuluyor: {SETTINGS_FILE}")
        settings_to_use = default_settings.copy()
        save_settings(settings_to_use)
    return settings_to_use

def save_settings(current_settings):
    """Ayarları dosyaya kaydeder. Listeleri temizler, URI formatına çevirir ve sıralar."""
    try:
        # Ayarları kopyala ki orijinal dict değişmesin (fonksiyon dışından geldiyse)
        settings_to_save = current_settings.copy()

        # Tür listelerini küçük harfe çevir ve sırala
        if 'genre_blacklist' in settings_to_save:
            settings_to_save['genre_blacklist'] = sorted(list(set([g.lower() for g in settings_to_save.get('genre_blacklist', []) if isinstance(g, str) and g.strip()])))
        if 'genre_whitelist' in settings_to_save:
            settings_to_save['genre_whitelist'] = sorted(list(set([g.lower() for g in settings_to_save.get('genre_whitelist', []) if isinstance(g, str) and g.strip()])))

        # Sanatçı ve Şarkı listelerini URI formatına çevir, temizle ve sırala
        for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
             if key in settings_to_save:
                  cleaned_uris = set()
                  item_type = 'track' if 'track' in key else 'artist'
                  # Listenin var olduğundan ve None olmadığından emin ol
                  current_list = settings_to_save.get(key, [])
                  if current_list is None: current_list = []

                  # Listenin gerçekten liste olduğundan emin ol
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

# --- Global Değişkenler ---
spotify_client = None
song_queue = [] # Şarkı objelerini tutar {'id': URI, 'name': ..., 'artist': ..., 'artist_ids': [URI,...], ...}
user_requests = {} # IP adresi başına istek sayısını tutar
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] } # Zaman profilleri için şarkı/sanatçı URI'lerini tutar
settings = load_settings() # Ayarları başlangıçta yükle
auto_advance_enabled = True # Otomatik şarkı geçişi aktif mi?

# --- Spotify Token Yönetimi (İyileştirildi) ---
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
                auth_manager.token = token_info # Eski token'ı set et
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

# --- Admin Giriş Decorator'ı ---
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            flash("Bu sayfaya erişmek için yönetici girişi yapmalısınız.", "warning")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Zaman Profili ve Öneri Fonksiyonları ---
def get_current_time_profile():
    hour = time.localtime().tm_hour
    if 6 <= hour < 12: return 'sabah'
    elif 12 <= hour < 18: return 'oglen'
    elif 18 <= hour < 24: return 'aksam'
    else: return 'gece'

def update_time_profile(track_uri, spotify):
    """Verilen track URI'sini mevcut zaman profiline ekler."""
    global time_profiles
    if not spotify or not track_uri or not track_uri.startswith('spotify:track:'):
        logger.warning(f"update_time_profile: geçersiz parametre veya format: {track_uri}"); return
    profile_name = get_current_time_profile()
    logger.debug(f"'{profile_name}' profili güncelleniyor, track_uri: {track_uri}")
    try:
        track_info = spotify.track(track_uri, market='TR')
        if not track_info: logger.warning(f"Şarkı detayı alınamadı: {track_uri}"); return
        track_name = track_info.get('name', '?'); artists = track_info.get('artists')
        primary_artist_uri = _ensure_spotify_uri(artists[0].get('id'), 'artist') if artists and artists[0].get('id') else None
        primary_artist_name = artists[0].get('name') if artists else '?'
        # Profile sadece URI'leri ekleyelim (daha az yer kaplar)
        profile_entry = {'track_uri': track_uri, 'artist_uri': primary_artist_uri}
        # Aynı şarkı/sanatçı tekrar eklenmesin
        if profile_entry not in time_profiles[profile_name]:
            time_profiles[profile_name].append(profile_entry)
            # Profil boyutunu sınırla
            if len(time_profiles[profile_name]) > 5: time_profiles[profile_name] = time_profiles[profile_name][-5:]
            logger.info(f"'{profile_name}' profiline eklendi: '{track_name}' ({track_uri})")
        else:
            logger.debug(f"'{profile_name}' profilinde zaten var: {track_uri}")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken hata (URI: {track_uri}): {e}", exc_info=True)

def suggest_song_for_time(spotify):
    """Mevcut zaman profiline göre şarkı önerir."""
    global time_profiles, song_queue
    if not spotify: logger.warning("suggest_song_for_time: spotify istemcisi eksik."); return None
    profile_name = get_current_time_profile(); profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None

    # Son eklenenlerden tohumları al
    seed_tracks = []; seed_artists = []
    for entry in reversed(profile_data): # Sondan başa doğru git
        if entry.get('track_uri') and entry['track_uri'] not in seed_tracks:
            seed_tracks.append(entry['track_uri'])
        if entry.get('artist_uri') and entry['artist_uri'] not in seed_artists:
            seed_artists.append(entry['artist_uri'])
        if len(seed_tracks) + len(seed_artists) >= 5: break # Spotify max 5 tohum alır

    if not seed_tracks and not seed_artists: logger.warning(f"'{profile_name}' profili öneri için tohum içermiyor."); return None

    try:
        logger.info(f"'{profile_name}' için öneri isteniyor: seeds_tracks={seed_tracks}, seeds_artists={seed_artists}")
        recs = spotify.recommendations(seed_tracks=seed_tracks, seed_artists=seed_artists, limit=5, market='TR')
        if recs and recs.get('tracks'):
            for suggested_track in recs['tracks']:
                 suggested_uri = suggested_track.get('uri') # URI'yi al
                 if not suggested_uri: continue
                 # Kuyrukta olup olmadığını kontrol et
                 if not any(song.get('id') == suggested_uri for song in song_queue):
                    is_allowed, _ = check_song_filters(suggested_uri, spotify) # Filtre kontrolü
                    if is_allowed:
                        logger.info(f"'{profile_name}' için öneri bulundu ve filtreden geçti: '{suggested_track.get('name')}' ({suggested_uri})")
                        # Önerilen şarkı bilgisini döndür
                        artists = suggested_track.get('artists', []);
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
                        artist_names = [a.get('name') for a in artists]
                        images = suggested_track.get('album', {}).get('images', [])
                        image_url = images[-1].get('url') if images else None
                        return {
                            'id': suggested_uri, # URI olarak döndür
                            'name': suggested_track.get('name'),
                            'artist': ', '.join(artist_names),
                            'artist_ids': artist_uris, # URI listesi
                            'image_url': image_url
                        }
                    else:
                         logger.info(f"'{profile_name}' için öneri bulundu ancak filtrelere takıldı: '{suggested_track.get('name')}' ({suggested_uri})")
            logger.info(f"'{profile_name}' önerileri kuyrukta mevcut veya filtrelere takıldı.")
        else: logger.info(f"'{profile_name}' için öneri alınamadı."); return None
    except Exception as e: logger.error(f"'{profile_name}' için öneri alınırken hata: {e}", exc_info=True); return None
    return None # Uygun öneri bulunamazsa

# --- Şarkı Filtreleme Yardımcı Fonksiyonu (Güncellendi) ---
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
        # 1. Şarkı Bilgilerini Al
        song_info = spotify_client.track(track_uri, market='TR')
        if not song_info: return False, f"Şarkı bulunamadı (URI: {track_uri})."
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []);
        # Sanatçı ID'lerini URI formatına çevir
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists];
        primary_artist_uri = artist_uris[0] if artist_uris else None # İlk sanatçının URI'sini al
        logger.debug(f"Şarkı bilgileri: {song_name}, Sanatçılar: {artist_names} ({artist_uris})")

        # Ayarlardaki filtre listelerini al (URI formatında olmalılar)
        track_blacklist_uris = settings.get('track_blacklist', []) # 'track_' kullan
        track_whitelist_uris = settings.get('track_whitelist', []) # 'track_' kullan
        artist_blacklist_uris = settings.get('artist_blacklist', [])
        artist_whitelist_uris = settings.get('artist_whitelist', [])
        genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
        genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]

        # 2. Şarkı Filtresi Kontrolü
        track_filter_mode = settings.get('track_filter_mode', 'blacklist') # 'track_' kullan
        logger.debug(f"Şarkı ('track') filtresi modu: {track_filter_mode}")
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
        logger.debug(f"Şarkı ('track') filtresinden geçti: {track_uri}")

        # 3. Sanatçı Filtresi Kontrolü
        artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
        logger.debug(f"Sanatçı filtresi modu: {artist_filter_mode}")
        if artist_filter_mode == 'blacklist':
            # Şarkının sanatçılarından herhangi biri kara listede mi?
            if any(a_uri in artist_blacklist_uris for a_uri in artist_uris if a_uri):
                blocked_artist_info = next(((a_uri, a_name) for a_uri, a_name in zip(artist_uris, artist_names) if a_uri in artist_blacklist_uris), (None, "?"))
                logger.debug(f"Filtre takıldı: Sanatçı ({blocked_artist_info[1]} - {blocked_artist_info[0]}) kara listede.")
                return False, f"'{blocked_artist_info[1]}' sanatçısı kara listede."
        elif artist_filter_mode == 'whitelist':
            if not artist_whitelist_uris:
                logger.debug("Filtre takıldı: Sanatçı beyaz listesi boş.")
                return False, 'Sanatçı beyaz listesi aktif ama boş.'
            # Şarkının sanatçılarından en az biri beyaz listede mi?
            if not any(a_uri in artist_whitelist_uris for a_uri in artist_uris if a_uri):
                logger.debug(f"Filtre takıldı: Sanatçı ({artist_names}) beyaz listede değil. Beyaz Liste: {artist_whitelist_uris}")
                return False, 'Bu sanatçı beyaz listede değil.'
        logger.debug("Sanatçı filtresinden geçti.")

        # 4. Tür Filtresi Kontrolü
        genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
        logger.debug(f"Tür filtresi modu: {genre_filter_mode}")
        # Sadece listelerden biri doluysa ve mod aktifse tür kontrolü yap
        run_genre_check = (genre_filter_mode == 'blacklist' and genre_blacklist) or \
                          (genre_filter_mode == 'whitelist' and genre_whitelist)

        if run_genre_check:
            artist_genres = []
            # Birincil sanatçının türlerini almayı dene
            if primary_artist_uri:
                try:
                    artist_info = spotify_client.artist(primary_artist_uri)
                    artist_genres = [g.lower() for g in artist_info.get('genres', [])]
                    logger.debug(f"Sanatçı türleri ({primary_artist_uri}): {artist_genres}")
                except Exception as e: logger.warning(f"Tür filtresi: Sanatçı türleri alınamadı ({primary_artist_uri}): {e}")

            if not artist_genres: logger.warning(f"Tür filtresi uygulanamıyor (türler yok): {song_name}. İzin veriliyor.")
            else:
                if genre_filter_mode == 'blacklist':
                    # Sanatçının türlerinden herhangi biri kara listede mi?
                    if any(genre in genre_blacklist for genre in artist_genres):
                        blocked_genre = next((genre for genre in artist_genres if genre in genre_blacklist), "?")
                        logger.debug(f"Filtre takıldı: Tür ({blocked_genre}) kara listede.")
                        return False, f"'{blocked_genre}' türü kara listede."
                elif genre_filter_mode == 'whitelist':
                    if not genre_whitelist: # Beyaz liste boşsa kontrol etmeye gerek yok, zaten izin verilmez
                         logger.debug("Filtre takıldı: Tür beyaz listesi boş.")
                         return False, 'Tür beyaz listesi aktif ama boş.'
                    # Sanatçının türlerinden en az biri beyaz listede mi?
                    if not any(genre in genre_whitelist for genre in artist_genres):
                        logger.debug(f"Filtre takıldı: Tür ({artist_genres}) beyaz listede değil. Beyaz Liste: {genre_whitelist}")
                        return False, 'Bu tür beyaz listede değil.'
            logger.debug("Tür filtresinden geçti.")
        else:
             logger.debug("Tür filtresi uygulanmadı (mod blacklist/whitelist değil veya ilgili liste boş).")

        # 5. Tüm Filtrelerden Geçti
        logger.debug(f"Filtre kontrolü tamamlandı: İzin verildi - {track_uri}")
        return True, "Filtrelerden geçti."

    except spotipy.SpotifyException as e:
        logger.error(f"Filtre kontrolü sırasında Spotify hatası (URI={track_uri}): {e}")
        if e.http_status == 400: return False, f"Geçersiz Spotify Şarkı URI: {track_uri}"
        return False, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"Filtre kontrolü sırasında hata (URI={track_uri}): {e}", exc_info=True)
        return False, "Filtre kontrolü sırasında bilinmeyen hata."

# --- Flask Rotaları ---

@app.route('/')
def index():
    """Ana sayfayı gösterir."""
    return render_template('index.html', allowed_genres=ALLOWED_GENRES)

@app.route('/admin')
def admin():
    """Admin giriş sayfasını veya paneli gösterir."""
    if session.get('admin_logged_in'): return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    """Admin giriş isteğini işler."""
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123") # Güvenli bir yerden alınmalı
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

    # Ses cihazı bilgilerini al
    audio_sinks_result = _run_command(['list_sinks'])
    audio_sinks = audio_sinks_result.get('sinks', []) if audio_sinks_result.get('success') else []
    default_audio_sink_name = audio_sinks_result.get('default_sink_name') if audio_sinks_result.get('success') else None
    if not audio_sinks_result.get('success'):
        flash(f"Ses cihazları listelenemedi: {audio_sinks_result.get('error', 'Bilinmeyen hata')}", "danger")

    if spotify:
        spotify_authenticated = True
        session['spotify_authenticated'] = True
        try:
            # Spotify cihazlarını al
            result = spotify.devices(); spotify_devices = result.get('devices', [])
            # Kullanıcı bilgisini al
            try: user = spotify.current_user(); spotify_user = user.get('display_name', '?'); session['spotify_user'] = spotify_user
            except Exception as user_err: logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}"); session.pop('spotify_user', None)
            # Şu an çalan şarkı bilgisini al
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']; is_playing = playback.get('is_playing', False)
                    track_uri = item.get('uri') # URI'yi al
                    if track_uri and track_uri.startswith('spotify:track:'):
                         # Çalan şarkının filtrelere uyup uymadığını kontrol et (admin görsün ama)
                         is_allowed, _ = check_song_filters(track_uri, spotify)
                         track_name = item.get('name', '?'); artists = item.get('artists', [])
                         artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
                         artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
                         images = item.get('album', {}).get('images', []); image_url = images[0].get('url') if images else None
                         currently_playing_info = {
                             'id': track_uri, # URI olarak sakla
                             'name': track_name, 'artist': artist_name,
                             'artist_ids': artist_uris, # URI listesi
                             'image_url': image_url, 'is_playing': is_playing,
                             'is_allowed': is_allowed # Filtre durumunu ekle
                         }
                         logger.debug(f"Şu An Çalıyor (Admin): {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'} - Filtre İzin: {is_allowed}")
            except Exception as pb_err: logger.warning(f"Çalma durumu alınamadı: {pb_err}")

            # Kuyruğu filtrele (Admin panelinde sadece izin verilenler görünsün)
            for song in song_queue:
                song_uri = song.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, spotify)
                    if is_allowed:
                        # Sanatçı ID'lerinin URI formatında olduğundan emin ol (eski veriler için)
                        if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                             song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song['artist_ids']]
                        filtered_queue.append(song)
                    else:
                        logger.debug(f"Admin Paneli: Kuyruktaki şarkı filtrelendi: {song.get('name')} ({song_uri})")
                else:
                     logger.warning(f"Admin Paneli: Kuyrukta geçersiz şarkı formatı: {song}")


        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e.http_status} - {e.msg}")
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            if e.http_status == 401 or e.http_status == 403:
                flash("Spotify yetkilendirmesi geçersiz veya süresi dolmuş. Lütfen tekrar yetkilendirin.", "warning")
                if os.path.exists(TOKEN_FILE): logger.warning("Geçersiz token dosyası siliniyor."); os.remove(TOKEN_FILE)
                spotify_client = None
            else: flash(f"Spotify API hatası: {e.msg}", "danger")
        except Exception as e:
            logger.error(f"Admin panelinde beklenmedik hata: {e}", exc_info=True)
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            flash("Beklenmedik bir hata oluştu.", "danger")
    else:
        spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
        if not os.path.exists(TOKEN_FILE): flash("Spotify hesabınızı bağlamak için lütfen yetkilendirme yapın.", "info")

    return render_template(
        'admin_panel.html',
        settings=settings, # Tüm ayarları gönder
        spotify_devices=spotify_devices,
        queue=filtered_queue, # Filtrelenmiş kuyruğu gönder
        all_genres=ALLOWED_GENRES, # Filtre yönetimi için
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        audio_sinks=audio_sinks, default_audio_sink_name=default_audio_sink_name,
        currently_playing_info=currently_playing_info, # Filtre durumu dahil
        auto_advance_enabled=auto_advance_enabled
    )

# --- Çalma Kontrol Rotaları ---
@app.route('/player/pause')
@admin_login_required
def player_pause():
    global auto_advance_enabled; spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        logger.info(f"Admin: Duraklatma isteği (Cihaz: {active_spotify_connect_device_id or '?'}).")
        spotify.pause_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = False; logger.info("Admin: Otomatik geçiş DURAKLATILDI.")
        flash('Müzik duraklatıldı ve otomatik geçiş kapatıldı.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify duraklatma hatası: {e}")
        if e.http_status == 401 or e.http_status == 403: flash('Spotify yetkilendirme hatası.', 'danger');
        global spotify_client; spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404: flash(f'Duraklatma hatası: Cihaz bulunamadı ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE': flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        else: flash(f'Spotify duraklatma hatası: {e.msg}', 'danger')
    except Exception as e: logger.error(f"Duraklatma sırasında genel hata: {e}", exc_info=True); flash('Müzik duraklatılırken bir hata oluştu.', 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/player/resume')
@admin_login_required
def player_resume():
    spotify = get_spotify_client()
    if not spotify:
        flash('Spotify bağlantısı yok!', 'danger')
        return redirect(url_for('admin_panel'))

    try:
        spotify.start_playback()
        flash('Çalma devam ediyor ve otomatik geçiş açık.', 'success')
    except Exception as e:
        flash(f'Çalma başlatılamadı: {str(e)}', 'danger')

    return redirect(url_for('admin_panel'))

@app.route('/player/skip')
@admin_login_required
def player_skip():
    spotify = get_spotify_client()
    if not spotify:
        flash('Spotify bağlantısı yok!', 'danger')
        return redirect(url_for('admin_panel'))

    try:
        spotify.next_track()
        flash('Sıradaki şarkıya geçildi.', 'success')
    except Exception as e:
        flash(f'Şarkı değiştirilemedi: {str(e)}', 'danger')

    return redirect(url_for('admin_panel'))

# --- Diğer Rotalar ---
@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    spotify = get_spotify_client()
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        result = spotify.devices(); devices = result.get('devices', [])
        logger.info(f"Spotify Connect Cihazları yenilendi: {len(devices)} cihaz")
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device and not any(d['id'] == active_spotify_connect_device for d in devices):
            logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device}) listede yok. Ayar temizleniyor.")
            settings['active_device_id'] = None; save_settings(settings)
            flash('Ayarlardaki aktif Spotify Connect cihazı artık mevcut değil.', 'warning')
        flash('Spotify Connect cihaz listesi yenilendi.', 'info')
    except Exception as e:
        logger.error(f"Spotify Connect Cihazlarını yenilerken hata: {e}")
        flash('Spotify Connect cihaz listesi yenilenirken bir hata oluştu.', 'danger')
        if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
            global spotify_client; spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    global settings
    try:
        logger.info("Ayarlar güncelleniyor...")
        current_settings = load_settings() # En güncel ayarları al
        current_settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        current_settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        if 'active_spotify_connect_device_id' in request.form:
             new_spotify_device_id = request.form.get('active_spotify_connect_device_id')
             current_settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {current_settings['active_device_id']}")
        current_settings['genre_filter_mode'] = request.form.get('genre_filter_mode', 'blacklist')
        current_settings['artist_filter_mode'] = request.form.get('artist_filter_mode', 'blacklist')
        # Şarkı filtresi modu için 'track_filter_mode' kullan
        current_settings['track_filter_mode'] = request.form.get('song_filter_mode', 'blacklist') # Formdan 'song_' gelir ama 'track_' olarak kaydet
        save_settings(current_settings);
        settings = current_settings # Global ayarları güncelle
        logger.info(f"Ayarlar güncellendi: {settings}")
        flash("Ayarlar başarıyla güncellendi.", "success")
    except ValueError:
        logger.error("Ayarları güncellerken geçersiz sayısal değer.")
        flash("Geçersiz sayısal değer girildi!", "danger")
    except Exception as e:
        logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True)
        flash("Ayarlar güncellenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    if os.path.exists(TOKEN_FILE): logger.warning("Mevcut token varken yeniden yetkilendirme.")
    try: auth_manager = get_spotify_auth(); auth_url = auth_manager.get_authorize_url(); logger.info("Spotify yetkilendirme URL'sine yönlendiriliyor."); return redirect(auth_url)
    except ValueError as e: logger.error(f"Spotify yetkilendirme hatası: {e}"); flash(f"Spotify Yetkilendirme Hatası: {e}", "danger"); return redirect(url_for('admin_panel'))
    except Exception as e: logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True); flash("Spotify yetkilendirme başlatılamadı.", "danger"); return redirect(url_for('admin_panel'))

@app.route('/callback')
def callback():
    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(f"Callback hatası: {e}"); return f"Callback Hatası: {e}", 500
    if 'error' in request.args: error = request.args.get('error'); logger.error(f"Spotify yetkilendirme hatası (callback): {error}"); return f"Spotify Yetkilendirme Hatası: {error}", 400
    if 'code' not in request.args: logger.error("Callback'te 'code' yok."); return "Geçersiz callback isteği.", 400
    code = request.args.get('code')
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        if not token_info: logger.error("Spotify'dan token alınamadı."); return "Token alınamadı.", 500
        if isinstance(token_info, str): logger.error("get_access_token sadece string döndürdü, refresh token alınamadı."); return "Token bilgisi eksik alındı.", 500
        elif not isinstance(token_info, dict): logger.error(f"get_access_token beklenmedik formatta veri döndürdü: {type(token_info)}"); return "Token bilgisi alınırken hata oluştu.", 500
        if save_token(token_info):
            global spotify_client; spotify_client = None # Yeni token ile istemciyi yeniden oluşturmaya zorla
            logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
            if session.get('admin_logged_in'): flash("Spotify yetkilendirmesi başarıyla tamamlandı!", "success"); return redirect(url_for('admin_panel'))
            else: return redirect(url_for('index')) # Admin değilse ana sayfaya yönlendir
        else: logger.error("Alınan token dosyaya kaydedilemedi."); return "Token kaydedilirken bir hata oluştu.", 500
    except spotipy.SpotifyOauthError as e: logger.error(f"Spotify token alırken OAuth hatası: {e}", exc_info=True); return f"Token alınırken yetkilendirme hatası: {e}", 500
    except Exception as e: logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True); return "Token işlenirken bir hata oluştu.", 500

# GÜNCELLENDİ: /search endpoint'i filtrelemeyi uygular ve URI kullanır
@app.route('/search', methods=['POST'])
def search():
    """Spotify'da arama yapar ve sonuçları aktif filtrelere göre süzer."""
    global settings
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track') # Arama tipi (track veya artist)
    logger.info(f"Arama isteği: '{search_query}' (Tip: {search_type})")
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400

    spotify = get_spotify_client()
    if not spotify: logger.error("Arama: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503

    try:
        items = []
        if search_type == 'artist':
             results = spotify.search(q=search_query, type='artist', limit=20, market='TR')
             items = results.get('artists', {}).get('items', [])
             logger.info(f"Spotify'dan {len(items)} sanatçı bulundu.")
        elif search_type == 'track':
             results = spotify.search(q=search_query, type='track', limit=20, market='TR')
             items = results.get('tracks', {}).get('items', [])
             logger.info(f"Spotify'dan {len(items)} şarkı bulundu.")
        else:
             return jsonify({'error': 'Geçersiz arama tipi.'}), 400

        filtered_items = []
        for item in items:
            if not item: continue
            item_uri = item.get('uri') # URI'yi al
            if not item_uri: continue

            is_allowed = True; reason = ""
            if search_type == 'track':
                # Şarkı filtresini URI ile kontrol et
                is_allowed, reason = check_song_filters(item_uri, spotify)
            elif search_type == 'artist':
                # Sanatçı filtresini URI ile kontrol et
                artist_uri_to_check = item_uri
                artist_name = item.get('name')
                artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
                artist_blacklist_uris = settings.get('artist_blacklist', [])
                artist_whitelist_uris = settings.get('artist_whitelist', [])

                if artist_filter_mode == 'blacklist':
                    if artist_uri_to_check in artist_blacklist_uris: is_allowed = False; reason = f"'{artist_name}' kara listede."
                elif artist_filter_mode == 'whitelist':
                    if not artist_whitelist_uris: is_allowed = False; reason = "Sanatçı beyaz listesi boş."
                    elif artist_uri_to_check not in artist_whitelist_uris: is_allowed = False; reason = f"'{artist_name}' beyaz listede değil."

                # Sanatçı filtresinden geçtiyse tür filtresini uygula
                if is_allowed:
                    genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
                    genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
                    genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]
                    run_genre_check = (genre_filter_mode == 'blacklist' and genre_blacklist) or \
                                      (genre_filter_mode == 'whitelist' and genre_whitelist)
                    if run_genre_check:
                        artist_genres = [g.lower() for g in item.get('genres', [])]
                        if not artist_genres: logger.warning(f"Tür filtresi uygulanamıyor (türler yok): {artist_name}")
                        else:
                            if genre_filter_mode == 'blacklist':
                                if any(genre in genre_blacklist for genre in artist_genres):
                                    blocked_genre = next((genre for genre in artist_genres if genre in genre_blacklist), "?"); is_allowed = False; reason = f"'{blocked_genre}' türü kara listede."
                            elif genre_filter_mode == 'whitelist':
                                if not genre_whitelist: is_allowed = False; reason = "Tür beyaz listesi boş."
                                elif not any(genre in genre_whitelist for genre in artist_genres): is_allowed = False; reason = "Bu tür beyaz listede değil."

            # Eğer öğe filtrelere takılmadıysa listeye ekle
            if is_allowed: filtered_items.append(item)
            else: logger.debug(f"Arama sonucu filtrelendi ({reason}): {item.get('name')} ({item_uri})")

        # Sonuçları frontend için formatla (ID ve diğer bilgilerle)
        search_results = []
        limit = 10 # Frontend'de gösterilecek max sonuç sayısı
        for item in filtered_items[:limit]:
            item_id = item.get('id') # Frontend genellikle ID bekler
            item_uri = item.get('uri')
            if not item_id or not item_uri: continue

            result_data = {'id': item_id, 'uri': item_uri, 'name': item.get('name')} # Temel bilgiler
            images = item.get('images', [])
            if not images and 'album' in item: images = item.get('album', {}).get('images', []) # Şarkılar için albüm kapağı
            result_data['image'] = images[-1].get('url') if images else None

            if search_type == 'artist':
                 result_data['genres'] = item.get('genres', [])
            elif search_type == 'track':
                 artists = item.get('artists', []);
                 result_data['artist'] = ', '.join([a.get('name') for a in artists])
                 result_data['artist_ids'] = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')] # Sanatçı URI'leri
                 result_data['album'] = item.get('album', {}).get('name')

            search_results.append(result_data)

        logger.info(f"Filtrelenmiş {search_type} arama sonucu: {len(search_results)} öğe.")
        return jsonify({'results': search_results})

    except Exception as e:
        logger.error(f"Spotify araması hatası ({search_type}): {e}", exc_info=True)
        return jsonify({'error': 'Arama sırasında sorun oluştu.'}), 500


@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
    """Admin tarafından şarkı ekleme (Filtreleri atlar)."""
    global song_queue
    song_input = request.form.get('song_id', '').strip()
    if not song_input: flash("Şarkı ID/URL girin.", "warning"); return redirect(url_for('admin_panel'))

    # Girdiyi URI formatına çevir
    track_uri = _ensure_spotify_uri(song_input, 'track')
    if not track_uri: flash("Geçersiz Spotify Şarkı ID veya URL formatı.", "danger"); return redirect(url_for('admin_panel'))

    if len(song_queue) >= settings.get('max_queue_length', 20): flash("Kuyruk dolu!", "warning"); return redirect(url_for('admin_panel'))

    spotify = get_spotify_client()
    if not spotify: flash("Spotify yetkilendirmesi gerekli.", "warning"); return redirect(url_for('spotify_auth'))

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: flash(f"Şarkı bulunamadı (URI: {track_uri}).", "danger"); return redirect(url_for('admin_panel'))

        artists = song_info.get('artists');
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        song_queue.append({
            'id': track_uri, # URI olarak ekle
            'name': song_info.get('name', '?'),
            'artist': ', '.join([a.get('name') for a in artists]),
            'artist_ids': artist_uris, # URI listesi
            'added_by': 'admin',
            'added_at': time.time()
        })
        logger.info(f"Şarkı eklendi (Admin - Filtresiz): {track_uri} - {song_info.get('name')}")
        flash(f"'{song_info.get('name')}' eklendi.", "success");
        update_time_profile(track_uri, spotify) # Zaman profiline ekle
    except spotipy.SpotifyException as e:
        logger.error(f"Admin eklerken Spotify hatası (URI={track_uri}): {e}")
        if e.http_status == 401 or e.http_status == 403: flash("Spotify yetkilendirme hatası.", "danger"); return redirect(url_for('spotify_auth'))
        elif e.http_status == 400: flash(f"Geçersiz Spotify URI: {track_uri}", "danger")
        else: flash(f"Spotify hatası: {e.msg}", "danger")
    except Exception as e: logger.error(f"Admin eklerken genel hata (URI={track_uri}): {e}", exc_info=True); flash("Şarkı eklenirken hata.", "danger")
    return redirect(url_for('admin_panel'))

# --- Queue Rotaları ---
@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Kullanıcı tarafından şarkı ekleme (Filtreler uygulanır)."""
    global settings, song_queue, user_requests
    if not request.is_json: return jsonify({'error': 'Geçersiz format.'}), 400
    data = request.get_json();
    # Frontend'den gelen ID'yi al (sadece ID veya URI olabilir)
    track_identifier = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: identifier={track_identifier}")
    if not track_identifier: return jsonify({'error': 'Eksik ID.'}), 400

    # Gelen ID'yi URI formatına çevir
    track_uri = _ensure_spotify_uri(track_identifier, 'track')
    if not track_uri:
        logger.error(f"Kullanıcı ekleme: Geçersiz ID formatı: {track_identifier}")
        return jsonify({'error': 'Geçersiz şarkı ID formatı.'}), 400

    # Kuyruk limiti kontrolü
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning("Kuyruk dolu."); return jsonify({'error': 'Kuyruk dolu.'}), 429

    # Kullanıcı istek limiti kontrolü
    user_ip = request.remote_addr; max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: logger.warning(f"Limit aşıldı: {user_ip}"); return jsonify({'error': f'İstek limitiniz ({max_requests}) doldu.'}), 429

    spotify = get_spotify_client()
    if not spotify: logger.error("Ekleme: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503

    # Filtreleri URI ile kontrol et
    is_allowed, reason = check_song_filters(track_uri, spotify)
    if not is_allowed:
        logger.info(f"Reddedildi ({reason}): {track_uri}")
        return jsonify({'error': reason}), 403 # 403 Forbidden

    # Filtrelerden geçtiyse şarkı bilgilerini tekrar al (güvenlik için) ve kuyruğa ekle
    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: return jsonify({'error': 'Şarkı bilgisi alınamadı (tekrar kontrol).'}), 500
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []);
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists]

        logger.info(f"Filtrelerden geçti: {song_name} ({track_uri})")
        update_time_profile(track_uri, spotify) # Zaman profiline ekle

        song_queue.append({
            'id': track_uri, # URI olarak ekle
            'name': song_name,
            'artist': ', '.join(artist_names),
            'artist_ids': artist_uris, # URI listesi
            'added_by': user_ip,
            'added_at': time.time()
        })
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1 # Kullanıcı limitini artır
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

@app.route('/remove-song/<path:song_id_str>', methods=['POST'])
@admin_login_required
def remove_song(song_id_str):
    """Admin tarafından kuyruktan şarkı kaldırma."""
    global song_queue;
    # Gelen ID'yi URI'ye çevir
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track')
    if not song_uri_to_remove:
        flash(f"Geçersiz şarkı ID formatı: {song_id_str}", "danger")
        return redirect(url_for('admin_panel'))

    logger.debug(f"Kuyruktan kaldırılacak URI: {song_uri_to_remove}")
    original_length = len(song_queue)
    # Kuyruktaki şarkıları URI ile karşılaştırarak kaldır
    song_queue = [song for song in song_queue if song.get('id') != song_uri_to_remove]
    if len(song_queue) < original_length:
        logger.info(f"Şarkı kaldırıldı (Admin): URI={song_uri_to_remove}")
        flash("Şarkı kuyruktan kaldırıldı.", "success")
    else:
        logger.warning(f"Kaldırılacak şarkı bulunamadı: URI={song_uri_to_remove}")
        flash("Şarkı kuyrukta bulunamadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue, user_requests; song_queue = []; user_requests = {}
    logger.info("Kuyruk temizlendi (Admin)."); flash("Kuyruk temizlendi.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/queue')
def view_queue():
    """Kullanıcılar için şarkı kuyruğunu gösterir (Filtrelenmiş)."""
    global spotify_client, song_queue
    currently_playing_info = None
    filtered_queue = []
    spotify = get_spotify_client()

    if spotify:
        # Şu an çalanı al
        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']; is_playing = playback.get('is_playing', False)
                track_uri = item.get('uri')
                if track_uri and track_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(track_uri, spotify)
                    # Sadece izin verilen şarkı gösterilsin
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
            if e.http_status == 401 or e.http_status == 403: spotify_client = None;
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        except Exception as e: logger.error(f"Çalma durumu genel hatası (Kuyruk): {e}", exc_info=True)

        # Kuyruğu filtrele
        for song in song_queue:
            song_uri = song.get('id')
            if song_uri and song_uri.startswith('spotify:track:'):
                is_allowed, _ = check_song_filters(song_uri, spotify)
                if is_allowed:
                    # Sanatçı ID'lerinin URI olduğundan emin ol
                    if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                         song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song['artist_ids']]
                    filtered_queue.append(song)
                else:
                     logger.debug(f"Kuyruk Sayfası: Kuyruktaki şarkı filtrelendi: {song.get('name')} ({song_uri})")
            else:
                 logger.warning(f"Kuyruk Sayfası: Kuyrukta geçersiz şarkı formatı: {song}")

    return render_template('queue.html', queue=filtered_queue, currently_playing_info=currently_playing_info)

@app.route('/api/queue')
def api_get_queue():
    """API: Filtrelenmemiş ham kuyruk verisini döndürür (Admin veya debug için)."""
    global song_queue
    # Güvenlik notu: Bu endpoint'in admin yetkisi gerektirmesi daha iyi olabilir.
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue), 'max_length': settings.get('max_queue_length', 20)})

# --- Ses/Bluetooth API Rotaları (ex.py'yi Çağıran) ---
@app.route('/api/audio-sinks')
@admin_login_required
def api_audio_sinks():
    logger.info("API: Ses sink listesi isteniyor (ex.py aracılığıyla)...")
    result = _run_command(['list_sinks'])
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code

@app.route('/api/set-audio-sink', methods=['POST'])
@admin_login_required
def api_set_audio_sink():
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    sink_identifier = data.get('sink_identifier')
    if sink_identifier is None: return jsonify({'success': False, 'error': 'Sink tanımlayıcısı gerekli'}), 400
    logger.info(f"API: Varsayılan ses sink ayarlama: {sink_identifier} (ex.py)...")
    result = _run_command(['set_audio_sink', '--identifier', str(sink_identifier)])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    # Başarılıysa güncel listeleri de döndür
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'])
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0']) # Sadece bilinenleri listele
         if sinks_list_res.get('success'):
              final_result['sinks'] = sinks_list_res.get('sinks', [])
              final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
         if bt_list_res.get('success'):
              all_bt = bt_list_res.get('devices', [])
              # Sadece eşleşmiş cihazları döndür
              final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
         else: final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code

@app.route('/api/discover-bluetooth')
@admin_login_required
def api_discover_bluetooth():
    scan_duration = request.args.get('duration', BLUETOOTH_SCAN_DURATION, type=int)
    logger.info(f"API: Bluetooth keşfi (Süre: {scan_duration}s, ex.py)...")
    result = _run_command(['discover_bluetooth', '--duration', str(scan_duration)])
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
    result = _run_command(['pair_bluetooth', '--path', device_path])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    # Başarılıysa güncel listeleri de döndür
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'])
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
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
    result = _run_command(['disconnect_bluetooth', '--path', device_path])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    # Başarılıysa güncel listeleri de döndür
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'])
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
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
    result = _run_command(['switch_to_alsa'])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
    # Başarılıysa güncel listeleri de döndür
    if result.get('success'):
         sinks_list_res = _run_command(['list_sinks'])
         bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
         if sinks_list_res.get('success'):
              final_result['sinks'] = sinks_list_res.get('sinks', [])
              final_result['default_sink_name'] = sinks_list_res.get('default_sink_name')
         if bt_list_res.get('success'):
              all_bt = bt_list_res.get('devices', [])
              final_result['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
         else: final_result['bluetooth_devices'] = []
    return jsonify(final_result), status_code

@app.route('/api/restart-spotifyd', methods=['POST'])
@admin_login_required
def api_restart_spotifyd():
    logger.info("API: Spotifyd yeniden başlatma isteği alındı (ex.py aracılığıyla)...")
    success, message = restart_spotifyd()
    status_code = 200 if success else 500
    response_data = {'success': success}
    if success: response_data['message'] = message
    else: response_data['error'] = message
    # Yeniden başlatma sonrası güncel listeleri döndür
    sinks_list_res = _run_command(['list_sinks'])
    bt_list_res = _run_command(['discover_bluetooth', '--duration', '0'])
    if sinks_list_res.get('success'):
        response_data['sinks'] = sinks_list_res.get('sinks', [])
        response_data['default_sink_name'] = sinks_list_res.get('default_sink_name')
    if bt_list_res.get('success'):
        all_bt = bt_list_res.get('devices', [])
        response_data['bluetooth_devices'] = [d for d in all_bt if d.get('paired')]
    else: response_data['bluetooth_devices'] = []
    return jsonify(response_data), status_code

# --- Filtre Yönetimi API Rotaları (Güncellendi) ---
@app.route('/remove-blocked-track', methods=['POST'])
@admin_login_required
def remove_blocked_track():
    track_uri = request.form.get('track_uri')
    global settings
    if track_uri and track_uri in settings.get('track_blacklist', []):
        settings['track_blacklist'].remove(track_uri)
        save_settings(settings)
        flash(f"Şarkı kara listeden çıkarıldı: {track_uri}", "success")
    else:
        flash("Şarkı URI geçersiz veya kara listede değil.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/get-blocked-tracks')
@admin_login_required
def get_blocked_tracks():
    global settings
    spotify = get_spotify_client()
    if not spotify:
        return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 500

    blocked_tracks = []
    for uri in settings.get('track_blacklist', []):
        try:
            track = spotify.track(uri)
            track_name = track.get('name', '?')
            artist_name = ', '.join([a.get('name') for a in track.get('artists', [])])
            blocked_tracks.append({
                'name': track_name,
                'artist': artist_name,
                'uri': uri
            })
        except Exception as e:
            continue  # Hatalı track'leri atla

    return jsonify({'success': True, 'blocked_tracks': blocked_tracks})

@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    """Hızlı engelleme: Sanatçı veya şarkıyı doğrudan kara listeye ekler."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); item_type = data.get('type'); identifier = data.get('identifier')
    # item_type 'song' ise 'track' yap
    actual_item_type = 'track' if item_type in ['song', 'track'] else 'artist'
    if actual_item_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz öğe tipi (artist veya track).'}), 400

    item_uri = _ensure_spotify_uri(identifier, actual_item_type)
    if not item_uri: return jsonify({'success': False, 'error': f"Geçersiz Spotify {actual_item_type} ID/URI."}), 400

    list_key = f"{actual_item_type}_blacklist" # Kara listeye ekle
    try:
        current_settings = load_settings(); target_list = current_settings.get(list_key, [])
        if item_uri not in target_list:
            target_list.append(item_uri); current_settings[list_key] = target_list; save_settings(current_settings)
            settings = current_settings; # Global ayarları güncelle
            logger.info(f"Hızlı Engelleme: '{item_uri}' ({actual_item_type}) kara listeye eklendi.")
            return jsonify({'success': True, 'message': f"'{identifier}' kara listeye eklendi."})
        else:
            logger.info(f"Hızlı Engelleme: '{item_uri}' ({actual_item_type}) zaten kara listede.")
            return jsonify({'success': True, 'message': f"'{identifier}' zaten kara listede."})
    except Exception as e: logger.error(f"Hızlı engelleme hatası ({actual_item_type}, {item_uri}): {e}", exc_info=True); return jsonify({'success': False, 'error': f"Öğe kara listeye eklenirken hata: {e}"}), 500

@app.route('/api/add-to-list', methods=['POST'])
@admin_login_required
def api_add_to_list():
    """Belirtilen filtre listesine öğe ekler."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); filter_type = data.get('filter_type'); list_type = data.get('list_type'); item = data.get('item')

    # filter_type 'song' ise 'track' olarak düzelt
    actual_filter_type = 'track' if filter_type == 'song' else filter_type
    if actual_filter_type not in ['genre', 'artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify({'success': False, 'error': 'Eklenecek öğe boş olamaz.'}), 400

    item = item.strip(); processed_item = None
    if actual_filter_type == 'genre':
        processed_item = item.lower() # Türler küçük harf
    elif actual_filter_type in ['artist', 'track']:
        processed_item = _ensure_spotify_uri(item, actual_filter_type) # URI'ye çevir
        if not processed_item: return jsonify({'success': False, 'error': f"Geçersiz Spotify {actual_filter_type} ID/URI formatı."}), 400

    if not processed_item: return jsonify({'success': False, 'error': 'İşlenecek öğe oluşturulamadı.'}), 500

    list_key = f"{actual_filter_type}_{list_type}" # Doğru anahtarı kullan (örn: track_whitelist)
    try:
        current_settings = load_settings(); target_list = current_settings.get(list_key, [])
        # Listenin None olmadığından emin ol
        if target_list is None: target_list = []

        if processed_item not in target_list:
            target_list.append(processed_item); current_settings[list_key] = target_list; save_settings(current_settings)
            settings = current_settings; # Global ayarları güncelle
            logger.info(f"Listeye Ekleme: '{processed_item}' -> '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item}' listeye eklendi.", 'updated_list': settings[list_key]})
        else:
            logger.info(f"Listeye Ekleme: '{processed_item}' zaten '{list_key}' listesinde.")
            return jsonify({'success': True, 'message': f"'{item}' zaten listede.", 'updated_list': target_list})
    except Exception as e: logger.error(f"Listeye ekleme hatası ({list_key}, {item}): {e}", exc_info=True); return jsonify({'success': False, 'error': f"Listeye öğe eklenirken hata: {e}"}), 500

@app.route('/api/remove-from-list', methods=['POST'])
@admin_login_required
def api_remove_from_list():
    """Belirtilen filtre listesinden öğe çıkarır."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); filter_type = data.get('filter_type'); list_type = data.get('list_type'); item = data.get('item')

    # filter_type 'song' ise 'track' olarak düzelt
    actual_filter_type = 'track' if filter_type == 'song' else filter_type
    if actual_filter_type not in ['genre', 'artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify({'success': False, 'error': 'Çıkarılacak öğe boş olamaz.'}), 400

    item = item.strip(); item_to_remove = None
    if actual_filter_type == 'genre':
        item_to_remove = item.lower()
    elif actual_filter_type in ['artist', 'track']:
        item_to_remove = _ensure_spotify_uri(item, actual_filter_type) # URI'ye çevir

    if not item_to_remove: return jsonify({'success': False, 'error': f"Geçersiz öğe formatı: {item}"}), 400

    list_key = f"{actual_filter_type}_{list_type}" # Doğru anahtarı kullan
    try:
        current_settings = load_settings(); target_list = current_settings.get(list_key, [])
        # Listenin None olmadığından emin ol
        if target_list is None: target_list = []

        if item_to_remove in target_list:
            target_list.remove(item_to_remove); current_settings[list_key] = target_list; save_settings(current_settings)
            settings = current_settings; # Global ayarları güncelle
            logger.info(f"Listeden Çıkarma: '{item_to_remove}' <- '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item}' listeden çıkarıldı.", 'updated_list': target_list})
        else:
            logger.info(f"Listeden Çıkarma: '{item_to_remove}' '{list_key}' listesinde bulunamadı.")
            return jsonify({'success': False, 'error': f"'{item}' listede bulunamadı.", 'updated_list': target_list}), 404
    except Exception as e: logger.error(f"Listeden çıkarma hatası ({list_key}, {item}): {e}", exc_info=True); return jsonify({'success': False, 'error': f"Listeden öğe çıkarılırken hata: {e}"}), 500

@app.route('/api/spotify/genres')
@admin_login_required
def api_spotify_genres():
    """
    Spotify API'den /recommendations/available-genre-seeds endpoint'i ile
    tüm türleri alır ve 'q' query parametresine göre filtreler.
    """
    # Spotify Access Token'ını al
    spotify = get_spotify_client()              
    if not spotify:
        return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503
    
    # get_spotify_client() sadece token döndürüyorsa, token'ı al
    # Örnek: token = spotify.token (veya get_spotify_token())
    # Burada varsayalım get_spotify_token() adında fonksiyon var
    
    try:
        token = load_token()  # Bu fonksiyon senin token alma mekanizmana göre değişir
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(
            "https://api.spotify.com/v1/recommendations/available-genre-seeds",
            headers=headers
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
        logger.error(f"Spotify API HTTP hatası: {http_err}", exc_info=True)
        return jsonify({'success': False, 'error': 'Spotify API çağrısı başarısız oldu.'}), 502
    except Exception as e:
        logger.error(f"Spotify türleri alınırken hata: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Spotify türleri alınamadı.'}), 500

# Spotify ID'lerinden Detayları Getirme API'si (URI Kullanır)
@app.route('/api/spotify/details', methods=['POST'])
@admin_login_required
def api_spotify_details():
    """Verilen Spotify URI listesi için isimleri ve detayları getirir."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    uris = data.get('ids', []) # Frontend 'ids' gönderse de bunlar URI olmalı
    id_type = data.get('type') # 'artist' veya 'track'

    logger.debug(f"Received /api/spotify/details request: type={id_type}, uris_count={len(uris)}")
    if uris: logger.debug(f"First few URIs: {uris[:5]}")

    if not uris or not isinstance(uris, list): return jsonify({'success': False, 'error': 'Geçerli URI listesi gerekli.'}), 400
    # id_type 'song' ise 'track' yap
    actual_id_type = 'track' if id_type == 'song' else id_type
    if actual_id_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz tip (artist veya track).'}), 400

    spotify = get_spotify_client()
    if not spotify: return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503

    details_map = {}
    batch_size = 50
    # Gelen URI'lerin formatını doğrula/temizle
    valid_uris = [_ensure_spotify_uri(uri, actual_id_type) for uri in uris]
    valid_uris = [uri for uri in valid_uris if uri] # None olanları çıkar

    if not valid_uris:
        logger.warning("No valid Spotify URIs found in the request.")
        return jsonify({'success': True, 'details': {}})

    logger.debug(f"Fetching details for {len(valid_uris)} valid URIs (type: {actual_id_type})...")

    try:
        for i in range(0, len(valid_uris), batch_size):
            batch_uris = valid_uris[i:i + batch_size]
            if not batch_uris: continue
            logger.debug(f"Processing batch {i//batch_size + 1} with URIs: {batch_uris}")

            results = None; items = []
            try:
                if actual_id_type == 'artist':
                    results = spotify.artists(batch_uris)
                    items = results.get('artists', []) if results else []
                elif actual_id_type == 'track':
                    results = spotify.tracks(batch_uris, market='TR')
                    items = results.get('tracks', []) if results else []
            except spotipy.SpotifyException as e:
                logger.error(f"Spotify API error during batch fetch (type: {actual_id_type}, batch: {batch_uris}): {e}")
                if e.http_status == 400: logger.error("Likely caused by invalid URIs in the batch."); continue
                else: raise e

            if items:
                for item in items:
                    if item:
                        item_uri = item.get('uri') # URI'yi kullan
                        item_name = item.get('name')
                        if item_uri and item_name:
                            if actual_id_type == 'track':
                                artists = item.get('artists', [])
                                artist_name = ', '.join([a.get('name') for a in artists]) if artists else ''
                                details_map[item_uri] = f"{item_name} - {artist_name}"
                            else: # Artist
                                details_map[item_uri] = item_name
                        else: logger.warning(f"Missing URI or Name in item: {item}")
                    else: logger.warning("Received a null item in the batch response.")
        logger.debug(f"Successfully fetched details for {len(details_map)} items.")
        return jsonify({'success': True, 'details': details_map})

    except spotipy.SpotifyException as e:
         logger.error(f"Spotify API error processing details (type: {actual_id_type}): {e}", exc_info=True)
         return jsonify({'success': False, 'error': f'Spotify API hatası: {e.msg}'}), e.http_status or 500
    except Exception as e:
        logger.error(f"Error fetching Spotify details (type: {actual_id_type}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Spotify detayları alınırken bilinmeyen bir hata oluştu.'}), 500
# Bu örnek, tür filtresinin doğru çalışıp çalışmadığını hızlıca test etmek için minimal bir Flask rotası sunar
@app.route('/debug-genre-filter/<artist_id>')
def debug_genre_filter(artist_id):
    spotify = get_spotify_client()
    if not spotify:
        return jsonify({'error': 'Spotify bağlantısı yok'}), 503

    uri = _ensure_spotify_uri(artist_id, 'artist')
    if not uri:
        return jsonify({'error': 'Geçersiz sanatçı ID'}), 400

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


# --- Arka Plan Şarkı Çalma İş Parçacığı ---
def background_queue_player():
    global auto_advance_enabled
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")
    
    while True:
        try:
            spotify = get_spotify_client()
            if not spotify:
                logger.warning("Spotify bağlantısı yok, 30 saniye bekleniyor...")
                time.sleep(30)
                continue

            current_track = spotify.current_playback()
            if not current_track:
                logger.info("Şu anda çalan şarkı yok.")
                time.sleep(5)
                continue

            # Çalınan şarkıyı kaydet
            if current_track.get('item'):
                track_info = {
                    'id': current_track['item']['id'],
                    'name': current_track['item']['name'],
                    'artist': ', '.join([artist['name'] for artist in current_track['item']['artists']])
                }
                save_played_track(track_info)

            # Şarkı bitti mi kontrol et
            if current_track.get('progress_ms') and current_track.get('item'):
                progress = current_track['progress_ms']
                duration = current_track['item']['duration_ms']
                
                if progress >= duration - 1000 and auto_advance_enabled:
                    logger.info("Şarkı bitti, sıradaki şarkıya geçiliyor...")
                    spotify.next_track()
                    time.sleep(2)  # Yeni şarkının yüklenmesi için bekle
                else:
                    time.sleep(5)
            else:
                time.sleep(5)

        except Exception as e:
            logger.error(f"Arka plan görevinde hata: {str(e)}")
            time.sleep(30)

# --- Uygulama Başlangıcı ---
def check_token_on_startup():
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client()
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Yetkilendirme gerekli olabilir.")

def start_queue_player():
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")

# SQLite veritabanı bağlantısı
DB_PATH = 'musicco.db'

def init_db():
    """SQLite veritabanını başlat ve gerekli tabloları oluştur"""
    try:
        logger.info("Veritabanı başlatılıyor...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # played_tracks tablosunu oluştur
        cursor.execute('''CREATE TABLE IF NOT EXISTS played_tracks
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     track_id TEXT,
                     track_name TEXT,
                     artist_name TEXT,
                     genre TEXT,
                     played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        conn.commit()
        logger.info("Veritabanı başarıyla başlatıldı")
    except sqlite3.Error as e:
        logging.error(f"Veritabanı başlatma hatası: {e}")
    finally:
        if conn:
            conn.close()

def save_played_track(track_info):
    """Çalınan şarkıyı veritabanına kaydet"""
    try:
        # Son çalınan şarkıyı kontrol et
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        
        # Son çalınan şarkıyı kontrol et
        cursor.execute('''
            SELECT track_id, played_at FROM played_tracks 
            ORDER BY played_at DESC LIMIT 1
        ''')
        last_track = cursor.fetchone()
        
        # Eğer son çalınan şarkı aynıysa ve son 5 dakika içinde çalındıysa kaydetme
        if last_track and last_track[0] == track_info.get('id'):
            last_played_time = datetime.strptime(last_track[1], '%Y-%m-%d %H:%M:%S')
            time_diff = datetime.now() - last_played_time
            if time_diff.total_seconds() < 300:  # 5 dakika
                logger.info("Bu şarkı zaten son 5 dakika içinde kaydedilmiş, tekrar kaydedilmiyor.")
                return
        
        # Yeni şarkıyı kaydet
        cursor.execute('''
            INSERT INTO played_tracks (track_id, track_name, artist_name)
            VALUES (?, ?, ?)
        ''', (
            track_info.get('id', ''),
            track_info.get('name', 'Bilinmeyen'),
            track_info.get('artist', 'Bilinmeyen')
        ))
        
        conn.commit()
        logger.info("Şarkı başarıyla kaydedildi.")
        
    except sqlite3.Error as e:
        logger.error(f"Şarkı kaydedilirken hata oluştu: {str(e)}")
        # Tablo yoksa oluşturmayı dene
        if "no such table" in str(e).lower():
            logger.info("Tablo bulunamadı, yeniden oluşturuluyor...")
            init_db()
            # Tekrar kaydetmeyi dene
            try:
                cursor.execute('''
                    INSERT INTO played_tracks (track_id, track_name, artist_name)
                    VALUES (?, ?, ?)
                ''', (
                    track_info.get('id', ''),
                    track_info.get('name', 'Bilinmeyen'),
                    track_info.get('artist', 'Bilinmeyen')
                ))
                conn.commit()
                logger.info("Şarkı başarıyla kaydedildi (ikinci deneme).")
            except sqlite3.Error as e2:
                logger.error(f"İkinci kaydetme denemesi de başarısız: {str(e2)}")
    finally:
        if conn:
            conn.close()

@app.route('/api/played-tracks')
@admin_login_required
def get_played_tracks():
    """Son çalınan şarkıları getir"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''SELECT track_name, artist_name, genre, played_at 
                         FROM played_tracks 
                         ORDER BY played_at DESC LIMIT 100''')
        tracks = cursor.fetchall()
        return jsonify({
            'success': True,
            'tracks': [{
                'name': track[0],
                'artist': track[1],
                'genre': track[2],
                'played_at': track[3]
            } for track in tracks]
        })
    except sqlite3.Error as e:
        logging.error(f"Çalınan şarkıları getirme hatası: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("Mekan Müzik Sistemi başlatılıyor...")
    logger.info("=================================================")

    # Veritabanını başlat
    init_db()

    # Token kontrolü
    check_token_on_startup()

    # Arka plan görevini başlat
    start_queue_player()

    port = int(os.environ.get('PORT', 9187))
    logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişilebilir.")
    logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişilebilir.")
    app.run(host='0.0.0.0', port=port, debug=False)

