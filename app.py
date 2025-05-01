#şarkı blackliste ekleme # <-- This comment seems irrelevant now but kept as original
# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse ve URI kontrolü için
import subprocess # ex.py ve spotifyd için
from functools import wraps
# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi
from threading import Lock

# --- Yapılandırılabilir Ayarlar ---
# !!! BU BİLGİLERİ KENDİ SPOTIFY DEVELOPER BİLGİLERİNİZLE DEĞİŞTİRİN !!!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78' # ÖRNEK - DEĞİŞTİR
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426' # ÖRNEK - DEĞİŞTİR
# !!! BU URI'NIN SPOTIFY DEVELOPER DASHBOARD'DAKİ REDIRECT URI İLE AYNI OLDUĞUNDAN EMİN OLUN !!!
SPOTIFY_REDIRECT_URI = 'http://100.81.225.104:8080/callback' # ÖRNEK - DEĞİŞTİR
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

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

# --- Global Değişkenler ---
queue = []  # Çalma kuyruğu
queue_lock = Lock()  # Kuyruk için thread-safe kilit

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
        'genre_filter_mode': 'blacklist', 'artist_filter_mode': 'blacklist', # Removed track_filter_mode
        'genre_blacklist': [], 'genre_whitelist': [],
        'artist_blacklist': [], 'artist_whitelist': [], # Bunlar URI listeleri olmalı
        # Removed track_blacklist, track_whitelist
    }
    settings_to_use = default_settings.copy() # Önce varsayılanı al
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: loaded = json.load(f)

            # Remove old track/song related keys if they exist
            removed_keys = ['song_blacklist', 'song_whitelist', 'song_filter_mode',
                            'track_blacklist', 'track_whitelist', 'track_filter_mode']
            for key in removed_keys:
                if key in loaded:
                    del loaded[key]
                    logger.info(f"Eski/kaldırılmış ayar '{key}' ayar dosyasından silindi.")

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
            # Only check artist lists now
            for key in ['artist_blacklist', 'artist_whitelist']:
                if key in settings_to_use:
                    item_type = 'artist'
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

        # Sanatçı listelerini URI formatına çevir, temizle ve sırala (Only Artist)
        for key in ['artist_blacklist', 'artist_whitelist']:
             if key in settings_to_save:
                  cleaned_uris = set()
                  item_type = 'artist'
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

        # Remove track/song related settings before saving
        removed_keys = ['song_blacklist', 'song_whitelist', 'song_filter_mode',
                        'track_blacklist', 'track_whitelist', 'track_filter_mode']
        for key in removed_keys:
            if key in settings_to_save:
                del settings_to_save[key]

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
                    is_allowed, _ = check_filters(suggested_uri, spotify) # <<-- Filtre kontrolü (check_filters olarak değiştirildi)
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
# Renamed from check_song_filters to check_filters as it now only checks artist and genre
def check_filters(track_uri, spotify_client):
    """
    Verilen track_uri'nin SANATÇI ve TÜR filtrelerine uyup uymadığını kontrol eder.
    ŞARKI filtresi kaldırılmıştır.
    URI formatında ('spotify:track:...') girdi bekler.
    Dönüş: (bool: is_allowed, str: reason)
    """
    global settings
    if not spotify_client: return False, "Spotify bağlantısı yok."
    if not track_uri or not isinstance(track_uri, str) or not track_uri.startswith('spotify:track:'):
        logger.error(f"check_filters: Geçersiz track_uri formatı: {track_uri}")
        return False, f"Geçersiz şarkı URI formatı: {track_uri}"

    logger.debug(f"Filtre kontrolü başlatılıyor (Sanatçı/Tür): {track_uri}")
    try:
        # 1. Şarkı Bilgilerini Al (Sanatçı ve Tür için gerekli)
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
        artist_blacklist_uris = settings.get('artist_blacklist', [])
        artist_whitelist_uris = settings.get('artist_whitelist', [])
        genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
        genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]

        # 2. Şarkı Filtresi Kontrolü <<-- BU BÖLÜM KALDIRILDI

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

        # 5. Tüm (Kalan) Filtrelerden Geçti
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
    """
    Admin panelini gösterir.
    """
    try:
        # Spotify bağlantısını kontrol et
        spotify = get_spotify_client()
        spotify_authenticated = bool(spotify)
        
        # Şu an çalan şarkı bilgilerini al
        currently_playing_info = None
        if spotify_authenticated:
            try:
                current = spotify.current_playback()
                if current and current.get('item'):
                    track = current['item']
                    currently_playing_info = {
                        'name': track['name'],
                        'artist': track['artists'][0]['name'] if track['artists'] else 'Bilinmeyen Sanatçı',
                        'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                        'is_playing': current.get('is_playing', False)
                    }
            except Exception as e:
                logger.error(f"Şu an çalan şarkı bilgileri alınırken hata: {str(e)}")

        # Kuyruğu güvenli bir şekilde al
        with queue_lock:
            queue_copy = queue.copy()  # Kuyruğun bir kopyasını al
            logger.debug(f"Admin panel için kuyruk yüklendi: {queue_copy}")

        # Ayarları yükle
        settings = load_settings()
        
        return render_template('admin_panel.html',
                             spotify_authenticated=spotify_authenticated,
                             currently_playing_info=currently_playing_info,
                             queue=queue_copy,
                             settings=settings)
    except Exception as e:
        logger.error(f"Admin panel yüklenirken hata: {str(e)}")
        flash('Panel yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('admin'))

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
    global auto_advance_enabled; spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        logger.info(f"Admin: Sürdürme isteği (Cihaz: {active_spotify_connect_device_id or '?'}).")
        spotify.start_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = True; logger.info("Admin: Otomatik geçiş SÜRDÜRÜLDÜ.")
        flash('Müzik sürdürüldü ve otomatik sıraya geçiş açıldı.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify sürdürme hatası: {e}")
        if e.http_status == 401 or e.http_status == 403: flash('Spotify yetkilendirme hatası.', 'danger');
        global spotify_client; spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404: flash(f'Sürdürme hatası: Cihaz bulunamadı ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE': flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        elif e.reason == 'PREMIUM_REQUIRED': flash('Bu işlem için Spotify Premium gerekli.', 'warning')
        else: flash(f'Spotify sürdürme hatası: {e.msg}', 'danger')
    except Exception as e: logger.error(f"Sürdürme sırasında genel hata: {e}", exc_info=True); flash('Müzik sürdürülürken bir hata oluştu.', 'danger')
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
        # Şarkı filtresi modu kaldırıldı ('song_filter_mode' veya 'track_filter_mode' işlenmiyor)
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

# GÜNCELLENDİ: /search endpoint'i filtrelemeyi uygular (Şarkı filtresi hariç) ve URI kullanır
@app.route('/search', methods=['POST'])
def search():
    """Spotify'da arama yapar ve sonuçları aktif (Sanatçı/Tür) filtrelere göre süzer."""
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
                # Şarkı filtresini değil, sadece sanatçı/tür filtresini URI ile kontrol et
                is_allowed, reason = check_filters(item_uri, spotify) # <<-- check_filters kullan
            elif search_type == 'artist':
                # Sanatçı ve Tür filtresini URI ile kontrol et
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
    """Admin tarafından şarkı ekleme (Sadece Sanatçı/Tür Filtrelerini atlar)."""
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

        # Admin eklemesi için filtre kontrolü yapmaya gerek yok
        # is_allowed, reason = check_filters(track_uri, spotify)
        # if not is_allowed:
        #     flash(f"Engellendi ({reason}): {song_info.get('name')}", "warning")
        #     return redirect(url_for('admin_panel'))

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
    """
    Kuyruğa yeni şarkı ekler.
    """
    try:
        data = request.get_json()
        if not data or 'track_id' not in data:
            return jsonify({'success': False, 'error': 'Şarkı ID\'si gerekli'}), 400

        track_id = data['track_id']
        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı kurulamadı'}), 500

        # Şarkı ID'sini Spotify URI formatına dönüştür
        track_uri = _ensure_spotify_uri(track_id, 'track')
        if not track_uri:
            return jsonify({'success': False, 'error': 'Geçersiz şarkı ID\'si'}), 400

        # Şarkı detaylarını al
        try:
            track_info = spotify.track(track_uri)
            if not track_info:
                return jsonify({'success': False, 'error': 'Şarkı bulunamadı'}), 404

            # Şarkıyı kuyruğa ekle
            with queue_lock:
                if track_uri not in queue:  # Tekrar eklemeyi önle
                    queue.append(track_uri)
                    logger.info(f"Şarkı kuyruğa eklendi: {track_uri}")
                    
                    # Şarkı bilgilerini hazırla
                    track_data = {
                        'id': track_uri,
                        'name': track_info['name'],
                        'artist': track_info['artists'][0]['name'] if track_info['artists'] else 'Bilinmeyen Sanatçı',
                        'artist_id': track_info['artists'][0]['id'] if track_info['artists'] else None,
                        'image_url': track_info['album']['images'][0]['url'] if track_info['album']['images'] else None
                    }
                    
                    return jsonify({
                        'success': True,
                        'message': 'Şarkı kuyruğa eklendi',
                        'track': track_data
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Bu şarkı zaten kuyrukta'
                    }), 400

        except Exception as e:
            logger.error(f"Şarkı detayları alınırken hata: {str(e)}")
            return jsonify({'success': False, 'error': f'Şarkı detayları alınamadı: {str(e)}'}), 500

    except Exception as e:
        logger.error(f"Kuyruğa şarkı eklenirken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
    """Kullanıcılar için şarkı kuyruğunu gösterir (Sanatçı/Tür Filtrelenmiş)."""
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
                    is_allowed, _ = check_filters(track_uri, spotify) # <<-- check_filters kullan
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
                is_allowed, _ = check_filters(song_uri, spotify) # <<-- check_filters kullan
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

@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    try:
        app.logger.info("Engelleme isteği alındı")
        data = request.get_json()
        app.logger.info(f"Gelen veri: {data}")
        
        if not data or 'type' not in data or 'identifier' not in data:
            app.logger.error("Eksik parametreler")
            return jsonify({'success': False, 'error': 'Eksik parametreler'}), 400

        item_type = data['type']
        identifier = data['identifier']
        app.logger.info(f"İşlenecek veri - Tip: {item_type}, ID: {identifier}")
        
        # Spotify bağlantısını kontrol et
        spotify = get_spotify_client()
        if not spotify:
            app.logger.error("Spotify bağlantısı yok")
            return jsonify({'success': False, 'error': 'Spotify bağlantısı yok'}), 401

        # Sanatçı türünü engelleme
        if item_type == 'genre':
            try:
                # Sanatçı URI'sinden ID'yi al
                artist_id = identifier.replace('spotify:artist:', '')
                
                # Sanatçının türlerini al
                artist_info = spotify.artist(artist_id)
                if not artist_info or 'genres' not in artist_info:
                    return jsonify({'success': False, 'error': 'Sanatçı bilgileri alınamadı'}), 404

                genres = artist_info['genres']
                if not genres:
                    return jsonify({'success': False, 'error': 'Sanatçının türü bulunamadı'}), 404

                # Kara listeye ekle
                settings = load_settings()
                if 'genre_blacklist' not in settings:
                    settings['genre_blacklist'] = []

                added_genres = []
                for genre in genres:
                    if genre not in settings['genre_blacklist']:
                        settings['genre_blacklist'].append(genre)
                        added_genres.append(genre)

                if not added_genres:
                    return jsonify({'success': False, 'error': 'Tüm türler zaten engellenmiş'}), 400

                save_settings(settings)
                return jsonify({
                    'success': True,
                    'message': f'{len(added_genres)} tür engellendi: {", ".join(added_genres)}',
                    'updated_list': settings['genre_blacklist']
                })

            except Exception as e:
                app.logger.error(f"Sanatçı türü engelleme hatası: {str(e)}")
                return jsonify({'success': False, 'error': f'Sanatçı türü engellenirken hata: {str(e)}'}), 500

        # Sanatçı engelleme
        elif item_type == 'artist':
            try:
                # Sanatçı URI'sinden ID'yi al
                artist_id = identifier.replace('spotify:artist:', '')
                
                # Sanatçı bilgilerini al
                artist_info = spotify.artist(artist_id)
                if not artist_info:
                    return jsonify({'success': False, 'error': 'Sanatçı bulunamadı'}), 404

                # Kara listeye ekle
                settings = load_settings()
                if 'artist_blacklist' not in settings:
                    settings['artist_blacklist'] = []

                if identifier in settings['artist_blacklist']:
                    return jsonify({'success': False, 'error': 'Sanatçı zaten engellenmiş'}), 400

                settings['artist_blacklist'].append(identifier)
                save_settings(settings)

                return jsonify({
                    'success': True,
                    'message': f'Sanatçı engellendi: {artist_info["name"]}',
                    'updated_list': settings['artist_blacklist']
                })

            except Exception as e:
                app.logger.error(f"Sanatçı engelleme hatası: {str(e)}")
                return jsonify({'success': False, 'error': f'Sanatçı engellenirken hata: {str(e)}'}), 500

        else:
            return jsonify({'success': False, 'error': 'Geçersiz öğe türü'}), 400

    except Exception as e:
        app.logger.error(f"Engelleme işlemi hatası: {str(e)}")
        return jsonify({'success': False, 'error': f'Engelleme işlemi sırasında hata: {str(e)}'}), 500

@app.route('/api/add-to-list', methods=['POST'])
@admin_login_required
def api_add_to_list():
    """Belirtilen filtre listesine öğe ekler (Sadece Tür/Sanatçı)."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); filter_type = data.get('filter_type'); list_type = data.get('list_type'); item = data.get('item')

    # filter_type 'song' ise hata ver
    if filter_type == 'song':
        return jsonify({'success': False, 'error': 'Şarkı filtreleme kaldırıldı.'}), 400
    actual_filter_type = filter_type # 'genre' veya 'artist' olmalı
    if actual_filter_type not in ['genre', 'artist']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi (genre veya artist).'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify({'success': False, 'error': 'Eklenecek öğe boş olamaz.'}), 400

    item = item.strip(); processed_item = None
    if actual_filter_type == 'genre':
        processed_item = item.lower() # Türler küçük harf
    elif actual_filter_type == 'artist':
        processed_item = _ensure_spotify_uri(item, actual_filter_type) # URI'ye çevir
        if not processed_item: return jsonify({'success': False, 'error': f"Geçersiz Spotify {actual_filter_type} ID/URI formatı."}), 400

    if not processed_item: return jsonify({'success': False, 'error': 'İşlenecek öğe oluşturulamadı.'}), 500

    list_key = f"{actual_filter_type}_{list_type}" # Doğru anahtarı kullan (örn: artist_whitelist)
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
    """Belirtilen filtre listesinden öğe çıkarır (Sadece Tür/Sanatçı)."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); filter_type = data.get('filter_type'); list_type = data.get('list_type'); item = data.get('item')

    # filter_type 'song' ise hata ver
    if filter_type == 'song':
        return jsonify({'success': False, 'error': 'Şarkı filtreleme kaldırıldı.'}), 400
    actual_filter_type = filter_type # 'genre' veya 'artist' olmalı
    if actual_filter_type not in ['genre', 'artist']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi (genre veya artist).'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify({'success': False, 'error': 'Çıkarılacak öğe boş olamaz.'}), 400

    item = item.strip(); item_to_remove = None
    if actual_filter_type == 'genre':
        item_to_remove = item.lower()
    elif actual_filter_type == 'artist':
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

# Spotify Türlerini Getirme API'si
@app.route('/api/spotify/genres')
@admin_login_required
def api_spotify_genres():
    """Spotify'dan mevcut öneri türlerini (genre seeds) alır."""
    spotify = get_spotify_client()
    if not spotify:
        return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503
    try:
        genres = spotify.recommendation_genre_seeds()
        return jsonify({'success': True, 'genres': genres.get('genres', [])})
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

    # id_type 'song' ise 'track' yap (track detayları hala çekilebilir)
    actual_id_type = 'track' if id_type == 'song' else id_type
    if actual_id_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz tip (artist veya track).'}), 400

    logger.debug(f"Received /api/spotify/details request: type={actual_id_type}, uris_count={len(uris)}")
    if uris: logger.debug(f"First few URIs: {uris[:5]}")

    if not uris or not isinstance(uris, list): return jsonify({'success': False, 'error': 'Geçerli URI listesi gerekli.'}), 400

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


# --- Arka Plan Şarkı Çalma İş Parçacığı ---
def background_queue_player():
    global spotify_client, song_queue, user_requests, settings, auto_advance_enabled
    logger.info("Arka plan şarkı çalma/öneri görevi başlatılıyor...")
    last_played_song_uri = None; last_suggested_song_uri = None
    while True:
        try:
            spotify = get_spotify_client()
            active_spotify_connect_device_id = settings.get('active_device_id')
            if not spotify or not active_spotify_connect_device_id: time.sleep(10); continue
            current_playback = None
            try: current_playback = spotify.current_playback(additional_types='track,episode', market='TR')
            except spotipy.SpotifyException as pb_err:
                logger.error(f"Arka plan: Playback kontrol hatası: {pb_err}")
                if pb_err.http_status == 401 or pb_err.http_status == 403: spotify_client = None;
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                time.sleep(10); continue
            except Exception as pb_err: logger.error(f"Arka plan: Playback kontrol genel hata: {pb_err}", exc_info=True); time.sleep(15); continue

            is_playing_now = False; current_track_uri_now = None
            if current_playback:
                is_playing_now = current_playback.get('is_playing', False); item = current_playback.get('item')
                current_track_uri_now = item.get('uri') if item else None

            # Otomatik ilerleme aktifse ve müzik çalmıyorsa
            if auto_advance_enabled and not is_playing_now:
                # Önce kuyruğu kontrol et
                if song_queue:
                    logger.info(f"Arka plan: Çalma durdu, otomatik ilerleme aktif. Kuyruktan çalınıyor...")
                    next_song = song_queue.pop(0) # Kuyruktan ilk şarkıyı al
                    next_song_uri = next_song.get('id') # Kuyrukta 'id' olarak URI tutuluyor

                    if not next_song_uri or not next_song_uri.startswith('spotify:track:'):
                        logger.warning(f"Arka plan: Kuyrukta geçersiz URI formatı: {next_song_uri}"); continue

                    # Aynı şarkıyı tekrar çalmayı önle (nadiren olabilir)
                    if next_song_uri == last_played_song_uri:
                        logger.debug(f"Şarkı ({next_song.get('name')}) zaten son çalınandı, atlanıyor."); last_played_song_uri = None; time.sleep(1); continue

                    logger.info(f"Arka plan: Çalınacak: {next_song.get('name')} ({next_song_uri})")
                    try:
                        # Şarkıyı çalmaya başla
                        spotify.start_playback(device_id=active_spotify_connect_device_id, uris=[next_song_uri])
                        logger.info(f"===> Şarkı çalmaya başlandı: {next_song.get('name')}")
                        last_played_song_uri = next_song_uri; last_suggested_song_uri = None # Son öneriyi sıfırla

                        # Kullanıcı limitini azalt (eğer kullanıcı eklediyse)
                        user_ip = next_song.get('added_by')
                        if user_ip and user_ip != 'admin' and user_ip != 'auto-time':
                             user_requests[user_ip] = max(0, user_requests.get(user_ip, 0) - 1)
                             logger.debug(f"Kullanıcı {user_ip} limiti azaltıldı: {user_requests.get(user_ip)}")
                        time.sleep(1); continue # Bir sonraki döngüye geç

                    except spotipy.SpotifyException as start_err:
                        logger.error(f"Arka plan: Şarkı başlatılamadı ({next_song_uri}): {start_err}")
                        song_queue.insert(0, next_song) # Başlatılamayan şarkıyı başa ekle
                        if start_err.http_status == 401 or start_err.http_status == 403: spotify_client = None;
                        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                        elif start_err.http_status == 404 and 'device_id' in str(start_err).lower():
                             logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device_id}) bulunamadı.");
                             settings['active_device_id'] = None; save_settings(settings)
                        elif start_err.http_status == 400:
                             logger.error(f"Arka plan: Geçersiz URI nedeniyle şarkı başlatılamadı: {next_song_uri}")
                        time.sleep(5); continue
                    except Exception as start_err: logger.error(f"Arka plan: Şarkı başlatılırken genel hata ({next_song_uri}): {start_err}", exc_info=True); song_queue.insert(0, next_song); time.sleep(10); continue
                # Kuyruk boşsa öneri yapmayı dene
                else:
                    suggested_song_info = suggest_song_for_time(spotify)
                    if suggested_song_info and suggested_song_info.get('id') != last_suggested_song_uri:
                        suggested_uri = suggested_song_info['id']
                        logger.info(f"Otomatik öneri bulundu: {suggested_song_info['name']} ({suggested_uri})")
                        # Önerilen şarkıyı kuyruğa ekle (filtre kontrolü suggest_song_for_time içinde yapıldı)
                        song_queue.append({
                            'id': suggested_uri,
                            'name': suggested_song_info['name'],
                            'artist': suggested_song_info.get('artist', '?'),
                            'artist_ids': suggested_song_info.get('artist_ids', []),
                            'added_by': 'auto-time',
                            'added_at': time.time()
                        })
                        last_suggested_song_uri = suggested_uri # Tekrar aynı öneriyi eklememek için
                        logger.info(f"Otomatik öneri kuyruğa eklendi: {suggested_song_info['name']}")
                    else:
                        # Uygun öneri yoksa veya son öneriyle aynıysa bekle
                        time.sleep(15) # Daha uzun bekleme süresi
            # Müzik zaten çalıyorsa
            elif is_playing_now:
                 if current_track_uri_now and current_track_uri_now != last_played_song_uri:
                     logger.debug(f"Arka plan: Yeni şarkı algılandı: {current_track_uri_now}");
                     last_played_song_uri = current_track_uri_now; last_suggested_song_uri = None # Son öneriyi sıfırla
                     # Çalan şarkıyı zaman profiline ekle
                     update_time_profile(current_track_uri_now, spotify)
                 time.sleep(5) # Normal kontrol aralığı
            # Otomatik ilerleme kapalıysa ve müzik çalmıyorsa
            else:
                 time.sleep(10) # Daha seyrek kontrol et

        except Exception as loop_err: logger.error(f"Arka plan döngü hatası: {loop_err}", exc_info=True); time.sleep(15)

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

@app.route('/remove-from-queue/<path:track_id>', methods=['POST'])
@admin_login_required
def remove_from_queue(track_id):
    """
    Kuyruktan belirtilen şarkıyı kaldırır.
    """
    try:
        # Şarkı ID'sini Spotify URI formatına dönüştür
        track_uri = _ensure_spotify_uri(track_id, 'track')
        if not track_uri:
            return jsonify({'success': False, 'error': 'Geçersiz şarkı ID\'si'}), 400

        # Kuyruktan şarkıyı kaldır
        with queue_lock:
            if track_uri in queue:
                queue.remove(track_uri)
                logger.info(f"Şarkı kuyruktan kaldırıldı: {track_uri}")
                return jsonify({'success': True, 'message': 'Şarkı kuyruktan kaldırıldı'})
            else:
                return jsonify({'success': False, 'error': 'Şarkı kuyrukta bulunamadı'}), 404

    except Exception as e:
        logger.error(f"Kuyruktan şarkı kaldırılırken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/spotify-devices')
@admin_login_required
def api_spotify_devices():
    """
    Kullanılabilir Spotify Connect cihazlarını listeler.
    """
    try:
        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı kurulamadı'}), 500

        devices = spotify.devices()
        if not devices or 'devices' not in devices:
            return jsonify({'success': False, 'error': 'Cihaz listesi alınamadı'}), 500

        # Aktif cihaz ID'sini al
        active_device_id = None
        for device in devices['devices']:
            if device.get('is_active'):
                active_device_id = device['id']
                break

        return jsonify({
            'success': True,
            'devices': devices['devices'],
            'active_device_id': active_device_id
        })

    except Exception as e:
        logger.error(f"Spotify cihazları alınırken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/transfer-playback', methods=['POST'])
@admin_login_required
def api_transfer_playback():
    """
    Çalma işlemini belirtilen cihaza aktarır.
    """
    try:
        data = request.get_json()
        if not data or 'device_id' not in data:
            return jsonify({'success': False, 'error': 'Cihaz ID\'si gerekli'}), 400

        device_id = data['device_id']
        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı kurulamadı'}), 500

        # Çalma işlemini aktar
        spotify.transfer_playback(device_id=device_id)
        logger.info(f"Çalma işlemi cihaza aktarıldı: {device_id}")

        return jsonify({
            'success': True,
            'message': 'Çalma işlemi başarıyla aktarıldı'
        })

    except Exception as e:
        logger.error(f"Çalma işlemi aktarılırken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/play-next', methods=['POST'])
@admin_login_required
def api_play_next():
    """
    Sıradaki şarkıyı çalar.
    """
    try:
        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı kurulamadı'}), 500

        # Kuyruktan ilk şarkıyı al
        with queue_lock:
            logger.debug(f"Mevcut kuyruk: {queue}")  # Debug için kuyruk içeriğini logla
            if not queue:
                logger.warning("Kuyruk boş olduğu için şarkı çalınamadı")
                return jsonify({'success': False, 'error': 'Kuyrukta şarkı yok'}), 404
            
            track_uri = queue[0]
            logger.info(f"Çalınacak şarkı URI'si: {track_uri}")
            queue.pop(0)  # Şarkıyı kuyruktan kaldır
            logger.debug(f"Kuyruktan çıkarıldıktan sonra kalan şarkılar: {queue}")

        # Şarkıyı çal
        try:
            spotify.start_playback(uris=[track_uri])
            logger.info(f"Sıradaki şarkı çalmaya başladı: {track_uri}")
        except Exception as playback_error:
            logger.error(f"Şarkı çalınırken hata: {str(playback_error)}")
            # Şarkıyı tekrar kuyruğa ekle
            with queue_lock:
                queue.insert(0, track_uri)
            return jsonify({'success': False, 'error': f'Şarkı çalınamadı: {str(playback_error)}'}), 500

        return jsonify({
            'success': True,
            'message': 'Sıradaki şarkı çalmaya başladı'
        })

    except Exception as e:
        logger.error(f"Sıradaki şarkı çalınırken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("=================================================")
    logger.info(f"Ayarlar Yüklendi: {SETTINGS_FILE}")
    logger.info(f"Harici betik yolu: {EX_SCRIPT_PATH}")

    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.error("LÜTFEN app.py dosyasında Spotify API bilgilerinizi ayarlayın!")
    else:
         logger.info("Spotify API bilgileri app.py içinde tanımlı görünüyor.")
         logger.info(f"Kullanılacak Redirect URI: {SPOTIFY_REDIRECT_URI}")
         logger.info("!!! BU URI'nin Spotify Developer Dashboard'da kayıtlı olduğundan emin olun !!!")

    if not os.path.exists(EX_SCRIPT_PATH):
        logger.error(f"Kritik Hata: Harici betik '{EX_SCRIPT_PATH}' bulunamadı!")
    else:
         logger.info(f"'{EX_SCRIPT_PATH}' betiği test ediliyor...")
         test_result = _run_command(['list_sinks'], timeout=10)
         if test_result.get('success'): logger.info(f"'{EX_SCRIPT_PATH}' betiği başarıyla çalıştı.")
         else: logger.warning(f"'{EX_SCRIPT_PATH}' betiği hatası: {test_result.get('error')}.")

    check_token_on_startup()
    start_queue_player()

    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişilebilir.")
    logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişilebilir.")

    # debug=True geliştirme sırasında kullanışlıdır, ancak production'da False yapın.
    # use_reloader=False arka plan thread'inin tekrar başlamasını önler.
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)