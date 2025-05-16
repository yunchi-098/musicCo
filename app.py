# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse ve URI kontrolü için (artık helpers'ta _ensure_spotify_uri içinde)
# subprocess # ex.py ve spotifyd için (artık helpers'ta _run_command içinde)
from functools import wraps

from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
# from spotipy.oauth2 import SpotifyOAuth # Artık spotify_client_handler içinde
import traceback # Hata ayıklama için eklendi

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
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
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
def get_current_time_profile():
    hour = time.localtime().tm_hour
    if 6 <= hour < 12: return 'sabah'
    elif 12 <= hour < 18: return 'oglen'
    elif 18 <= hour < 24: return 'aksam'
    else: return 'gece'

def update_time_profile(track_uri, spotify):
    global time_profiles
    if not spotify or not track_uri or not track_uri.startswith('spotify:track:'):
        logger.warning(f"update_time_profile: geçersiz parametre veya format: {track_uri}"); return
    profile_name = get_current_time_profile()
    logger.debug(f"'{profile_name}' profili güncelleniyor, track_uri: {track_uri}")
    try:
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

def suggest_song_for_time(spotify):
    global time_profiles, song_queue
    if not spotify: logger.warning("suggest_song_for_time: spotify istemcisi eksik."); return None
    profile_name = get_current_time_profile(); profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None

    seed_tracks = []; seed_artists = []
    for entry in reversed(profile_data):
        if entry.get('track_uri') and entry['track_uri'] not in seed_tracks:
            seed_tracks.append(entry['track_uri'])
        if entry.get('artist_uri') and entry['artist_uri'] not in seed_artists:
            seed_artists.append(entry['artist_uri'])
        if len(seed_tracks) + len(seed_artists) >= 5: break

    if not seed_tracks and not seed_artists: logger.warning(f"'{profile_name}' profili öneri için tohum içermiyor."); return None

    try:
        logger.info(f"'{profile_name}' için öneri isteniyor: seeds_tracks={seed_tracks}, seeds_artists={seed_artists}")
        recs = spotify.recommendations(seed_tracks=seed_tracks, seed_artists=seed_artists, limit=5, market='TR')
        if recs and recs.get('tracks'):
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
        return True, "Filtrelerden geçti."

    except spotipy.SpotifyException as e:
        logger.error(f"Filtre kontrolü sırasında Spotify hatası (URI={track_uri}): {e}")
        if e.http_status == 400: return False, f"Geçersiz Spotify Şarkı URI: {track_uri}"
        return False, f"Spotify hatası: {e.msg}"
    except Exception as e:
        logger.error(f"Filtre kontrolü sırasında hata (URI={track_uri}): {e}", exc_info=True)
        return False, "Filtre kontrolü sırasında bilinmeyen hata."

# --- Flask Rotaları (İçleri güncellenmeli) ---

@app.route('/')
def index():
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
@admin_login_required
def logout():
    clear_spotify_client() # spotify_client = None yerine
    session.clear()
    logger.info("Admin çıkışı yapıldı."); flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    global auto_advance_enabled, settings, song_queue # settings artık load_app_settings ile yükleniyor
    spotify = get_spotify_client() # spotify_client_handler'dan
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None
    filtered_queue = []

    audio_sinks_result = _run_command(['list_sinks'], config.EX_SCRIPT_PATH) # config.EX_SCRIPT_PATH eklendi
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
        if e.http_status == 401 or e.http_status == 403: 
            flash('Spotify yetkilendirme hatası.', 'danger');
            clear_spotify_client()
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
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

@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    global settings # save_app_settings için settings global'ini kullanıyoruz
    spotify = get_spotify_client()
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        result = spotify.devices(); devices = result.get('devices', [])
        logger.info(f"Spotify Connect Cihazları yenilendi: {len(devices)} cihaz")
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device and not any(d['id'] == active_spotify_connect_device for d in devices):
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
    return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings_route(): # İsim çakışmasını önlemek için
    global settings
    try:
        logger.info("Ayarlar güncelleniyor...")
        current_settings = settings.copy() # Mevcut global settings'i kopyala
        current_settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        current_settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        if 'active_spotify_connect_device_id' in request.form:
             new_spotify_device_id = request.form.get('active_spotify_connect_device_id')
             current_settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {current_settings['active_device_id']}")
        current_settings['genre_filter_mode'] = request.form.get('genre_filter_mode', 'blacklist')
        current_settings['artist_filter_mode'] = request.form.get('artist_filter_mode', 'blacklist')
        current_settings['track_filter_mode'] = request.form.get('song_filter_mode', 'blacklist') # Formdan song gelir ama track olarak saklanır
        
        save_app_settings(current_settings) # app_settings modülünden
        settings = load_app_settings() # Global settings'i güncelle
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

@app.route('/search', methods=['POST'])
def search():
    global settings # settings global'i
    search_query = request.form.get('search_query')
    search_type = request.form.get('type', 'track')
    logger.info(f"Arama isteği: '{search_query}' (Tip: {search_type})")
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400

    spotify = get_spotify_client() # spotify_client_handler'dan
    if not spotify: 
        logger.error("Arama: Spotify istemcisi yok.")
        return jsonify({'error': 'Spotify bağlantısı yok.'}), 503

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
                artist_filter_mode = settings.get('artist_filter_mode', 'blacklist')
                artist_blacklist_uris = settings.get('artist_blacklist', [])
                artist_whitelist_uris = settings.get('artist_whitelist', [])

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

@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
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


@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
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

@app.route('/remove-song/<path:song_id_str>', methods=['POST'])
@admin_login_required
def remove_song(song_id_str):
    global song_queue;
    song_uri_to_remove = _ensure_spotify_uri(song_id_str, 'track') # helpers'dan
    if not song_uri_to_remove:
        flash(f"Geçersiz şarkı ID formatı: {song_id_str}", "danger")
        return redirect(url_for('admin_panel'))

    logger.debug(f"Kuyruktan kaldırılacak URI: {song_uri_to_remove}")
    original_length = len(song_queue)
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

@app.route('/api/set-audio-sink', methods=['POST'])
@admin_login_required
def api_set_audio_sink():
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
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

@app.route('/api/restart-spotifyd', methods=['POST'])
@admin_login_required
def api_restart_spotifyd():
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

    list_key = f"{actual_item_type}_blacklist"
    try:
        current_settings = settings.copy() # Global settings'i kullan
        target_list = current_settings.get(list_key, [])
        if item_uri not in target_list:
            target_list.append(item_uri); current_settings[list_key] = target_list; 
            save_app_settings(current_settings) # app_settings'den
            settings = load_app_settings() # Global settings'i güncelle
            logger.info(f"Hızlı Engelleme: '{item_uri}' ({actual_item_type}) kara listeye eklendi.")
            return jsonify({'success': True, 'message': f"'{identifier}' kara listeye eklendi."})
        else:
            logger.info(f"Hızlı Engelleme: '{item_uri}' ({actual_item_type}) zaten kara listede.")
            return jsonify({'success': True, 'message': f"'{identifier}' zaten kara listede."})
    except Exception as e: logger.error(f"Hızlı engelleme hatası ({actual_item_type}, {item_uri}): {e}", exc_info=True); return jsonify({'success': False, 'error': f"Öğe kara listeye eklenirken hata: {e}"}), 500

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

@app.route('/api/spotify/details', methods=['POST'])
@admin_login_required
def api_spotify_details():
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
    while True:
        try:
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

def start_queue_player():
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("=================================================")
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