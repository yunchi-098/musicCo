# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse için
import subprocess # ex.py ve spotifyd için
from functools import wraps
# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi

# --- Yapılandırılabilir Ayarlar ---
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78' # ÖRNEK - DEĞİŞTİR
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426' # ÖRNEK - DEĞİŞTİR
SPOTIFY_REDIRECT_URI = 'http://100.81.225.104:8080/callback' # ÖRNEK - DEĞİŞTİR
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12 # Saniye cinsinden Bluetooth tarama süresi
EX_SCRIPT_PATH = 'ex.py' # ex.py betiğinin yolu
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish'] # Tekrar eklendi
# ---------------------------------

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION
app.jinja_env.globals['ALLOWED_GENRES'] = ALLOWED_GENRES # Şablona gönder

# --- Yardımcı Fonksiyon: Komut Çalıştırma (ex.py ve spotifyd için) ---
def _run_command(command, timeout=30):
    """Helper function to run shell commands and return parsed JSON or error."""
    try:
        full_command = ['python3', EX_SCRIPT_PATH] + command if command[0] != 'spotifyd' and command[0] != 'pgrep' else command # python3 olarak değiştirildi
        logger.debug(f"Running command: {' '.join(full_command)}")
        result = subprocess.run(full_command, capture_output=True, text=True, check=True, timeout=timeout, encoding='utf-8') # encoding eklendi
        logger.debug(f"Command stdout (first 500 chars): {result.stdout[:500]}")
        try:
            if command[0] != 'spotifyd' and command[0] != 'pgrep':
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
    result = _run_command(['restart_spotifyd'])
    return result.get('success', False), result.get('message', result.get('error', 'Bilinmeyen hata'))


# --- Ayarlar Yönetimi (Filtreler Eklendi) ---
def load_settings():
    """Ayarları dosyadan yükler, eksik filtre ayarları için varsayılanları ekler."""
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5,
        'active_device_id': None,
        'genre_filter_mode': 'blacklist',
        'artist_filter_mode': 'blacklist',
        'song_filter_mode': 'blacklist',
        'genre_blacklist': [],
        'genre_whitelist': [],
        'artist_blacklist': [],
        'artist_whitelist': [],
        'song_blacklist': [],
        'song_whitelist': [],
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            for key, default_value in default_settings.items():
                if key not in loaded:
                    logger.info(f"'{key}' ayarı dosyada bulunamadı, varsayılan değer ({default_value}) ekleniyor.")
                    loaded[key] = default_value
            if 'active_genres' in loaded:
                del loaded['active_genres']
                logger.info("Eski 'active_genres' ayarı kaldırıldı.")
            settings_to_use = loaded
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
    """Ayarları dosyaya kaydeder."""
    try:
        if 'genre_blacklist' in current_settings:
            current_settings['genre_blacklist'] = sorted(list(set([g.lower() for g in current_settings['genre_blacklist'] if isinstance(g, str)])))
        if 'genre_whitelist' in current_settings:
            current_settings['genre_whitelist'] = sorted(list(set([g.lower() for g in current_settings['genre_whitelist'] if isinstance(g, str)])))
        for key in ['artist_blacklist', 'artist_whitelist', 'song_blacklist', 'song_whitelist']:
             if key in current_settings:
                  current_settings[key] = sorted(list(set([item for item in current_settings[key] if isinstance(item, str)])))

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, indent=4, ensure_ascii=False)
        logger.info(f"Ayarlar kaydedildi: {SETTINGS_FILE}")
    except Exception as e:
        logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)

# --- Global Değişkenler ---
# Flask uygulaması yukarıda tanımlandı
spotify_client = None
song_queue = [] # Global kuyruk listesi
user_requests = {} # Kullanıcı istek limitleri
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] } # Zaman profilleri
settings = load_settings() # Uygulama başlangıcında ayarları yükle

# --- Spotify Token Yönetimi ---
def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f: return json.load(f)
        except Exception as e: logger.error(f"Token dosyası okuma hatası ({TOKEN_FILE}): {e}")
    return None
def save_token(token_info):
    try:
        with open(TOKEN_FILE, 'w') as f: json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi.")
    except Exception as e: logger.error(f"Token kaydetme hatası: {e}")
def get_spotify_auth():
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_'):
         raise ValueError("Spotify Client ID ve Secret app.py içinde ayarlanmamış!")
    return SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPE, open_browser=False, cache_path=None)
