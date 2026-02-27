import os
import sys
import platform
import json
import threading
import time
import logging
import re
import io
import base64
from functools import wraps
import requests
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash, send_file
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback
import random
import socket
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import generate_csrf
import qrcode
from flask_socketio import SocketIO, emit

# Abonelik sistemi modülleri
from models import init_db, Venue, SubscriptionPlan, VenueSpotifyData, VenueQueue, VenueSettings, SongRequestAnalytics
 
# --- Platform Tespiti ---
IS_WINDOWS = platform.system() == 'Windows'
PYTHON_CMD = 'python' if IS_WINDOWS else 'python3'

# --- Yapılandırılabilir Ayarlar ---
# Spotify Developer Dashboard üzerinden alınan bilgiler
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID', '332e5f2c9fe44d9b9ef19c49d0caeb78')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET', 'bbb19ad9c7d04d738f61cd0bd4f47426')
# Production'da bu değeri ortam değişkeninden alın
SPOTIFY_REDIRECT_URI = os.environ.get('SPOTIFY_REDIRECT_URI', 'http://localhost:9187/callback')
SPOTIFY_SCOPE = 'user-read-playback-state user-read-private user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
# Kullanıcı arayüzünde gösterilecek varsayılan türler (opsiyonel)
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
# ---------------------------------

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
# --- Güvenlik Olayları için Özel Logger ---
waf_logger = logging.getLogger('WAF')
waf_logger.setLevel(logging.WARNING)
# Sadece güvenlik olaylarını 'security_events.log' dosyasına yaz
waf_handler = logging.FileHandler('security_events.log')
waf_formatter = logging.Formatter('%(asctime)s - %(levelname)s - IP: %(ip)s - Rule: %(rule)s - Path: %(path)s - Data: %(data)s')
waf_handler.setFormatter(waf_formatter)
waf_logger.addHandler(waf_handler)
# ----------------------------------------
logger = logging.getLogger(__name__)

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
app.jinja_env.globals['ALLOWED_GENRES'] = ALLOWED_GENRES

# Production'da subdomain routing için SERVER_NAME ayarlayın (opsiyonel)
# Örn: MAIN_DOMAIN=qubeat.com
if os.environ.get('MAIN_DOMAIN'):
    app.config['SERVER_NAME'] = os.environ.get('MAIN_DOMAIN')

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)
csrf = CSRFProtect(app)

# SocketIO for real-time updates
socketio = SocketIO(app, cors_allowed_origins="*")

# Flask g objesi için import
from flask import g

@app.context_processor
def inject_csrf():
    # Şablonlarda {{ csrf_token() }} olarak kullanılabilir
    return dict(csrf_token=generate_csrf)

@app.context_processor
def inject_venue():
    """Şablonlara venue bilgisini enjekte eder"""
    return dict(
        current_venue=getattr(g, 'venue', None),
        current_venue_id=getattr(g, 'venue_id', None)
    )

# --- Subdomain Middleware ---
@app.before_request
def detect_venue_from_subdomain():
    """Her istekte subdomain'den venue'yu tespit eder"""
    host = request.host.split(':')[0]  # Port'u kaldır
    parts = host.split('.')
    
    # Subdomain varsa (örn: demo.qubeat.local -> ['demo', 'qubeat', 'local'])
    if len(parts) > 2:
        subdomain = parts[0]
        # Ana domain veya www değilse venue ara
        if subdomain not in ['www', 'qubeat', 'admin']:
            venue = Venue.get_by_slug(subdomain)
            if venue:
                g.venue = venue
                g.venue_id = venue.id
                logger.debug(f"Subdomain tespit edildi: {subdomain} -> Venue ID: {venue.id}")
            else:
                logger.warning(f"Bilinmeyen subdomain: {subdomain}")

# --- WAF Benzeri Ara Katman (Middleware) ---
@app.before_request
def waf_middleware():
    # Güvenlik kuralları (Regex kalıpları)
    # Bu listeyi ihtiyaçlarınıza göre genişletebilirsiniz.
    rules = [
        {'name': 'SQL_INJECTION_1', 'pattern': r"(\b(union|select|insert|drop|update|delete|from|where)\b.*?--|\' OR \'1\'=\'1\')"},
        {'name': 'SQL_INJECTION_2', 'pattern': r"(\b(exec|execute|char|cast|convert)\b.*?--)"},
        {'name': 'XSS_SCRIPT_TAG', 'pattern': r"<script.*?>.*?</script>"},
        {'name': 'XSS_ON_EVENT', 'pattern': r"onerror=|onload=|onmouseover=|onclick="},
        {'name': 'PATH_TRAVERSAL', 'pattern': r"(\.\./|\.\.\\)"},
        {'name': 'COMMAND_INJECTION', 'pattern': r"(\b(cat|ls|whoami|uname|id|pwd|wget|curl)\s)"},
        {'name': 'MALICIOUS_USER_AGENT', 'pattern': r"(sqlmap|nmap|nikto|wpscan|nessus)"}
    ]

    # İncelenecek veri kaynakları
    user_ip = request.remote_addr
    path_and_query = request.path  # Sadece path'i al, query string'i alma
    user_agent = request.headers.get('User-Agent', '')
    
    # POST, PUT gibi isteklerin body'sini güvenli bir şekilde al
    body = ''
    if request.method in ['POST', 'PUT', 'PATCH']:
        try:
            body = request.get_data(as_text=True)
        except Exception as e:
            logger.warning(f"WAF: İstek body'si okunamadı. IP: {user_ip}, Hata: {e}")

    # Kontrol edilecek tüm metinleri birleştir
    data_to_check = {
        'path': path_and_query,
        'user_agent': user_agent,
        'body': body
    }

    # Kuralları uygula
    for rule in rules:
        for source, data in data_to_check.items():
            if data and re.search(rule['pattern'], data, re.IGNORECASE):
                # Kural eşleşti! Saldırı girişimini engelle ve logla.
                log_extra = {
                    'ip': user_ip,
                    'rule': rule['name'],
                    'path': request.path,
                    'data': f"Kaynak: {source}, Veri: {data[:200]}" # Verinin ilk 200 karakterini logla
                }
                waf_logger.warning("Potansiyel Saldırı Engellendi!", extra=log_extra)
                
                # İsteği 403 Forbidden hatası ile sonlandır
                return jsonify({
                    'success': False,
                    'error': 'Forbidden',
                    'message': 'İsteğiniz güvenlik politikalarımızı ihlal ettiği için reddedildi.'
                }), 403

    # Hiçbir kural eşleşmezse, isteğin normal şekilde devam etmesine izin ver
    return None

# --- BİTİŞ: Yeni Konum Mantığı ---

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
    # DEĞİŞİKLİK: Çalma listesi URL'sini de URI'ye çevirme eklendi
    elif actual_item_type == 'playlist' and '/playlist/' in item_id:
        match = re.search(r'/playlist/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:playlist:{match.group(1)}"

    # Unrecognized or invalid format
    logger.warning(f"Tanınmayan veya geçersiz Spotify {actual_item_type} ID/URI formatı: {item_id}")
    return None

# --- Ayarlar Yönetimi (Filtreler Eklendi) ---
def load_settings():
    """Ayarları dosyadan yükler, eksik filtre ayarları için varsayılanları ekler."""
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5,
        'active_device_id': None,
        'genre_filter_mode': 'blacklist',
        'artist_filter_mode': 'blacklist',
        'track_filter_mode': 'blacklist',  # song_filter_mode yerine track_filter_mode kullan
        'genre_blacklist': [],
        'genre_whitelist': [],
        'artist_blacklist': [],
        'artist_whitelist': [],
        'track_blacklist': [],  # song_blacklist yerine track_blacklist kullan
        'track_whitelist': [],  # song_whitelist yerine track_whitelist kullan
        'active_playlist_uri': None
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
# DEĞİŞİKLİK: 'time_profiles' kaldırıldı. Bunun yerine çalma listesinden son çalınanları tutacağız.
recently_played_from_playlist = []
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

# --- Multi-Venue Spotify Client Yönetimi ---
venue_spotify_clients = {}  # venue_id -> spotify_client cache

def get_venue_spotify_client(venue_id):
    """Belirli bir venue için Spotify istemcisini döndürür veya oluşturur."""
    global venue_spotify_clients
    
    # Önce cache'e bak
    if venue_id in venue_spotify_clients:
        client = venue_spotify_clients[venue_id]
        try:
            client.current_user()
            logger.debug(f"[Venue {venue_id}] Cache'deki Spotify istemcisi geçerli.")
            return client
        except Exception as e:
            logger.warning(f"[Venue {venue_id}] Cache'deki istemci geçersiz: {e}")
            del venue_spotify_clients[venue_id]
    
    # Veritabanından token al
    spotify_data = VenueSpotifyData.get_by_venue_id(venue_id)
    if not spotify_data or not spotify_data.get('spotify_token_info'):
        logger.info(f"[Venue {venue_id}] Spotify token bulunamadı. Yetkilendirme gerekli.")
        return None
    
    token_info = spotify_data['spotify_token_info']
    
    try:
        auth_manager = get_spotify_auth()
    except ValueError as e:
        logger.error(f"[Venue {venue_id}] SpotifyOAuth oluşturulamadı: {e}")
        return None
    
    try:
        # Token süresi dolmuş mu kontrol et
        if auth_manager.is_token_expired(token_info):
            logger.info(f"[Venue {venue_id}] Token süresi dolmuş, yenileniyor...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val:
                logger.error(f"[Venue {venue_id}] Refresh token bulunamadı.")
                VenueSpotifyData.delete_token(venue_id)
                return None
            
            try:
                auth_manager.token = token_info
                new_token_info = auth_manager.refresh_access_token(refresh_token_val)
                if not new_token_info:
                    logger.error(f"[Venue {venue_id}] Token yenilenemedi.")
                    VenueSpotifyData.delete_token(venue_id)
                    return None
                
                if isinstance(new_token_info, str):
                    token_info['access_token'] = new_token_info
                    token_info['expires_at'] = int(time.time()) + 3600
                    new_token_info = token_info
                
                # Yenilenen token'ı veritabanına kaydet
                VenueSpotifyData.save_token(venue_id, new_token_info)
                token_info = new_token_info
                logger.info(f"[Venue {venue_id}] Token başarıyla yenilendi.")
            except Exception as e:
                logger.error(f"[Venue {venue_id}] Token yenileme hatası: {e}")
                return None
        
        # Spotify client oluştur
        access_token = token_info.get('access_token')
        if not access_token:
            logger.error(f"[Venue {venue_id}] Token'da access_token bulunamadı.")
            return None
        
        new_client = spotipy.Spotify(auth=access_token)
        
        # Doğrula
        try:
            user_info = new_client.current_user()
            logger.info(f"[Venue {venue_id}] Spotify bağlandı: {user_info.get('display_name', '?')}")
            venue_spotify_clients[venue_id] = new_client
            return new_client
        except spotipy.SpotifyException as e:
            logger.error(f"[Venue {venue_id}] Spotify doğrulama hatası: {e}")
            if e.http_status in [401, 403]:
                VenueSpotifyData.delete_token(venue_id)
            return None
    except Exception as e:
        logger.error(f"[Venue {venue_id}] Spotify client oluşturma hatası: {e}")
        return None

def invalidate_venue_spotify_client(venue_id):
    """Venue'nun Spotify istemcisini cache'den siler."""
    global venue_spotify_clients
    if venue_id in venue_spotify_clients:
        del venue_spotify_clients[venue_id]
        logger.info(f"[Venue {venue_id}] Spotify client cache'den silindi.")

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

# --- Mekan Giriş Decorator'ı ---
def venue_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        venue_id = session.get('venue_id')
        if not venue_id:
            logger.warning("Yetkisiz mekan erişim girişimi")
            flash("Bu sayfaya erişmek için mekan girişi yapmalısınız.", "warning")
            return redirect(url_for('venue_login'))
        
        # Mekan bilgisini al ve request context'e ekle
        venue = Venue.get_by_id(venue_id)
        if not venue or not venue.is_active:
            session.clear()
            flash("Mekan hesabınız bulunamadı veya devre dışı.", "danger")
            return redirect(url_for('venue_login'))
        
        # Venue objesini flask g objesine ekle
        from flask import g
        g.current_venue = venue
        return f(*args, **kwargs)
    return decorated_function

# --- Abonelik Kontrolü Decorator'ı ---
def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        venue_id = session.get('venue_id')
        if not venue_id:
            flash("Giriş yapmalısınız.", "warning")
            return redirect(url_for('venue_login'))
        
        venue = Venue.get_by_id(venue_id)
        if not venue:
            session.clear()
            flash("Mekan bulunamadı.", "danger")
            return redirect(url_for('venue_login'))
        
        # Abonelik aktif mi kontrol et
        if not venue.is_subscription_active():
            flash("Aboneliğiniz sona ermiş. Lütfen aboneliğinizi yenileyin.", "warning")
            return redirect(url_for('subscription_page'))
        
        from flask import g
        g.current_venue = venue
        return f(*args, **kwargs)
    return decorated_function

# DEĞİŞİKLİK: Zaman profili ve öneri fonksiyonları kaldırıldı.
# def get_current_time_profile(): ... (KALDIRILDI)
# def update_time_profile(track_uri, spotify): ... (KALDIRILDI)
# def suggest_song_for_time(spotify): ... (KALDIRILDI)



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
        track_blacklist_uris = settings.get('track_blacklist', [])
        track_whitelist_uris = settings.get('track_whitelist', [])
        artist_blacklist_uris = settings.get('artist_blacklist', [])
        artist_whitelist_uris = settings.get('artist_whitelist', [])
        genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
        genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]

        # 2. Şarkı Filtresi Kontrolü
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
    return render_template('admin.html',csrf_token=generate_csrf())

@app.route('/admin-login', methods=['POST'])
@limiter.limit("3 per minute")
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

# --- Mekan Giriş/Kayıt Rotaları ---
@app.route('/venue/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def venue_login():
    """Mekan giriş sayfası"""
    if session.get('venue_id'):
        return redirect(url_for('admin_panel'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash("E-posta ve şifre gerekli.", "warning")
            return render_template('login.html', csrf_token=generate_csrf())
        
        venue = Venue.authenticate(email, password)
        if venue:
            session['venue_id'] = venue.id
            session['venue_name'] = venue.name
            session['admin_logged_in'] = True  # Admin paneline erişim için
            logger.info(f"Mekan girişi başarılı: {venue.name} (ID: {venue.id})")
            
            # Abonelik durumunu kontrol et
            if not venue.is_subscription_active():
                flash(f"Hoş geldiniz {venue.name}! Aboneliğiniz sona ermiş.", "warning")
                return redirect(url_for('subscription_page'))
            
            flash(f"Hoş geldiniz {venue.name}!", "success")
            return redirect(url_for('admin_panel'))
        else:
            logger.warning(f"Başarısız mekan girişi: {email}")
            flash("E-posta veya şifre hatalı.", "danger")
    
    return render_template('login.html', csrf_token=generate_csrf())

@app.route('/venue/register', methods=['GET', 'POST'])
@limiter.limit("3 per minute")
def venue_register():
    """Mekan kayıt sayfası"""
    if session.get('venue_id'):
        return redirect(url_for('admin_panel'))
    
    plans = SubscriptionPlan.get_all()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        
        errors = []
        if not name or len(name) < 2:
            errors.append("Mekan adı en az 2 karakter olmalı.")
        if not email or '@' not in email:
            errors.append("Geçerli bir e-posta adresi girin.")
        if not password or len(password) < 6:
            errors.append("Şifre en az 6 karakter olmalı.")
        if password != password_confirm:
            errors.append("Şifreler eşleşmiyor.")
        
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template('register.html', csrf_token=generate_csrf(), plans=plans)
        
        # Mekani oluştur
        result = Venue.create(name, email, password, phone, address)
        if result['success']:
            logger.info(f"Yeni mekan kaydı: {name} ({email})")
            flash("Kayıt başarılı! 7 günlük ücretsiz deneme süreniz başladı. Giriş yapabilirsiniz.", "success")
            return redirect(url_for('venue_login'))
        else:
            flash(result['error'], "danger")
    
    return render_template('register.html', csrf_token=generate_csrf(), plans=plans)

@app.route('/venue/logout')
def venue_logout():
    """Mekan çıkış işlemi"""
    venue_name = session.get('venue_name', 'Mekan')
    session.clear()
    logger.info(f"Mekan çıkışı: {venue_name}")
    flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('venue_login'))

@app.route('/subscription')
@venue_login_required
def subscription_page():
    """Abonelik yönetim sayfası"""
    from flask import g
    venue = g.current_venue
    plans = SubscriptionPlan.get_all()
    current_plan = SubscriptionPlan.get_by_name(venue.subscription_type)
    
    return render_template('subscription.html', 
                          venue=venue.to_dict(),
                          plans=plans,
                          current_plan=current_plan,
                          csrf_token=generate_csrf())

@app.route('/api/upgrade-subscription', methods=['POST'])
@venue_login_required
@limiter.limit("3 per minute")
def api_upgrade_subscription():
    """Abonelik yükseltme API"""
    from flask import g
    venue = g.current_venue
    
    if not request.is_json:
        return jsonify({'success': False, 'error': 'JSON gerekli'}), 400
    
    data = request.get_json()
    plan_name = data.get('plan')
    
    if not plan_name:
        return jsonify({'success': False, 'error': 'Plan seçilmedi'}), 400
    
    # Ödeme simülasyonu (gerçek uygulamada ödeme gateway'i kullanılmalı)
    result = venue.upgrade_subscription(plan_name, amount_paid=0, payment_method='demo')
    
    if result['success']:
        logger.info(f"Abonelik yükseltildi: {venue.name} -> {plan_name}")
        return jsonify({'success': True, 'message': result['message']})
    else:
        return jsonify({'success': False, 'error': result['error']}), 400


# app.py dosyasında, mevcut admin_panel fonksiyonunu bununla değiştirin.
@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    """Yönetim panelini gösterir. Venue bazlı Spotify ve kuyruk kullanır."""
    global auto_advance_enabled, settings
    
    # Venue bazlı mı yoksa eski admin mi kontrol et
    venue_id = session.get('venue_id')
    
    if venue_id:
        # Venue bazlı Spotify client
        spotify = get_venue_spotify_client(venue_id)
        venue_settings = VenueSettings.get_settings(venue_id)
        venue_queue = VenueQueue.get_queue(venue_id)
        spotify_data = VenueSpotifyData.get_by_venue_id(venue_id)
        active_device_id = spotify_data.get('active_device_id') if spotify_data else None
        active_playlist_uri = spotify_data.get('active_playlist_uri') if spotify_data else None
        venue_auto_advance = spotify_data.get('auto_advance_enabled', True) if spotify_data else True
    else:
        # Eski global admin sistemi
        spotify = get_spotify_client()
        venue_settings = settings
        venue_queue = song_queue
        active_device_id = settings.get('active_device_id')
        active_playlist_uri = settings.get('active_playlist_uri')
        venue_auto_advance = auto_advance_enabled
    
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None
    filtered_queue = []
    
    # Sayfalama değişkenleri
    user_playlists = []
    paginated_playlists = []
    page = request.args.get('page', 1, type=int)
    per_page = 8
    total_pages = 1

    if spotify:
        spotify_authenticated = True
        session['spotify_authenticated'] = True
        try:
            # Spotify cihazlarını al
            result = spotify.devices()
            spotify_devices = result.get('devices', [])
            
            # Kullanıcının tüm çalma listelerini al
            try:
                all_playlists = []
                results = spotify.current_user_playlists(limit=50)
                all_playlists.extend(results['items'])
                while results['next']:
                    results = spotify.next(results)
                    all_playlists.extend(results['items'])
                user_playlists = all_playlists
                logger.info(f"[Venue {venue_id or 'Admin'}] {len(user_playlists)} çalma listesi bulundu.")

                # Sayfalama
                total_items = len(user_playlists)
                total_pages = (total_items + per_page - 1) // per_page
                start = (page - 1) * per_page
                end = start + per_page
                paginated_playlists = user_playlists[start:end]

            except Exception as pl_err:
                logger.warning(f"Çalma listeleri alınamadı: {pl_err}")
                flash("Spotify çalma listeleriniz alınırken bir hata oluştu.", "warning")

            # Kullanıcı bilgisini al
            try: 
                user = spotify.current_user()
                spotify_user = user.get('display_name', '?')
                session['spotify_user'] = spotify_user
            except Exception as user_err: 
                logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}")
                session.pop('spotify_user', None)
            
            # Şu an çalan şarkı bilgisini al
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']
                    is_playing = playback.get('is_playing', False)
                    track_uri = item.get('uri')
                    if track_uri and track_uri.startswith('spotify:track:'):
                        is_allowed, _ = check_song_filters(track_uri, spotify)
                        track_name = item.get('name', '?')
                        artists = item.get('artists', [])
                        artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
                        images = item.get('album', {}).get('images', [])
                        image_url = images[0].get('url') if images else None
                        currently_playing_info = {
                            'id': track_uri, 'name': track_name, 'artist': artist_name,
                            'artist_ids': artist_uris, 'image_url': image_url, 
                            'is_playing': is_playing, 'is_allowed': is_allowed
                        }
            except Exception as pb_err: 
                logger.warning(f"Çalma durumu alınamadı: {pb_err}")

            # Kuyruğu filtrele
            for song in venue_queue:
                song_uri = song.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, spotify)
                    if is_allowed:
                        if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                            song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song['artist_ids']]
                        filtered_queue.append(song)
                        
        except spotipy.SpotifyException as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e.http_status} - {e.msg}")
            spotify_authenticated = False
            session['spotify_authenticated'] = False
            if e.http_status in [401, 403]:
                flash("Spotify yetkilendirmesi geçersiz. Lütfen tekrar yetkilendirin.", "warning")
                if venue_id:
                    VenueSpotifyData.delete_token(venue_id)
                    invalidate_venue_spotify_client(venue_id)
                else:
                    if os.path.exists(TOKEN_FILE): 
                        os.remove(TOKEN_FILE)
                    global spotify_client
                    spotify_client = None
            else: 
                flash(f"Spotify API hatası: {e.msg}", "danger")
        except Exception as e:
            logger.error(f"Admin panelinde beklenmedik hata: {e}", exc_info=True)
            spotify_authenticated = False
            session['spotify_authenticated'] = False
            flash("Beklenmedik bir hata oluştu.", "danger")
    else:
        spotify_authenticated = False
        session['spotify_authenticated'] = False
        flash("Spotify hesabınızı bağlamak için yetkilendirme yapın.", "info")
        
    return render_template(
        'admin_panel.html',
        settings=venue_settings,
        spotify_devices=spotify_devices,
        queue=filtered_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=active_device_id,
        currently_playing_info=currently_playing_info,
        auto_advance_enabled=venue_auto_advance,
        paginated_playlists=paginated_playlists,
        page=page,
        total_pages=total_pages,
        active_playlist_uri=active_playlist_uri,
        csrf_token=generate_csrf(),
        venue_id=venue_id
    )