def get_spotify_client():
    global spotify_client
    token_info = load_token()
    if not token_info: return None
    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(e); return None
    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token süresi dolmuş, yenileniyor...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val: logger.error("Refresh token bulunamadı."); os.remove(TOKEN_FILE); spotify_client = None; return None
            new_token_info = auth_manager.refresh_access_token(refresh_token_val)
            if not new_token_info: logger.error("Token yenilenemedi."); os.remove(TOKEN_FILE); spotify_client = None; return None
            token_info = new_token_info; save_token(token_info)
        new_spotify_client = spotipy.Spotify(auth=token_info.get('access_token'))
        try: new_spotify_client.current_user(); spotify_client = new_spotify_client; return spotify_client
        except Exception as e:
            logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası: {e}")
            if "invalid access token" in str(e).lower() or "token expired" in str(e).lower() or "unauthorized" in str(e).lower():
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            spotify_client = None; return None
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API hatası (token işlemi sırasında): {e}")
        if e.http_status == 401 or e.http_status == 403:
             if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None; return None
    except Exception as e:
        logger.error(f"Spotify token işlemi sırasında genel hata: {e}", exc_info=True)
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None; return None

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
def update_time_profile(track_id, spotify):
    # global time_profiles # Bu global gerekli
    global time_profiles
    if not spotify or not track_id: logger.warning("update_time_profile: eksik parametre."); return
    profile_name = get_current_time_profile()
    logger.debug(f"'{profile_name}' profili güncelleniyor, track_id: {track_id}")
    try:
        track_info = spotify.track(track_id, market='TR')
        if not track_info: logger.warning(f"Şarkı detayı alınamadı: {track_id}"); return
        track_name = track_info.get('name', '?'); artists = track_info.get('artists')
        primary_artist_id = artists[0].get('id') if artists else None; primary_artist_name = artists[0].get('name') if artists else '?'
        profile_entry = {'id': track_id, 'artist_id': primary_artist_id, 'name': track_name, 'artist_name': primary_artist_name}
        time_profiles[profile_name].append(profile_entry)
        if len(time_profiles[profile_name]) > 5: time_profiles[profile_name] = time_profiles[profile_name][-5:]
        logger.info(f"'{profile_name}' profiline eklendi: '{track_name}'")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken hata (ID: {track_id}): {e}", exc_info=True)
def suggest_song_for_time(spotify):
    # global time_profiles, song_queue # Bu globaller gerekli
    global time_profiles, song_queue
    if not spotify: logger.warning("suggest_song_for_time: spotify istemcisi eksik."); return None
    profile_name = get_current_time_profile(); profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None
    seed_tracks = []; seed_artists = []
    last_entry = profile_data[-1]
    if last_entry.get('id'): seed_tracks.append(last_entry['id'])
    if last_entry.get('artist_id'): seed_artists.append(last_entry['artist_id'])
    if not seed_tracks and not seed_artists: logger.warning(f"'{profile_name}' profili öneri için tohum içermiyor."); return None
    try:
        logger.info(f"'{profile_name}' için öneri isteniyor: seeds={seed_tracks+seed_artists}")
        recs = spotify.recommendations(seed_tracks=seed_tracks, seed_artists=seed_artists, limit=5, market='TR')
        if recs and recs.get('tracks'):
            for suggested_track in recs['tracks']:
                 if not any(song.get('id') == suggested_track['id'] for song in song_queue):
                    is_allowed, _ = check_song_filters(suggested_track['id'], spotify)
                    if is_allowed:
                        logger.info(f"'{profile_name}' için öneri bulundu ve filtreden geçti: '{suggested_track.get('name')}'")
                        artists = suggested_track.get('artists', []); suggested_track['artist'] = ', '.join([a.get('name') for a in artists]) if artists else '?'
                        return suggested_track
                    else:
                         logger.info(f"'{profile_name}' için öneri bulundu ancak filtrelere takıldı: '{suggested_track.get('name')}'")
            logger.info(f"'{profile_name}' önerileri kuyrukta mevcut veya filtrelere takıldı.")
        else: logger.info(f"'{profile_name}' için öneri alınamadı."); return None
    except Exception as e: logger.error(f"'{profile_name}' için öneri alınırken hata: {e}", exc_info=True); return None