# --- Çalma Kontrol Rotaları ---
@app.route('/player/pause')
@limiter.limit("10 per minute")
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
@limiter.limit("10 per minute")
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

@app.route('/player/next', methods=['POST']) # 'POST' metodu daha güvenli ve idempotent olmayan işlemler için daha uygundur
@admin_login_required
@limiter.limit("5 per minute")
def player_next():
    global auto_advance_enabled # Otomatik geçişi de kontrol etmek isteyebilirsiniz
    spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')

    if not spotify:
        flash('Spotify bağlantısı yok!', 'danger')
        return redirect(url_for('admin_panel'))

    try:
        logger.info(f"Admin: Sonraki şarkıya geçiş isteği (Cihaz: {active_spotify_connect_device_id or '?'}).")
        spotify.next_track(device_id=active_spotify_connect_device_id)
        # Eğer otomatik geçiş kapalıysa, bir sonraki şarkıya geçildiğinde otomatik geçişi tekrar açmak mantıklı olabilir.
        # Ya da sadece manuel geçiş yapmak isteyip otomatik geçiş ayarını değiştirmeyebilirsiniz.
        # auto_advance_enabled = True # Bu satırı isterseniz ekleyebilirsiniz
        logger.info("Admin: Sonraki şarkıya geçildi.")
        flash('Sonraki şarkıya geçildi.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify sonraki şarkı hatası: {e}")
        if e.http_status == 401 or e.http_status == 403:
            flash('Spotify yetkilendirme hatası. Lütfen tekrar yetkilendirin.', 'danger')
            global spotify_client
            spotify_client = None
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404:
            flash(f'Sonraki şarkıya geçiş hatası: Cihaz bulunamadı veya oynatma aktif değil ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE':
            flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        else:
            flash(f'Spotify sonraki şarkı hatası: {e.msg}', 'danger')
    except Exception as e:
        logger.error(f"Sonraki şarkıya geçiş sırasında genel hata: {e}", exc_info=True)
        flash('Sonraki şarkıya geçilirken bir hata oluştu.', 'danger')

    return redirect(url_for('admin_panel'))
# --- Diğer Rotalar ---
@app.route('/refresh-devices')
@admin_login_required
@limiter.limit("5 per minute")
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
        
        # DEĞİŞİKLİK: Aktif çalma listesi ayarını kaydet
        if 'active_playlist_uri' in request.form:
            new_playlist_uri = request.form.get('active_playlist_uri')
            current_settings['active_playlist_uri'] = new_playlist_uri if new_playlist_uri else None
            logger.info(f"Aktif çalma listesi ayarlandı: {current_settings['active_playlist_uri']}")

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
    """Spotify yetkilendirme akışını başlatır (venue bazlı)."""
    venue_id = session.get('venue_id')
    if venue_id:
        # Venue bazlı yetkilendirme
        logger.info(f"[Venue {venue_id}] Spotify yetkilendirme başlatılıyor...")
    else:
        # Admin için eski global token
        if os.path.exists(TOKEN_FILE): 
            logger.warning("Mevcut token varken yeniden yetkilendirme.")
    
    try: 
        auth_manager = get_spotify_auth()
        auth_url = auth_manager.get_authorize_url()
        logger.info(f"Spotify yetkilendirme URL'sine yönlendiriliyor. Redirect URI: {SPOTIFY_REDIRECT_URI}")
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
    """Spotify OAuth callback - venue bazlı token kaydetme."""
    try: 
        auth_manager = get_spotify_auth()
    except ValueError as e: 
        logger.error(f"Callback hatası: {e}")
        return f"Callback Hatası: {e}", 500
    
    if 'error' in request.args: 
        error = request.args.get('error')
        logger.error(f"Spotify yetkilendirme hatası (callback): {error}")
        return f"Spotify Yetkilendirme Hatası: {error}", 400
    
    if 'code' not in request.args: 
        logger.error("Callback'te 'code' yok.")
        return "Geçersiz callback isteği.", 400
    
    code = request.args.get('code')
    
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        if not token_info: 
            logger.error("Spotify'dan token alınamadı.")
            return "Token alınamadı.", 500
        
        if isinstance(token_info, str): 
            logger.error("get_access_token sadece string döndürdü, refresh token alınamadı.")
            return "Token bilgisi eksik alındı.", 500
        elif not isinstance(token_info, dict): 
            logger.error(f"get_access_token beklenmedik formatta veri döndürdü: {type(token_info)}")
            return "Token bilgisi alınırken hata oluştu.", 500
        
        # Venue bazlı mı yoksa admin mi kontrol et
        venue_id = session.get('venue_id')
        
        if venue_id:
            # Venue bazlı token kaydetme
            temp_client = spotipy.Spotify(auth=token_info.get('access_token'))
            try:
                user_info = temp_client.current_user()
                user_name = user_info.get('display_name', '')
                user_id = user_info.get('id', '')
            except:
                user_name = None
                user_id = None
            
            result = VenueSpotifyData.save_token(venue_id, token_info, user_name, user_id)
            if result['success']:
                invalidate_venue_spotify_client(venue_id)  # Cache'i temizle
                logger.info(f"[Venue {venue_id}] Spotify yetkilendirmesi başarılı.")
                flash("Spotify yetkilendirmesi başarıyla tamamlandı!", "success")
                return redirect(url_for('admin_panel'))
            else:
                logger.error(f"[Venue {venue_id}] Token kaydedilemedi: {result.get('error')}")
                return "Token kaydedilirken bir hata oluştu.", 500
        else:
            # Eski admin global token
            if save_token(token_info):
                global spotify_client
                spotify_client = None  # Yeni token ile istemciyi yeniden oluşturmaya zorla
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


# GÜNCELLENDİ: /search endpoint'i filtrelemeyi uygular ve URI kullanır
@app.route('/search', methods=['POST'])
@limiter.limit("5 per minute")
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
@limiter.limit("5 per minute")
def add_song():
    """Admin tarafından şarkı ekleme (Filtreleri atlar). Venue bazlı kuyruk kullanır."""
    global song_queue
    
    venue_id = session.get('venue_id')
    song_input = request.form.get('song_id', '').strip()
    
    if not song_input: 
        flash("Şarkı ID/URL girin.", "warning")
        return redirect(url_for('admin_panel'))

    track_uri = _ensure_spotify_uri(song_input, 'track')
    if not track_uri: 
        flash("Geçersiz Spotify Şarkı ID veya URL formatı.", "danger")
        return redirect(url_for('admin_panel'))

    # Kuyruk limiti kontrol
    if venue_id:
        queue_length = VenueQueue.get_length(venue_id)
        venue_settings = VenueSettings.get_settings(venue_id)
        max_length = venue_settings.get('max_queue_length', 20)
    else:
        queue_length = len(song_queue)
        max_length = settings.get('max_queue_length', 20)
    
    if queue_length >= max_length:
        flash("Kuyruk dolu!", "warning")
        return redirect(url_for('admin_panel'))

    # Spotify client al
    if venue_id:
        spotify = get_venue_spotify_client(venue_id)
    else:
        spotify = get_spotify_client()
    
    if not spotify: 
        flash("Spotify yetkilendirmesi gerekli.", "warning")
        return redirect(url_for('spotify_auth'))

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: 
            flash(f"Şarkı bulunamadı (URI: {track_uri}).", "danger")
            return redirect(url_for('admin_panel'))

        artists = song_info.get('artists', [])
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_name = ', '.join([a.get('name') for a in artists])
        
        images = song_info.get('album', {}).get('images', [])
        image_url = images[0].get('url') if images else None
        song_name = song_info.get('name', '?')

        if venue_id:
            # Venue bazlı kuyruğa ekle
            VenueQueue.add_song(
                venue_id=venue_id,
                song_uri=track_uri,
                song_name=song_name,
                artist_name=artist_name,
                artist_ids=artist_uris,
                image_url=image_url,
                added_by='admin'
            )
        else:
            # Eski global kuyruk
            song_queue.append({
                'id': track_uri,
                'name': song_name,
                'artist': artist_name,
                'artist_ids': artist_uris,
                'image_url': image_url,
                'added_by': 'admin',
                'added_at': time.time()
            })
        
        logger.info(f"[Venue {venue_id or 'Admin'}] Şarkı eklendi: {track_uri} - {song_name}")
        flash(f"'{song_name}' eklendi.", "success")
        
    except spotipy.SpotifyException as e:
        logger.error(f"Admin eklerken Spotify hatası (URI={track_uri}): {e}")
        if e.http_status in [401, 403]: 
            flash("Spotify yetkilendirme hatası.", "danger")
            return redirect(url_for('spotify_auth'))
        elif e.http_status == 400: 
            flash(f"Geçersiz Spotify URI: {track_uri}", "danger")
        else: 
            flash(f"Spotify hatası: {e.msg}", "danger")
    except Exception as e: 
        logger.error(f"Admin eklerken genel hata (URI={track_uri}): {e}", exc_info=True)
        flash("Şarkı eklenirken hata.", "danger")
    
    return redirect(url_for('admin_panel'))

# --- Queue Rotaları ---
@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Kullanıcı tarafından şarkı ekleme (Filtreler uygulanır). Venue bazlı."""
    global settings, song_queue, user_requests
    
    if not request.is_json: 
        return jsonify({'error': 'Geçersiz format.'}), 400
    
    data = request.get_json()
    track_identifier = data.get('track_id')
    venue_id = data.get('venue_id')  # İstemciden venue_id alınır
    
    logger.info(f"[Venue {venue_id or 'Global'}] Kuyruğa ekleme isteği: {track_identifier}")
    
    if not track_identifier: 
        return jsonify({'error': 'Eksik ID.'}), 400

    track_uri = _ensure_spotify_uri(track_identifier, 'track')
    if not track_uri:
        return jsonify({'error': 'Geçersiz şarkı ID formatı.'}), 400

    # Kuyruk ve ayarları venue bazlı al
    if venue_id:
        queue_length = VenueQueue.get_length(venue_id)
        venue_settings = VenueSettings.get_settings(venue_id)
        max_queue = venue_settings.get('max_queue_length', 20)
        max_requests = venue_settings.get('max_user_requests_per_hour', 5)
        spotify = get_venue_spotify_client(venue_id)
    else:
        queue_length = len(song_queue)
        max_queue = settings.get('max_queue_length', 20)
        max_requests = settings.get('max_user_requests', 5)
        spotify = get_spotify_client()

    if queue_length >= max_queue: 
        return jsonify({'error': 'Kuyruk dolu.'}), 429

    user_ip = request.remote_addr
    if user_requests.get(user_ip, 0) >= max_requests: 
        return jsonify({'error': f'İstek limitiniz ({max_requests}) doldu.'}), 429

    if not spotify: 
        return jsonify({'error': 'Spotify bağlantısı yok.'}), 503

    is_allowed, reason = check_song_filters(track_uri, spotify)
    if not is_allowed:
        return jsonify({'error': reason}), 403

    try:
        song_info = spotify.track(track_uri, market='TR')
        if not song_info: 
            return jsonify({'error': 'Şarkı bilgisi alınamadı.'}), 500
        
        song_name = song_info.get('name', '?')
        artists = song_info.get('artists', [])
        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
        artist_name = ', '.join([a.get('name') for a in artists])
        images = song_info.get('album', {}).get('images', [])
        image_url = images[0].get('url') if images else None

        if venue_id:
            VenueQueue.add_song(
                venue_id=venue_id,
                song_uri=track_uri,
                song_name=song_name,
                artist_name=artist_name,
                artist_ids=artist_uris,
                image_url=image_url,
                added_by=user_ip
            )
        else:
            song_queue.append({
                'id': track_uri,
                'name': song_name,
                'artist': artist_name,
                'artist_ids': artist_uris,
                'image_url': image_url,
                'added_by': user_ip,
                'added_at': time.time()
            })
        
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        logger.info(f"[Venue {venue_id or 'Global'}] Şarkı eklendi: {song_name}")
        return jsonify({'success': True, 'message': f"'{song_name}' kuyruğa eklendi!"})

    except spotipy.SpotifyException as e:
        logger.error(f"Kullanıcı eklerken Spotify hatası: {e}")
        if e.http_status in [401, 403]: 
            return jsonify({'error': 'Spotify yetkilendirme sorunu.'}), 503
        elif e.http_status == 400: 
            return jsonify({'error': f"Geçersiz Spotify URI"}), 400
        else: 
            return jsonify({'error': f"Spotify hatası: {e.msg}"}), 500
    except Exception as e:
        logger.error(f"Kuyruğa ekleme hatası: {e}", exc_info=True)
        return jsonify({'error': 'Şarkı eklenirken bilinmeyen bir sorun oluştu.'}), 500


@app.route('/remove-song/<path:song_id_str>', methods=['POST'])
@admin_login_required
def remove_song(song_id_str):
    """Admin tarafından kuyruktan şarkı kaldırma. Venue bazlı."""
    global song_queue
    
    venue_id = session.get('venue_id')
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track')
    
    if not song_uri_to_remove:
        flash(f"Geçersiz şarkı ID formatı: {song_id_str}", "danger")
        return redirect(url_for('admin_panel'))

    logger.debug(f"[Venue {venue_id or 'Admin'}] Kuyruktan kaldırılacak URI: {song_uri_to_remove}")
    
    if venue_id:
        result = VenueQueue.remove_song(venue_id, song_uri_to_remove)
        if result['success']:
            logger.info(f"[Venue {venue_id}] Şarkı kaldırıldı: {song_uri_to_remove}")
            flash("Şarkı kuyruktan kaldırıldı.", "success")
        else:
            flash("Şarkı kuyrukta bulunamadı.", "warning")
    else:
        original_length = len(song_queue)
        song_queue = [song for song in song_queue if song.get('id') != song_uri_to_remove]
        if len(song_queue) < original_length:
            logger.info(f"Şarkı kaldırıldı (Admin): URI={song_uri_to_remove}")
            flash("Şarkı kuyruktan kaldırıldı.", "success")
        else:
            flash("Şarkı kuyrukta bulunamadı.", "warning")
    
    return redirect(url_for('admin_panel'))

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    """Kuyruğu temizler. Venue bazlı."""
    global song_queue, user_requests
    
    venue_id = session.get('venue_id')
    
    if venue_id:
        VenueQueue.clear_queue(venue_id)
        logger.info(f"[Venue {venue_id}] Kuyruk temizlendi.")
    else:
        song_queue = []
        user_requests = {}
        logger.info("Kuyruk temizlendi (Admin).")
    
    flash("Kuyruk temizlendi.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/queue')
def view_queue():
    """Kullanıcılar için şarkı kuyruğunu gösterir (Filtrelenmiş)."""
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
                        image_url = images[-1].get('url') if images else None # En küçük resmi al
                        artist_uris = [_ensure_spotify_uri(a.get('id'), 'artist') for a in artists if a.get('id')]
                        recently_played_info = {
                            'id': track_uri, 'name': track_name, 'artist': artist_name,
                            'artist_ids': artist_uris, 'image_url': image_url
                        }
                        logger.debug(f"Son Çalınan (Kuyruk): {track_name}")
        except Exception as e:
            logger.error(f"Son çalınan şarkı alınırken hata: {e}", exc_info=True)

        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']; is_playing = playback.get('is_playing', False)
                track_uri = item.get('uri')
                if track_uri and track_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(track_uri, spotify)
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

        for song in song_queue:
            song_uri = song.get('id')
            if song_uri and song_uri.startswith('spotify:track:'):
                is_allowed, _ = check_song_filters(song_uri, spotify)
                if is_allowed:
                    if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                         song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song['artist_ids']]
                    filtered_queue.append(song)
                else:
                     logger.debug(f"Kuyruk Sayfası: Kuyruktaki şarkı filtrelendi: {song.get('name')} ({song_uri})")
            else:
                 logger.warning(f"Kuyruk Sayfası: Kuyrukta geçersiz şarkı formatı: {song}")

    return render_template(
        'queue.html', 
        queue=filtered_queue, 
        currently_playing_info=currently_playing_info,
        recently_played_info=recently_played_info
    )


@app.route('/api/queue')
def api_get_queue():
    """API: Filtrelenmemiş ham kuyruk verisini döndürür (Admin veya debug için)."""
    global song_queue
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue), 'max_length': settings.get('max_queue_length', 20)})

# --- Filtre Yönetimi API Rotaları (Güncellendi) ---


@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    """Hızlı engelleme: Sanatçı veya şarkıyı doğrudan kara listeye ekler."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); item_type = data.get('type'); identifier = data.get('identifier')
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
    spotify = get_spotify_client()              
    if not spotify:
        return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503
    
    try:
        # get_access_token() yerine doğrudan client'in auth bilgisini kullanabiliriz
        # spotipy objesi zaten token'ı içerir
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
    actual_id_type = 'track' if id_type == 'song' else id_type
    if actual_id_type not in ['artist', 'track']: return jsonify({'success': False, 'error': 'Geçersiz tip (artist veya track).'}), 400

    spotify = get_spotify_client()
    if not spotify: return jsonify({'success': False, 'error': 'Spotify bağlantısı yok.'}), 503

    details_map = {}
    batch_size = 50
    valid_uris = [_ensure_spotify_uri(uri, actual_id_type) for uri in uris]
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



# --- Helper: Broadcast State ---
def broadcast_state(venue_id=None):
    """Broadcasts current state (queue + now playing) to venue room"""
    # 1. Kuyruk Yayınla
    if venue_id:
        queue = VenueQueue.get_queue(venue_id)
        socketio.emit('queueUpdated', queue, room=f'venue_{venue_id}') # Event ismi queueUpdated olarak düzeltildi (frontend ile uyumlu)
        
        # 2. Şimdi Çalıyor Yayınla
        spotify = get_venue_spotify_client(venue_id)
        if spotify:
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']
                    track_data = {
                        'item': item,
                        'is_playing': playback['is_playing'],
                        'progress_ms': playback['progress_ms']
                    }
                    socketio.emit('nowPlaying', track_data, room=f'venue_{venue_id}')
                else:
                    # Çalıyor bilgisi yoksa boş gönder ya da paused
                    socketio.emit('nowPlaying', {'item': None, 'is_playing': False}, room=f'venue_{venue_id}')
            except Exception as e:
                logger.error(f"Broadcast error (nowPlaying): {e}")

# --- Arka Plan Şarkı Çalma İş Parçacığı ---
def background_queue_player():
    # DEĞİŞİKLİK: 'time_profiles' yerine 'recently_played_from_playlist' kullanılıyor.
    global spotify_client, song_queue, user_requests, settings, auto_advance_enabled, recently_played_from_playlist
    logger.info("Arka plan şarkı çalma/çalma listesi görevi başlatılıyor...")
    last_played_song_uri = None
    
    # Tüm aktif mekanları bulup döngüde kontrol etmemiz lazım
    # Ancak basitlik için şimdilik sadece döngü kuralım
    # Gerçek uygulamada her venue için ayrı thread veya async yapı gerekir
    # Burada basitleştirilmiş bir yapı kullanacağız:
    
    while True:
        try:
            # Sadece aktif, Spotify bağlı mekanları döngüye al
            # NOT: Bu kısım normalde veritabanından aktif mekanları çekmeli
            # Ancak `app.py` tek instance çalışıyorsa global cache kullanılabilir
            
            # Global Admin (Legacy) Desteği
            if spotify_client:
                # ... (Eski mantık buraya eklenebilir ama şu an venue odaklı gidiyoruz)
                pass

            # Venue bazlı kontrol (Örnek: Cache'deki client'lar üzerinden)
            # venue_spotify_clients global değişkenini kullanabiliriz
            # Bu basit bir yaklaşım, production için daha sağlam bir yapı gerekir.
            
            for venue_id, client in list(venue_spotify_clients.items()):
                try:
                    # Durum güncellemesi yayınla (Her 5 saniyede bir veya değişiklikte)
                    broadcast_state(venue_id)
                    
                    # Otomatik İlerleme Mantığı (Venue için)
                    spotify_data = VenueSpotifyData.get_by_venue_id(venue_id)
                    if not spotify_data or not spotify_data.get('auto_advance_enabled'):
                        continue

                    current_playback = client.current_playback(additional_types='track,episode', market='TR')
                    is_playing = current_playback.get('is_playing', False) if current_playback else False
                    
                    if not is_playing:
                        # Kuyruk kontrol
                        venue_queue_len = VenueQueue.get_length(venue_id)
                        if venue_queue_len > 0:
                            next_song = VenueQueue.pop_first(venue_id)
                            if next_song:
                                logger.info(f"[Venue {venue_id}] Kuyruktan çalınıyor: {next_song.get('name')}")
                                client.start_playback(uris=[next_song['id']])
                                # Çalmaya başladı, hemen durumu güncelle
                                time.sleep(1) 
                                broadcast_state(venue_id)
                        else:
                             # Çalma listesinden çal (Eğer ayarlıysa)
                             playlist_uri = spotify_data.get('active_playlist_uri')
                             if playlist_uri:
                                 # (Çalma listesi mantığı burada uygulanacak - basitleştirildi)
                                 pass
                                 
                except Exception as v_err:
                     logger.error(f"[Venue {venue_id}] Background loop error: {v_err}")
            
            time.sleep(5) # 5 saniyede bir kontrol

        except Exception as loop_err:
            logger.error(f"Arka plan döngü hatası: {loop_err}", exc_info=True)
            time.sleep(15)



@app.route('/api/set-active-playlist', methods=['POST'])
@admin_login_required
def api_set_active_playlist():
    """API: Tıklanan çalma listesini anında aktif olarak ayarlar."""
    global settings
    if not request.is_json:
        return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    
    data = request.get_json()
    playlist_uri = data.get('playlist_uri') # URI boş bir string olabilir (seçim kaldırıldığında)

    logger.info(f"API: Aktif çalma listesi güncelleniyor -> {playlist_uri or 'Hiçbiri'}")

    try:
        current_settings = load_settings()
        current_settings['active_playlist_uri'] = playlist_uri if playlist_uri else None
        save_settings(current_settings)
        settings = current_settings  # Global ayarları da anında güncelle
        
        message = "Otomatik çalma listesi güncellendi." if playlist_uri else "Otomatik çalma listesi seçimi kaldırıldı."
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Aktif çalma listesi ayarlanırken hata: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ayar kaydedilirken bir hata oluştu.'}), 500
# --- Uygulama Başlangıcı ---
def check_token_on_startup():
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client()
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Yetkilendirme gerekli olabilir.")

def start_queue_player():
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/çalma listesi görevi başlatıldı.")

@app.route('/api/check-port', methods=['POST'])
@admin_login_required
def check_port():
    """SSH portunun (22) durumunu kontrol eder."""
    try:
        data = request.get_json()
        port = data.get('port')
        
        if port != 22:
            return jsonify({'success': False, 'error': 'Sadece SSH portu (22) kontrol edilebilir'})
            
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
        logger.error(f"SSH port kontrolü sırasında hata: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("=================================================")
    logger.info(f"Platform: {platform.system()} ({'Windows' if IS_WINDOWS else 'Linux/Mac'})")
    logger.info(f"Ayarlar Yüklendi: {SETTINGS_FILE}")

    # Veritabanını başlat
    logger.info("Veritabanı başlatılıyor...")
    try:
        init_db()
        logger.info("Veritabanı hazır.")
    except Exception as db_err:
        logger.error(f"Veritabanı başlatma hatası: {db_err}")

    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.error("LÜTFEN app.py dosyasında Spotify API bilgilerinizi ayarlayın!")
    else:
         logger.info("Spotify API bilgileri app.py içinde tanımlı görünüyor.")
         logger.info(f"Kullanılacak Redirect URI: {SPOTIFY_REDIRECT_URI}")
         logger.info("!!! BU URI'nin Spotify Developer Dashboard'da kayıtlı olduğundan emin olun !!!")

    check_token_on_startup()
    start_queue_player()

    # Port: Spotify redirect URI ile aynı olmalı
    port = int(os.environ.get('PORT', 9187))
    logger.info(f"Uygulama arayüzüne http://localhost:{port} adresinden erişilebilir.")
    logger.info(f"Mekan girişi: http://localhost:{port}/venue/login")
    logger.info(f"Admin paneli: http://localhost:{port}/admin")

    # SocketIO ile başlat (WebSocket desteği için)
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


# --- QR Kod API ---
@app.route('/api/venue/qr-code')
@admin_login_required
def generate_venue_qr():
    """Venue için QR kod oluşturur"""
    venue_id = session.get('venue_id')
    if not venue_id:
        return jsonify({'error': 'Venue ID bulunamadı'}), 400
    
    venue = Venue.get_by_id(venue_id)
    if not venue:
        return jsonify({'error': 'Venue bulunamadı'}), 404
    
    # QR kod için URL oluştur
    base_url = request.host_url.rstrip('/')
    venue_url = f"{base_url}/?venue={venue_id}"
    
    # QR kod oluştur
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(venue_url)
    qr.make(fit=True)
    
    # Görsel olarak oluştur
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Base64'e çevir
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    return jsonify({
        'success': True,
        'qr_code': f"data:image/png;base64,{img_base64}",
        'url': venue_url,
        'venue_name': venue.name
    })


@app.route('/api/venue/qr-code/download')
@admin_login_required
def download_venue_qr():
    """Venue QR kodunu PNG olarak indir"""
    venue_id = session.get('venue_id')
    if not venue_id:
        return jsonify({'error': 'Venue ID bulunamadı'}), 400
    
    venue = Venue.get_by_id(venue_id)
    if not venue:
        return jsonify({'error': 'Venue bulunamadı'}), 404
    
    base_url = request.host_url.rstrip('/')
    venue_url = f"{base_url}/?venue={venue_id}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=15,
        border=4,
    )
    qr.add_data(venue_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return send_file(
        buffer, 
        mimetype='image/png', 
        as_attachment=True, 
        download_name=f'qr_{venue.slug or venue_id}.png'
    )


# --- Analytics API ---
@app.route('/api/analytics')
@admin_login_required
def get_analytics():
    """Venue için analytics verilerini döndürür"""
    venue_id = session.get('venue_id')
    if not venue_id:
        return jsonify({'error': 'Venue ID bulunamadı'}), 400
    
    days = request.args.get('days', 30, type=int)
    
    return jsonify({
        'success': True,
        'summary': SongRequestAnalytics.get_summary(venue_id),
        'top_tracks': SongRequestAnalytics.get_top_tracks(venue_id, limit=10, days=days),
        'hourly_stats': SongRequestAnalytics.get_hourly_stats(venue_id, days=7),
        'daily_stats': SongRequestAnalytics.get_daily_stats(venue_id, days=days)
    })


@app.route('/api/analytics/top-tracks')
@admin_login_required
def get_top_tracks_api():
    """En çok istenen şarkıları döndürür"""
    venue_id = session.get('venue_id')
    if not venue_id:
        return jsonify({'error': 'Venue ID bulunamadı'}), 400
    
    limit = request.args.get('limit', 10, type=int)
    days = request.args.get('days', 30, type=int)
    
    return jsonify({
        'success': True,
        'tracks': SongRequestAnalytics.get_top_tracks(venue_id, limit=limit, days=days)
    })


# --- Mobile API Endpoints ---
@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    """Mobile app login endpoint"""
    if not request.is_json:
        return jsonify({'success': False, 'error': 'JSON gerekli'}), 400
    
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'error': 'E-posta ve şifre gerekli'}), 400
    
    venue = Venue.authenticate(email, password)
    if venue:
        # Session oluştur
        session['venue_id'] = venue.id
        session['venue_name'] = venue.name
        session['admin_logged_in'] = True
        
        return jsonify({
            'success': True,
            'venue': {
                'id': venue.id,
                'name': venue.name,
                'slug': venue.slug
            },
            'session_id': session.get('csrf_token') # Basit session check için
        })
    else:
        return jsonify({'success': False, 'error': 'E-posta veya şifre hatalı'}), 401

@app.route('/api/state')
def api_get_state():
    """Get current player state and queue"""
    venue_id = session.get('venue_id')
    if not venue_id:
        return jsonify({'success': False, 'error': 'Giriş gerekli'}), 401

    spotify = get_venue_spotify_client(venue_id)
    if not spotify:
        return jsonify({'success': False, 'error': 'Spotify bağlı değil', 'spotify_connected': False}), 200

    # Get Queue
    queue = VenueQueue.get_queue(venue_id)
    
    # Get Now Playing
    currently_playing = None
    try:
        playback = spotify.current_playback(additional_types='track,episode', market='TR')
        if playback and playback.get('item'):
            item = playback['item']
            currently_playing = {
                'id': item.get('uri'),
                'name': item.get('name'),
                'artist': ', '.join([a['name'] for a in item['artists']]),
                'image_url': item['album']['images'][0]['url'] if item['album']['images'] else None,
                'is_playing': playback['is_playing'],
                'progress_ms': playback['progress_ms'],
                'duration_ms': item['duration_ms']
            }
    except Exception as e:
        logger.error(f"State API error: {e}")

    return jsonify({
        'success': True,
        'spotify_connected': True,
        'queue': queue,
        'now_playing': currently_playing
    })


# --- WebSocket Events ---
@socketio.on('connect')
def handle_connect():
    """Client bağlandığında"""
    logger.debug(f"WebSocket client bağlandı: {request.sid}")


@socketio.on('join_venue')
def handle_join_venue(data):
    """Client bir venue odasına katılır"""
    venue_id = data.get('venue_id')
    if venue_id:
        from flask_socketio import join_room
        join_room(f'venue_{venue_id}')
        logger.debug(f"Client {request.sid} venue_{venue_id} odasına katıldı")


def emit_queue_update(venue_id):
    """Venue kuyruğu güncellendiğinde tüm client'lara bildir"""
    queue = VenueQueue.get_queue(venue_id)
    socketio.emit('queue_updated', {'queue': queue}, room=f'venue_{venue_id}')


def emit_now_playing(venue_id, track_info):
    """Şu an çalan şarkı değiştiğinde bildir"""
    socketio.emit('now_playing', track_info, room=f'venue_{venue_id}')