# --- Şarkı Filtreleme Yardımcı Fonksiyonu ---
def check_song_filters(track_id, spotify_client):
    """Verilen track_id'nin filtrelere uyup uymadığını kontrol eder."""
    global settings # Settings'i okumak için global
    if not spotify_client:
        return False, "Spotify bağlantısı yok."
    try:
        song_info = spotify_client.track(track_id, market='TR')
        if not song_info: return False, f"Şarkı bulunamadı (ID: {track_id})."
        song_spotify_id = song_info.get('id'); song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []); artist_ids = [a.get('id') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists]; primary_artist_id = artist_ids[0] if artist_ids else None

        song_filter_mode = settings.get('song_filter_mode', 'blacklist')
        if song_filter_mode == 'blacklist':
            if song_spotify_id in settings.get('song_blacklist', []): return False, 'Bu şarkı kara listede.'
        elif song_filter_mode == 'whitelist':
            song_whitelist = settings.get('song_whitelist', [])
            if not song_whitelist: return False, 'Şarkı beyaz listesi aktif ama boş.'
            if song_spotify_id not in song_whitelist: return False, 'Bu şarkı beyaz listede değil.'

        artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
        if artist_filter_mode == 'blacklist':
            artist_blacklist = settings.get('artist_blacklist', [])
            if any(a_id in artist_blacklist for a_id in artist_ids):
                blocked_artist = next((a_name for a_id, a_name in zip(artist_ids, artist_names) if a_id in artist_blacklist), "?")
                return False, f"'{blocked_artist}' sanatçısı kara listede."
        elif artist_filter_mode == 'whitelist':
            artist_whitelist = settings.get('artist_whitelist', [])
            if not artist_whitelist: return False, 'Sanatçı beyaz listesi aktif ama boş.'
            if not any(a_id in artist_whitelist for a_id in artist_ids): return False, 'Bu sanatçı beyaz listede değil.'

        genre_filter_mode = settings.get('genre_filter_mode', 'blacklist')
        genre_blacklist = [g.lower() for g in settings.get('genre_blacklist', [])]
        genre_whitelist = [g.lower() for g in settings.get('genre_whitelist', [])]
        if (genre_filter_mode == 'blacklist' and genre_blacklist) or (genre_filter_mode == 'whitelist' and genre_whitelist):
            artist_genres = []
            if primary_artist_id:
                try:
                    artist_info = spotify_client.artist(primary_artist_id)
                    artist_genres = [g.lower() for g in artist_info.get('genres', [])]
                except Exception as e: logger.warning(f"Tür filtresi: Sanatçı türleri alınamadı ({primary_artist_id}): {e}")
            if not artist_genres: logger.warning(f"Tür filtresi uygulanamıyor (türler yok): {song_name}. İzin veriliyor.")
            else:
                if genre_filter_mode == 'blacklist':
                    if any(genre in genre_blacklist for genre in artist_genres):
                        blocked_genre = next((genre for genre in artist_genres if genre in genre_blacklist), "?")
                        return False, f"'{blocked_genre}' türü kara listede."
                elif genre_filter_mode == 'whitelist':
                    if not genre_whitelist: return False, 'Tür beyaz listesi aktif ama boş.'
                    if not any(genre in genre_whitelist for genre in artist_genres): return False, 'Bu tür beyaz listede değil.'
        return True, "Filtrelerden geçti."
    except spotipy.SpotifyException as e:
        logger.error(f"Filtre kontrolü sırasında Spotify hatası (ID={track_id}): {e}")
        return False, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"Filtre kontrolü sırasında hata (ID={track_id}): {e}", exc_info=True)
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
    global auto_advance_enabled, settings, song_queue # song_queue global eklendi
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None

    audio_sinks_result = _run_command(['list_sinks'])
    audio_sinks = audio_sinks_result.get('sinks', []) if audio_sinks_result.get('success') else []
    default_audio_sink_name = audio_sinks_result.get('default_sink_name') if audio_sinks_result.get('success') else None
    if not audio_sinks_result.get('success'):
        flash(f"Ses cihazları listelenemedi: {audio_sinks_result.get('error', 'Bilinmeyen hata')}", "danger")

    if spotify:
        try:
            result = spotify.devices(); spotify_devices = result.get('devices', [])
            spotify_authenticated = True; session['spotify_authenticated'] = True
            try: user = spotify.current_user(); spotify_user = user.get('display_name', '?'); session['spotify_user'] = spotify_user
            except Exception as user_err: logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}"); session.pop('spotify_user', None)
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']; is_playing = playback.get('is_playing', False)
                    track_name = item.get('name', '?'); artists = item.get('artists', [])
                    artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
                    artist_ids = [a.get('id') for a in artists if a.get('id')]
                    images = item.get('album', {}).get('images', []); image_url = images[0].get('url') if images else None
                    currently_playing_info = {
                        'id': item.get('id'), 'name': track_name, 'artist': artist_name,
                        'artist_ids': artist_ids, 'image_url': image_url, 'is_playing': is_playing
                    }
                    logger.debug(f"Şu An Çalıyor: {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'}")
            except Exception as pb_err: logger.warning(f"Çalma durumu alınamadı: {pb_err}")
        except Exception as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e}")
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE); spotify_client = None
    else: spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)

    return render_template(
        'admin_panel.html',
        settings=settings, spotify_devices=spotify_devices, queue=song_queue,
        all_genres=ALLOWED_GENRES, spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        audio_sinks=audio_sinks, default_audio_sink_name=default_audio_sink_name,
        currently_playing_info=currently_playing_info, auto_advance_enabled=auto_advance_enabled
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
        settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        if 'active_spotify_connect_device_id' in request.form:
             new_spotify_device_id = request.form.get('active_spotify_connect_device_id')
             settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {settings['active_device_id']}")
        settings['genre_filter_mode'] = request.form.get('genre_filter_mode', 'blacklist')
        settings['artist_filter_mode'] = request.form.get('artist_filter_mode', 'blacklist')
        settings['song_filter_mode'] = request.form.get('song_filter_mode', 'blacklist')
        save_settings(settings);
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
        save_token(token_info); global spotify_client; spotify_client = None
        logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
        if session.get('admin_logged_in'): flash("Spotify yetkilendirmesi başarıyla tamamlandı!", "success"); return redirect(url_for('admin_panel'))
        else: return redirect(url_for('index'))
    except Exception as e: logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True); return "Token işlenirken bir hata oluştu.", 500

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track')
    logger.info(f"Arama isteği: '{search_query}' (Tip: {search_type})")
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400
    spotify = get_spotify_client()
    if not spotify: logger.error("Arama: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503
    try:
        if search_type == 'artist':
             results = spotify.search(q=search_query, type='artist', limit=10, market='TR')
             items = results.get('artists', {}).get('items', [])
             logger.info(f"Sanatçı arama sonucu: {len(items)} sanatçı.")
        elif search_type == 'track':
             results = spotify.search(q=search_query, type='track', limit=10, market='TR')
             items = results.get('tracks', {}).get('items', [])
             logger.info(f"Şarkı arama sonucu: {len(items)} şarkı.")
        else: return jsonify({'error': 'Geçersiz arama tipi.'}), 400
        search_results = []
        for item in items:
            if search_type == 'artist':
                 genres = item.get('genres', []); images = item.get('images', [])
                 search_results.append({'id': item.get('id'), 'name': item.get('name'), 'genres': genres, 'image': images[-1].get('url') if images else None})
            elif search_type == 'track':
                 artists = item.get('artists', []); album = item.get('album', {}); images = album.get('images', [])
                 artist_ids = [a.get('id') for a in artists if a.get('id')]
                 search_results.append({'id': item.get('id'), 'name': item.get('name'), 'artist': ', '.join([a.get('name') for a in artists]), 'artist_ids': artist_ids, 'album': album.get('name'), 'image': images[-1].get('url') if images else None})
        return jsonify({'results': search_results})
    except Exception as e: logger.error(f"Spotify araması hatası ({search_type}): {e}", exc_info=True); return jsonify({'error': 'Arama sırasında sorun oluştu.'}), 500

@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
    """Admin tarafından şarkı ekleme (Filtreleri atlar)."""
    global song_queue # global eklendi
    song_input = request.form.get('song_id', '').strip()
    if not song_input: flash("Şarkı ID/URL girin.", "warning"); return redirect(url_for('admin_panel'))
    song_id = song_input
    if 'https://developer.spotify.com/documentation/web-api/reference/add-to-queue2' in song_input or 'open.spotify.com/track/' in song_input:
        match = re.search(r'/track/([a-zA-Z0-9]+)', song_input)
        if match: song_id = match.group(1)
        else: logger.warning(f"Geçersiz Spotify URL: {song_input}"); flash("Geçersiz Spotify URL.", "danger"); return redirect(url_for('admin_panel'))
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning(f"Kuyruk dolu, admin ekleyemedi: {song_id}"); flash("Kuyruk dolu!", "warning"); return redirect(url_for('admin_panel'))
    spotify = get_spotify_client()
    if not spotify: logger.warning("Admin ekleme: Spotify gerekli"); flash("Spotify yetkilendirmesi gerekli.", "warning"); return redirect(url_for('spotify_auth'))
    try:
        song_info = spotify.track(song_id, market='TR')
        if not song_info: logger.warning(f"Admin ekleme: Şarkı bulunamadı ID={song_id}"); flash(f"Şarkı bulunamadı (ID: {song_id}).", "danger"); return redirect(url_for('admin_panel'))
        artists = song_info.get('artists'); artist_ids = [a.get('id') for a in artists if a.get('id')]
        song_queue.append({'id': song_id, 'name': song_info.get('name', '?'), 'artist': ', '.join([a.get('name') for a in artists]), 'artist_ids': artist_ids, 'added_by': 'admin', 'added_at': time.time()})
        logger.info(f"Şarkı eklendi (Admin - Filtresiz): {song_id} - {song_info.get('name')}")
        flash(f"'{song_info.get('name')}' eklendi.", "success"); update_time_profile(song_id, spotify)
    except spotipy.SpotifyException as e:
        logger.error(f"Admin eklerken Spotify hatası (ID={song_id}): {e}")
        if e.http_status == 401 or e.http_status == 403: flash("Spotify yetkilendirme hatası.", "danger"); return redirect(url_for('spotify_auth'))
        else: flash(f"Spotify hatası: {e.msg}", "danger")
    except Exception as e: logger.error(f"Admin eklerken genel hata (ID={song_id}): {e}", exc_info=True); flash("Şarkı eklenirken hata.", "danger")
    return redirect(url_for('admin_panel'))

# --- Queue Rotaları ---
@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Kullanıcı tarafından şarkı ekleme (Filtreler uygulanır)."""
    global settings, song_queue, user_requests # Gerekli globaller eklendi
    if not request.is_json: return jsonify({'error': 'Geçersiz format.'}), 400
    data = request.get_json(); track_id = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: track_id={track_id}")
    if not track_id: return jsonify({'error': 'Eksik ID.'}), 400
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning("Kuyruk dolu."); return jsonify({'error': 'Kuyruk dolu.'}), 429
    user_ip = request.remote_addr; max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: logger.warning(f"Limit aşıldı: {user_ip}"); return jsonify({'error': f'Limit aşıldı ({max_requests}).'}), 429
    spotify = get_spotify_client()
    if not spotify: logger.error("Ekleme: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503
    is_allowed, reason = check_song_filters(track_id, spotify)
    if not is_allowed:
        logger.info(f"Reddedildi ({reason}): {track_id}")
        return jsonify({'error': reason}), 403
    try:
        song_info = spotify.track(track_id, market='TR')
        if not song_info: return jsonify({'error': 'Şarkı bilgisi alınamadı.'}), 500
        song_spotify_id = song_info.get('id'); song_name = song_info.get('name', '?')
        artists = song_info.get('artists', []); artist_ids = [a.get('id') for a in artists if a.get('id')]
        artist_names = [a.get('name') for a in artists]
        logger.info(f"Filtrelerden geçti: {song_name}")
        update_time_profile(track_id, spotify)
        song_queue.append({'id': song_spotify_id, 'name': song_name, 'artist': ', '.join(artist_names), 'artist_ids': artist_ids, 'added_by': user_ip, 'added_at': time.time()})
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        logger.info(f"Şarkı eklendi (Kullanıcı: {user_ip}): {song_name}. Kuyruk: {len(song_queue)}")
        return jsonify({'success': True, 'message': f"'{song_name}' kuyruğa eklendi!"})
    except spotipy.SpotifyException as e:
        logger.error(f"Kullanıcı eklerken Spotify hatası (ID={track_id}): {e}")
        if e.http_status == 401 or e.http_status == 403: return jsonify({'error': 'Spotify yetkilendirme sorunu.'}), 503
        else: return jsonify({'error': f"Spotify hatası: {e.msg}"}), 500
    except Exception as e:
        logger.error(f"Kuyruğa ekleme hatası (ID: {track_id}): {e}", exc_info=True)
        return jsonify({'error': 'Şarkı eklenirken bilinmeyen bir sorun oluştu.'}), 500

@app.route('/remove-song/<song_id>', methods=['POST'])
@admin_login_required
def remove_song(song_id):
    global song_queue; initial_length = len(song_queue)
    song_queue = [song for song in song_queue if song.get('id') != song_id]
    if len(song_queue) < initial_length: logger.info(f"Şarkı kaldırıldı (Admin): ID={song_id}"); flash("Şarkı kaldırıldı.", "success")
    else: logger.warning(f"Kaldırılacak şarkı bulunamadı: ID={song_id}"); flash("Şarkı bulunamadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue, user_requests; song_queue = []; user_requests = {}
    logger.info("Kuyruk temizlendi (Admin)."); flash("Kuyruk temizlendi.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/queue')
def view_queue():
    global spotify_client, song_queue # song_queue global eklendi
    current_q = list(song_queue); currently_playing_info = None
    spotify = get_spotify_client()
    if spotify:
        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']; is_playing = playback.get('is_playing', False)
                track_name = item.get('name'); artists = item.get('artists', [])
                artist_name = ', '.join([a.get('name') for a in artists]); images = item.get('album', {}).get('images', [])
                image_url = images[-1].get('url') if images else None
                artist_ids = [a.get('id') for a in artists if a.get('id')]
                currently_playing_info = {'id': item.get('id'), 'name': track_name, 'artist': artist_name, 'artist_ids': artist_ids, 'image_url': image_url, 'is_playing': is_playing}
                logger.debug(f"Şu An Çalıyor (Kuyruk): {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'}")
        except spotipy.SpotifyException as e:
            logger.warning(f"Çalma durumu hatası (Kuyruk): {e}")
            if e.http_status == 401 or e.http_status == 403: spotify_client = None;
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        except Exception as e: logger.error(f"Çalma durumu genel hatası (Kuyruk): {e}", exc_info=True)
    queue_with_ids = []
    for song in current_q:
        if 'artist_ids' not in song:
             try:
                  track_info = spotify.track(song['id'], market='TR') if spotify else None
                  if track_info:
                       artists = track_info.get('artists', [])
                       song['artist_ids'] = [a.get('id') for a in artists if a.get('id')]
                  else: song['artist_ids'] = []
             except: song['artist_ids'] = []
        queue_with_ids.append(song)
    return render_template('queue.html', queue=queue_with_ids, currently_playing_info=currently_playing_info)

@app.route('/api/queue')
def api_get_queue():
    global song_queue # global eklendi
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
    if not device_path:
         mac_address = data.get('mac_address')
         if not mac_address: return jsonify({'success': False, 'error': 'device_path veya mac_address gerekli'}), 400
         else:
              logger.warning("MAC adresinden path bulunuyor...")
              discover_res = _run_command(['discover_bluetooth', '--duration', '0'])
              found_path = None
              if discover_res.get('success'):
                   for dev in discover_res.get('devices', []):
                        if dev.get('mac_address') == mac_address: found_path = dev.get('path'); break
              if not found_path: return jsonify({'success': False, 'error': f'MAC ({mac_address}) için path bulunamadı.'}), 404
              device_path = found_path
              logger.info(f"MAC {mac_address} için path bulundu: {device_path}")
    logger.info(f"API: Bluetooth eşleştirme/bağlama: {device_path} (ex.py)...")
    result = _run_command(['pair_bluetooth', '--path', device_path])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
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
    if not device_path:
         mac_address = data.get('mac_address')
         if not mac_address: return jsonify({'success': False, 'error': 'device_path veya mac_address gerekli'}), 400
         else:
              logger.warning("MAC adresinden path bulunuyor...")
              discover_res = _run_command(['discover_bluetooth', '--duration', '0'])
              found_path = None
              if discover_res.get('success'):
                   for dev in discover_res.get('devices', []):
                        if dev.get('mac_address') == mac_address: found_path = dev.get('path'); break
              if not found_path: return jsonify({'success': False, 'error': f'MAC ({mac_address}) için path bulunamadı.'}), 404
              device_path = found_path
              logger.info(f"MAC {mac_address} için path bulundu: {device_path}")
    logger.info(f"API: Bluetooth bağlantısını kesme: {device_path} (ex.py)...")
    result = _run_command(['disconnect_bluetooth', '--path', device_path])
    status_code = 200 if result.get('success') else 500
    final_result = result.copy()
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

# --- YENİ Filtre Yönetimi API Rotaları ---

@app.route('/api/block', methods=['POST'])
@admin_login_required
def api_block_item():
    """Hızlı engelleme: Sanatçı veya şarkıyı doğrudan kara listeye ekler."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    item_type = data.get('type')
    identifier = data.get('identifier')

    if not item_type or item_type not in ['artist', 'song']: return jsonify({'success': False, 'error': 'Geçersiz öğe tipi.'}), 400
    if not identifier or not identifier.startswith('spotify:'): return jsonify({'success': False, 'error': 'Geçersiz Spotify ID.'}), 400

    list_key = f"{item_type}_blacklist"
    try:
        current_settings = load_settings()
        target_list = current_settings.get(list_key, [])
        if identifier not in target_list:
            target_list.append(identifier)
            current_settings[list_key] = target_list
            save_settings(current_settings)
            settings = current_settings
            logger.info(f"Hızlı Engelleme: '{identifier}' ({item_type}) kara listeye eklendi.")
            return jsonify({'success': True, 'message': f"'{identifier}' kara listeye eklendi."})
        else:
            logger.info(f"Hızlı Engelleme: '{identifier}' ({item_type}) zaten kara listede.")
            return jsonify({'success': True, 'message': f"'{identifier}' zaten kara listede."})
    except Exception as e:
        logger.error(f"Hızlı engelleme hatası ({item_type}, {identifier}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': f"Öğe kara listeye eklenirken hata: {e}"}), 500

@app.route('/api/add-to-list', methods=['POST'])
@admin_login_required
def api_add_to_list():
    """Belirtilen filtre listesine öğe ekler."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    filter_type = data.get('filter_type')
    list_type = data.get('list_type')
    item = data.get('item')

    if filter_type not in ['genre', 'artist', 'song']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify({'success': False, 'error': 'Eklenecek öğe boş olamaz.'}), 400

    item = item.strip()
    if filter_type == 'genre': item = item.lower()

    list_key = f"{filter_type}_{list_type}"
    try:
        current_settings = load_settings()
        target_list = current_settings.get(list_key, [])
        if item not in target_list:
            target_list.append(item)
            current_settings[list_key] = target_list
            save_settings(current_settings)
            settings = current_settings
            logger.info(f"Listeye Ekleme: '{item}' -> '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item}' listeye eklendi.", 'updated_list': settings[list_key]})
        else:
            logger.info(f"Listeye Ekleme: '{item}' zaten '{list_key}' listesinde.")
            return jsonify({'success': True, 'message': f"'{item}' zaten listede.", 'updated_list': target_list})
    except Exception as e:
        logger.error(f"Listeye ekleme hatası ({list_key}, {item}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': f"Listeye öğe eklenirken hata: {e}"}), 500

@app.route('/api/remove-from-list', methods=['POST'])
@admin_login_required
def api_remove_from_list():
    """Belirtilen filtre listesinden öğe çıkarır."""
    global settings
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    filter_type = data.get('filter_type')
    list_type = data.get('list_type')
    item = data.get('item')

    if filter_type not in ['genre', 'artist', 'song']: return jsonify({'success': False, 'error': 'Geçersiz filtre tipi.'}), 400
    if list_type not in ['whitelist', 'blacklist']: return jsonify({'success': False, 'error': 'Geçersiz liste tipi.'}), 400
    if not item or not isinstance(item, str) or not item.strip(): return jsonify({'success': False, 'error': 'Çıkarılacak öğe boş olamaz.'}), 400

    item = item.strip()
    if filter_type == 'genre': item = item.lower()

    list_key = f"{filter_type}_{list_type}"
    try:
        current_settings = load_settings()
        target_list = current_settings.get(list_key, [])
        if item in target_list:
            target_list.remove(item)
            current_settings[list_key] = target_list
            save_settings(current_settings)
            settings = current_settings
            logger.info(f"Listeden Çıkarma: '{item}' <- '{list_key}'")
            return jsonify({'success': True, 'message': f"'{item}' listeden çıkarıldı.", 'updated_list': target_list})
        else:
            logger.info(f"Listeden Çıkarma: '{item}' zaten '{list_key}' listesinde değil.")
            return jsonify({'success': False, 'error': f"'{item}' listede bulunamadı.", 'updated_list': target_list}), 404
    except Exception as e:
        logger.error(f"Listeden çıkarma hatası ({list_key}, {item}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': f"Listeden öğe çıkarılırken hata: {e}"}), 500


# --- Arka Plan Şarkı Çalma İş Parçacığı ---
def background_queue_player():
    global spotify_client, song_queue, user_requests, settings, auto_advance_enabled
    logger.info("Arka plan şarkı çalma/öneri görevi başlatılıyor...")
    last_played_song_id = None; last_suggested_song_id = None
    while True:
        try:
            spotify = get_spotify_client()
            # Ayarları döngü içinde tekrar okumak yerine global 'settings'i kullanalım
            # current_settings = load_settings() # Her döngüde okumak yerine global kullan
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

            is_playing_now = False; current_track_id_now = None
            if current_playback:
                is_playing_now = current_playback.get('is_playing', False); item = current_playback.get('item')
                current_track_id_now = item.get('id') if item else None

            if song_queue and not is_playing_now and auto_advance_enabled:
                logger.info(f"Arka plan: Çalma durdu, otomatik ilerleme aktif. Kuyruktan çalınıyor...")
                next_song = song_queue.pop(0)
                if next_song.get('id') == last_played_song_id: logger.debug(f"Şarkı ({next_song.get('name')}) zaten son çalınandı, atlanıyor."); last_played_song_id = None; time.sleep(1); continue
                logger.info(f"Arka plan: Çalınacak: {next_song.get('name')} ({next_song.get('id')})")
                try:
                    spotify.start_playback(device_id=active_spotify_connect_device_id, uris=[f"spotify:track:{next_song['id']}"])
                    logger.info(f"===> Şarkı çalmaya başlandı: {next_song.get('name')}")
                    last_played_song_id = next_song['id']; last_suggested_song_id = None
                    user_ip = next_song.get('added_by')
                    if user_ip and user_ip != 'admin' and user_ip != 'auto-time': user_requests[user_ip] = max(0, user_requests.get(user_ip, 0) - 1); logger.debug(f"Kullanıcı {user_ip} limiti azaltıldı: {user_requests.get(user_ip)}")
                    time.sleep(1); continue
                except spotipy.SpotifyException as start_err:
                    logger.error(f"Arka plan: Şarkı başlatılamadı ({next_song.get('id')}): {start_err}")
                    song_queue.insert(0, next_song)
                    if start_err.http_status == 401 or start_err.http_status == 403: spotify_client = None;
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                    elif start_err.http_status == 404 and 'device_id' in str(start_err).lower():
                         logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device_id}) bulunamadı.");
                         settings['active_device_id'] = None; # Global settings'i güncelle
                         save_settings(settings) # Değişikliği kaydet
                    time.sleep(5); continue
                except Exception as start_err: logger.error(f"Arka plan: Şarkı başlatılırken genel hata ({next_song.get('id')}): {start_err}", exc_info=True); song_queue.insert(0, next_song); time.sleep(10); continue
            elif not song_queue and not is_playing_now and auto_advance_enabled: # Otomatik öneri ve ekleme
                suggested = suggest_song_for_time(spotify)
                if suggested and suggested.get('id') != last_suggested_song_id:
                    is_allowed, _ = check_song_filters(suggested['id'], spotify)
                    if is_allowed:
                        logger.info(f"Otomatik öneri filtreden geçti ve eklendi: {suggested['name']}")
                        artists = suggested.get('artists', []); artist_ids = [a.get('id') for a in artists if a.get('id')]
                        song_queue.append({'id': suggested['id'], 'name': suggested['name'], 'artist': suggested.get('artist', '?'), 'artist_ids': artist_ids, 'added_by': 'auto-time', 'added_at': time.time()})
                        last_suggested_song_id = suggested['id']
                    else:
                         logger.info(f"Otomatik öneri filtrelere takıldı: {suggested['name']}")
                         last_suggested_song_id = suggested['id']
            elif is_playing_now:
                 if current_track_id_now and current_track_id_now != last_played_song_id: logger.debug(f"Arka plan: Yeni şarkı algılandı: {current_track_id_now}"); last_played_song_id = current_track_id_now; last_suggested_song_id = None
            time.sleep(5)
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

    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
