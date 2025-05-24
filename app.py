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
from dotenv import load_dotenv
import secrets
import hashlib
import socket
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
#import bluetooth
#import dbus
#from dbus.mainloop.glib import DBusGMainLoop
#from gi.repository import GLib
#import alsaaudio
import pylast  # Last.fm API için
import logging

# .env dosyasını yükle
load_dotenv()

# Last.fm API yapılandırması
LASTFM_API_KEY = os.getenv('LASTFM_API_KEY')
LASTFM_API_SECRET = os.getenv('LASTFM_API_SECRET')
LASTFM_USERNAME = os.getenv('LASTFM_USERNAME')

# Last.fm API istemcisini oluştur
lastfm_network = pylast.LastFMNetwork(
    api_key=LASTFM_API_KEY,
    api_secret=LASTFM_API_SECRET
)

# logger'ı yapılandır
logger = logging.getLogger("musicco")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Bu işlemi yapmak için giriş yapmalısınız.', 'warning')
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function


# Güvenlik kontrolleri
def check_env_variables():
    required_vars = [
        'SPOTIFY_CLIENT_ID',
        'SPOTIFY_CLIENT_SECRET',
        'SPOTIFY_REDIRECT_URI',
        'ADMIN_PASSWORD',
        'FLASK_SECRET_KEY'
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Eksik çevre değişkenleri: {', '.join(missing_vars)}")

# Güvenli şifre hash'leme fonksiyonu
def hash_password(password):
    """Şifreyi güvenli bir şekilde hashler."""
    try:
        logger.debug("Şifre hash'leme başladı")
        
        if not password:
            logger.error("Hash'lenecek şifre boş")
            return None
            
        # Salt oluştur
        salt = secrets.token_hex(16)
        logger.debug(f"Salt oluşturuldu, uzunluk: {len(salt)}")
        
        # Key oluştur
        key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            bytes.fromhex(salt),
            100000
        ).hex()
        logger.debug(f"Key oluşturuldu, uzunluk: {len(key)}")
        
        # Hash'lenmiş şifreyi oluştur
        hashed = f"{salt}${key}"
        logger.debug(f"Hash'lenmiş şifre oluşturuldu, uzunluk: {len(hashed)}")
        
        return hashed
        
    except Exception as e:
        logger.error(f"Şifre hash'leme sırasında beklenmeyen hata: {str(e)}", exc_info=True)
        return None

def verify_password(stored_password, provided_password):
    """Şifre doğrulaması yapar."""
    try:
        logger.debug("Şifre doğrulama başladı")
        
        # Giriş kontrolü
        if not stored_password:
            logger.error("Stored password boş")
            return False
        if not provided_password:
            logger.error("Provided password boş")
            return False
            
        # Hash formatı kontrolü
        if '$' not in stored_password:
            logger.error(f"Geçersiz stored password formatı: {stored_password[:10]}...")
            return False
            
        # Salt ve key ayırma
        try:
            salt, key = stored_password.split('$')
            logger.debug(f"Salt uzunluğu: {len(salt)}, Key uzunluğu: {len(key)}")
        except ValueError as e:
            logger.error(f"Salt/Key ayrıştırma hatası: {str(e)}")
            return False
            
        # Yeni key oluşturma
        try:
            new_key = hashlib.pbkdf2_hmac(
                'sha256',
                provided_password.encode('utf-8'),
                bytes.fromhex(salt),
                100000
            ).hex()
            logger.debug(f"Yeni key oluşturuldu, uzunluk: {len(new_key)}")
        except Exception as e:
            logger.error(f"Key oluşturma hatası: {str(e)}")
            return False
            
        # Karşılaştırma
        is_valid = key == new_key
        logger.debug(f"Şifre doğrulama sonucu: {'Başarılı' if is_valid else 'Başarısız'}")
        
        if not is_valid:
            logger.debug(f"Key karşılaştırma hatası: Stored key: {key[:10]}..., New key: {new_key[:10]}...")
            
        return is_valid
        
    except Exception as e:
        logger.error(f"Şifre doğrulama sırasında beklenmeyen hata: {str(e)}", exc_info=True)
        return False

# --- Yapılandırılabilir Ayarlar ---
# !!! BU BİLGİLERİ KENDİ SPOTIFY DEVELOPER BİLGİLERİNİZLE DEĞİŞTİRİN !!!
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI')
SPOTIFY_SCOPE = 'user-read-playback-state user-read-private user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = int(os.getenv('BLUETOOTH_SCAN_DURATION', 12))
EX_SCRIPT_PATH = 'ex.py'
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']

# Güvenlik ayarları
MAX_LOGIN_ATTEMPTS = 5
LOGIN_TIMEOUT = 300  # 5 dakika
SESSION_TIMEOUT = 3600  # 1 saat

# Global değişkenler
settings = {}
auto_advance_enabled = True
song_queue = []

def load_settings():
    """Ayarları settings.json dosyasından yükler."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'max_queue_length': 50,
            'max_user_requests': 3,
            'genre_filter_mode': 'blacklist',
            'artist_filter_mode': 'blacklist',
            'genre_blacklist': [],
            'genre_whitelist': [],
            'artist_blacklist': [],
            'artist_whitelist': [],
            'track_blacklist': [],
            'active_device_id': None
        }
    except Exception as e:
        logger.error(f"Ayarlar yüklenirken hata: {e}")
        return {}

def save_settings(new_settings):
    """Ayarları settings.json dosyasına kaydeder."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Ayarlar kaydedilirken hata: {e}")
        return False

# --- Flask Uygulamasını Başlat ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_TIMEOUT
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION
app.jinja_env.globals['ALLOWED_GENRES'] = ALLOWED_GENRES

# Login denemelerini takip etmek için
login_attempts = {}

# Başlangıçta ayarları yükle
settings = load_settings()

# Güvenli oturum yönetimi
@app.before_request
def before_request():
    if request.endpoint and 'static' not in request.endpoint:
        if session.get('admin_logged_in'):
            session.permanent = True
            if 'last_activity' in session:
                last_activity = datetime.fromisoformat(session['last_activity'])
                if (datetime.now() - last_activity).total_seconds() > SESSION_TIMEOUT:
                    session.clear()
                    flash('Oturum zaman aşımına uğradı. Lütfen tekrar giriş yapın.', 'warning')
                    return redirect(url_for('admin'))
            session['last_activity'] = datetime.now().isoformat()

def check_admin_password():
    """Admin şifresinin doğru formatta olup olmadığını kontrol eder."""
    stored_password = os.getenv('ADMIN_PASSWORD')
    if not stored_password:
        logger.error("ADMIN_PASSWORD çevre değişkeni bulunamadı!")
        return False
    
    try:
        # Şifre hash'lenmiş formatta değilse, hash'le
        if '$' not in stored_password:
            logger.info("Admin şifresi hash'lenmiş formatta değil, hash'leniyor...")
            hashed_password = hash_password(stored_password)
            if hashed_password:
                # .env dosyasını güncelle
                env_path = '.env'
                env_lines = []
                if os.path.exists(env_path):
                    with open(env_path, 'r') as f:
                        env_lines = f.readlines()
                
                updated_lines = []
                for line in env_lines:
                    if line.startswith('ADMIN_PASSWORD='):
                        updated_lines.append(f'ADMIN_PASSWORD={hashed_password}\n')
                    else:
                        updated_lines.append(line)
                
                with open(env_path, 'w') as f:
                    f.writelines(updated_lines)
                
                logger.info("Admin şifresi başarıyla hash'lendi ve kaydedildi.")
                return True
            return False
        return True
    except Exception as e:
        logger.error(f"Admin şifre kontrolü sırasında hata: {e}")
        return False

@app.route('/admin-login', methods=['POST'])
def admin_login():
    """Admin giriş isteğini işler."""
    try:
        ip = request.remote_addr
        logger.info(f"Admin giriş denemesi başladı (IP: {ip})")
        
        # Form verilerini kontrol et
        if 'password' not in request.form:
            logger.error("Şifre alanı form verilerinde bulunamadı")
            flash('Geçersiz form verisi.', 'danger')
            return redirect(url_for('admin'))
        
        provided_password = request.form.get('password', '').strip()
        if not provided_password:
            logger.error("Boş şifre girildi")
            flash('Şifre boş olamaz.', 'danger')
            return redirect(url_for('admin'))
        
        # Admin şifresini kontrol et
        stored_password = os.getenv('ADMIN_PASSWORD')
        if not stored_password:
            logger.error("ADMIN_PASSWORD çevre değişkeni bulunamadı")
            flash('Sistem yapılandırma hatası.', 'danger')
            return redirect(url_for('admin'))
        
        logger.debug(f"Stored password format: {'Hashlenmiş' if '$' in stored_password else 'Düz metin'}")
        
        # IP bazlı giriş denemesi kontrolü
        if ip in login_attempts:
            attempts, last_attempt = login_attempts[ip]
            logger.debug(f"Mevcut giriş denemeleri: {attempts}, Son deneme: {datetime.fromtimestamp(last_attempt)}")
            
            if attempts >= MAX_LOGIN_ATTEMPTS:
                time_passed = time.time() - last_attempt
                if time_passed < LOGIN_TIMEOUT:
                    remaining = int(LOGIN_TIMEOUT - time_passed)
                    logger.warning(f"Çok fazla başarısız deneme (IP: {ip}). Kalan bekleme süresi: {remaining} saniye")
                    flash(f'Çok fazla başarısız deneme. Lütfen {remaining} saniye bekleyin.', 'danger')
                    return redirect(url_for('admin'))
                else:
                    login_attempts[ip] = [0, time.time()]
                    logger.info(f"Bekleme süresi doldu, deneme sayacı sıfırlandı (IP: {ip})")
        
        # Şifre doğrulama
        if not stored_password or '$' not in stored_password:
            # Şifre hash'lenmemişse, hash'le
            logger.info("Admin şifresi hash'lenmemiş, hash'leniyor...")
            hashed_password = hash_password(stored_password)
            if not hashed_password:
                logger.error("Şifre hash'lenemedi")
                flash('Sistem yapılandırma hatası.', 'danger')
                return redirect(url_for('admin'))
            
            # .env dosyasını güncelle
            env_path = '.env'
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    env_lines = f.readlines()
                
                with open(env_path, 'w') as f:
                    for line in env_lines:
                        if line.startswith('ADMIN_PASSWORD='):
                            f.write(f'ADMIN_PASSWORD={hashed_password}\n')
                        else:
                            f.write(line)
                
                logger.info("Admin şifresi başarıyla hash'lendi ve kaydedildi")
                stored_password = hashed_password
        
        # Şifre doğrulama
        if verify_password(stored_password, provided_password):
            session['admin_logged_in'] = True
            session['last_activity'] = datetime.now().isoformat()
            if ip in login_attempts:
                del login_attempts[ip]
            logger.info(f"Admin girişi başarılı (IP: {ip})")
            flash("Yönetim paneline hoş geldiniz!", "success")
            return redirect(url_for('admin_panel'))
        else:
            # Başarısız giriş denemesini kaydet
            if ip not in login_attempts:
                login_attempts[ip] = [1, time.time()]
            else:
                login_attempts[ip][0] += 1
                login_attempts[ip][1] = time.time()
            
            logger.warning(f"Başarısız admin girişi denemesi (IP: {ip}, Deneme sayısı: {login_attempts[ip][0]})")
            flash("Yanlış şifre girdiniz.", "danger")
            return redirect(url_for('admin'))
            
    except Exception as e:
        logger.error(f"Admin girişi sırasında beklenmeyen hata: {str(e)}", exc_info=True)
        flash('Giriş işlemi sırasında bir hata oluştu.', 'danger')
        return redirect(url_for('admin'))

@app.route('/')
def index():
    """Ana sayfayı gösterir."""
    return render_template('index.html', allowed_genres=ALLOWED_GENRES)

@app.route('/admin')
def admin():
    """Admin giriş sayfasını veya paneli gösterir."""
    if session.get('admin_logged_in'): return redirect(url_for('admin_panel'))
    return render_template('admin.html')

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
    try:
        audio_sinks = []
        default_audio_sink_name = None
        # Debian için ses cihazlarını al
        result = subprocess.run(['pactl', 'list', 'sinks'], capture_output=True, text=True)
        if result.returncode == 0:
            current_sink = None
            for line in result.stdout.split('\n'):
                if 'Sink #' in line:
                    current_sink = line.split('#')[1].strip()
                elif 'Name:' in line and current_sink:
                    device_name = line.split(':')[1].strip()
                    audio_sinks.append({
                        'name': device_name,
                        'is_default': False
                    })
                elif 'State: RUNNING' in line and current_sink:
                    # Çalışan cihaz varsayılan olarak kabul edilir
                    default_audio_sink_name = device_name
                    for sink in audio_sinks:
                        if sink['name'] == device_name:
                            sink['is_default'] = True
                            break
    except Exception as e:
        logger.error(f"Ses cihazları listelenirken hata: {e}")
        flash(f"Ses cihazları listelenemedi: {str(e)}", "danger")

    if spotify:
        spotify_authenticated = True
        session['spotify_authenticated'] = True
        try:
            # Spotify cihazlarını al
            result = spotify.devices()
            spotify_devices = result.get('devices', [])
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
                            'id': track_uri,
                            'name': track_name,
                            'artist': artist_name,
                            'artist_ids': artist_uris,
                            'image_url': image_url,
                            'is_playing': is_playing,
                            'is_allowed': is_allowed
                        }
            except Exception as pb_err:
                logger.warning(f"Çalma durumu alınamadı: {pb_err}")

            # Kuyruğu filtrele
            for song in song_queue:
                song_uri = song.get('id')
                if song_uri and song_uri.startswith('spotify:track:'):
                    is_allowed, _ = check_song_filters(song_uri, spotify)
                    if is_allowed:
                        if 'artist_ids' in song and isinstance(song['artist_ids'], list):
                            song['artist_ids'] = [_ensure_spotify_uri(aid, 'artist') for aid in song['artist_ids']]
                        filtered_queue.append(song)

        except Exception as e:
            logger.error(f"Admin panelinde beklenmedik hata: {e}", exc_info=True)
            spotify_authenticated = False
            session['spotify_authenticated'] = False
            session.pop('spotify_user', None)
            flash("Beklenmedik bir hata oluştu.", "danger")
    else:
        spotify_authenticated = False
        session['spotify_authenticated'] = False
        session.pop('spotify_user', None)
        if not os.path.exists(TOKEN_FILE):
            flash("Spotify hesabınızı bağlamak için lütfen yetkilendirme yapın.", "info")

    return render_template(
        'admin_panel.html',
        settings=settings,
        spotify_devices=spotify_devices,
        queue=filtered_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        audio_sinks=audio_sinks,
        default_audio_sink_name=default_audio_sink_name,
        currently_playing_info=currently_playing_info,
        auto_advance_enabled=auto_advance_enabled
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

@app.route('/api/audio-sinks')
@admin_login_required
def api_audio_sinks():
    """Ses cihazlarını listeler"""
    try:
        return jsonify(get_audio_devices())
    except Exception as e:
        logger.error(f"Ses cihazları listelenirken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/set-audio-sink', methods=['POST'])
@admin_login_required
def api_set_audio_sink():
    """Varsayılan ses çıkışını ayarlar"""
    if not request.is_json:
        return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    
    data = request.get_json()
    sink_identifier = data.get('sink_identifier')
    
    if sink_identifier is None:
        return jsonify({'success': False, 'error': 'Sink tanımlayıcısı gerekli'}), 400
    
    try:
        # amixer ile ses çıkışını ayarla
        result = subprocess.run(['amixer', '-c', sink_identifier, 'set', 'Master', 'unmute'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': f'Ses çıkışı {sink_identifier} olarak ayarlandı',
                'sinks': get_audio_devices().get('devices', [])
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Ses çıkışı ayarlanamadı: {result.stderr}'
            })
    except Exception as e:
        logger.error(f"Ses çıkışı ayarlanırken hata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/discover-bluetooth', methods=['GET', 'POST'])
@admin_login_required
def api_discover_bluetooth():
    """Bluetooth cihazlarını tarar"""
    try:
        # GET isteğinde duration parametresini URL'den al, POST isteğinde JSON'dan al
        if request.method == 'GET':
            duration = int(request.args.get('duration', BLUETOOTH_SCAN_DURATION))
        else:
            data = request.get_json()
            duration = int(data.get('duration', BLUETOOTH_SCAN_DURATION))

        # Bluetooth adaptörünü bul
        nearby_devices = bluetooth.discover_devices(
            duration=duration,
            lookup_names=True,
            flush_cache=True,
            lookup_class=True
        )
        
        devices = []
        for addr, name, device_class in nearby_devices:
            devices.append({
                'name': name or 'Bilinmeyen Cihaz',
                'address': addr,
                'class': device_class,
                'paired': False,  # Bu bilgiyi DBus'tan alabiliriz
                'connected': False
            })
        
        return jsonify({'success': True, 'devices': devices})
    except bluetooth.BluetoothError as e:
        logger.error(f"Bluetooth tarama hatası: {str(e)}")
        return jsonify({'success': False, 'error': 'Bluetooth adaptörü bulunamadı veya erişilemedi'})
    except Exception as e:
        logger.error(f"Beklenmeyen Bluetooth hatası: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    """Bluetooth cihazı ile eşleşme yapar"""
    try:
        data = request.get_json()
        device_path = data.get('device_path')
        
        if not device_path:
            return jsonify({'success': False, 'error': 'Cihaz yolu belirtilmedi'})
        
        bus = dbus.SystemBus()
        device = dbus.Interface(bus.get_object('org.bluez', device_path), 'org.bluez.Device1')
        
        # Eşleşme ve bağlantı
        device.Pair()
        device.Connect()
        
        return jsonify({
            'success': True,
            'message': 'Cihaz başarıyla eşleştirildi ve bağlandı'
        })
    except dbus.exceptions.DBusException as e:
        logger.error(f"Bluetooth eşleşme hatası: {str(e)}")
        return jsonify({'success': False, 'error': 'Eşleşme başarısız oldu'})
    except Exception as e:
        logger.error(f"Beklenmeyen Bluetooth eşleşme hatası: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    """Bluetooth cihazı ile bağlantıyı keser"""
    try:
        data = request.get_json()
        device_path = data.get('device_path')
        
        if not device_path:
            return jsonify({'success': False, 'error': 'Cihaz yolu belirtilmedi'})
        
        bus = dbus.SystemBus()
        device = dbus.Interface(bus.get_object('org.bluez', device_path), 'org.bluez.Device1')
        
        # Bağlantıyı kes
        device.Disconnect()
        
        return jsonify({
            'success': True,
            'message': 'Cihaz bağlantısı kesildi'
        })
    except dbus.exceptions.DBusException as e:
        logger.error(f"Bluetooth bağlantı kesme hatası: {str(e)}")
        return jsonify({'success': False, 'error': 'Bağlantı kesilemedi'})
    except Exception as e:
        logger.error(f"Beklenmeyen Bluetooth bağlantı kesme hatası: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/switch-to-alsa', methods=['POST'])
@admin_login_required
def api_switch_to_alsa():
    """Varsayılan ses çıkışını ALSA uyumlu bir cihaza değiştir"""
    try:
        # ALSA cihazına geçiş yap
        result = _run_command(['python3', EX_SCRIPT_PATH, 'switch-to-alsa'])
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': 'ALSA ses çıkışına geçiş başarılı.',
                'sinks': result.get('sinks', []),
                'default_sink_name': result.get('default_sink_name')
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'ALSA geçişi başarısız.')
            })
    except Exception as e:
        logger.error(f"ALSA geçişi sırasında hata: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'ALSA geçişi sırasında hata: {str(e)}'
        })

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

@app.route('/remove-blocked-track', methods=['POST'])
@admin_login_required
def remove_blocked_track():
    """Engellenmiş bir şarkıyı kaldır"""
    track_uri = request.form.get('track_uri')
    if not track_uri:
        return jsonify({'success': False, 'error': 'Şarkı URI\'si gerekli'})

    global settings
    if track_uri and track_uri in settings.get('track_blacklist', []):
        settings['track_blacklist'].remove(track_uri)
        save_settings(settings)
        return jsonify({'success': True, 'message': 'Şarkı kara listeden kaldırıldı'})
    return jsonify({'success': False, 'error': 'Şarkı kara listede bulunamadı'})

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

def check_token_on_startup():
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client()
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Yetkilendirme gerekli olabilir.")

def start_queue_player():
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")

DB_PATH = os.getenv('DB_PATH', 'musicco.db')

def init_db():
    """SQLite veritabanını başlat ve gerekli tabloları oluştur"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # played_tracks tablosunu oluştur
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS played_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT,
                track_name TEXT,
                artist_name TEXT,
                played_at TEXT
            )
        """)
        
        conn.commit()
        logger.info("Veritabanı başarıyla başlatıldı")
        
    except sqlite3.Error as e:
        logger.error(f"Veritabanı başlatılırken hata: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def scrobble_to_lastfm(track_info):
    """Çalınan şarkıyı Last.fm'e kaydeder"""
    try:
        if not LASTFM_USERNAME:
            logger.warning("Last.fm kullanıcı adı yapılandırılmamış")
            return False

        user = lastfm_network.get_user(LASTFM_USERNAME)
        user.scrobble(
            artist=track_info.get('artist', 'Bilinmeyen Sanatçı'),
            title=track_info.get('name', 'Bilinmeyen Şarkı'),
            timestamp=int(time.time())
        )
        logger.info(f"Şarkı Last.fm'e kaydedildi: {track_info.get('name')} - {track_info.get('artist')}")
        return True
    except Exception as e:
        logger.error(f"Last.fm'e kayıt yapılırken hata: {e}")
        return False

def save_played_track(track_info):
    """Çalınan şarkıyı veritabanına ve Last.fm'e kaydeder"""
    try:
        logger.info(f"Kaydedilecek şarkı bilgileri: {track_info}")
        
        # Son çalınan şarkıyı kontrol et
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Son çalınan şarkıyı al
        cursor.execute("""
            SELECT track_id, played_at 
            FROM played_tracks 
            ORDER BY played_at DESC 
            LIMIT 1
        """)
        last_track = cursor.fetchone()
        
        if last_track:
            last_track_id, last_played_at = last_track
            last_played_time = datetime.fromisoformat(last_played_at)
            current_time = datetime.now()
            time_diff = current_time - last_played_time
            
            # track_id'yi doğru şekilde al
            current_track_id = track_info.get('id') or track_info.get('track_id', '')
            logger.info(f"Son çalınan şarkı ID: {last_track_id}, Şimdiki şarkı ID: {current_track_id}")
            logger.info(f"Son çalınma zamanı: {last_played_time}, Şimdiki zaman: {current_time}")
            logger.info(f"Geçen süre (saniye): {time_diff.total_seconds()}")
            
            # Eğer aynı şarkı son 5 saat içinde çalındıysa kaydetme
            if last_track_id == current_track_id and time_diff.total_seconds() < 300:
                logger.info(f"Şarkı son 5 dakika içinde çalındı, tekrar kaydedilmeyecek: {track_info.get('name', track_info.get('track_name', 'Bilinmeyen'))}")
                return
        
        # Yeni şarkıyı kaydet
        cursor.execute("""
            INSERT INTO played_tracks (track_id, track_name, artist_name, played_at)
            VALUES (?, ?, ?, ?)
        """, (
            track_info.get('id') or track_info.get('track_id', ''),
            track_info.get('name') or track_info.get('track_name', 'Bilinmeyen'),
            track_info.get('artist') or track_info.get('artist_name', 'Bilinmeyen'),
            datetime.now().isoformat()
        ))
        conn.commit()
        logger.info(f"Şarkı başarıyla kaydedildi: {track_info.get('name', track_info.get('track_name', 'Bilinmeyen'))}")
        
        # Last.fm'e kaydet
        scrobble_to_lastfm(track_info)
        
    except sqlite3.Error as e:
        logger.error(f"Şarkı kaydedilirken SQLite hatası: {e}")
        # Eğer tablo yoksa oluştur
        if "no such table" in str(e):
            init_db()
            # Tekrar kaydetmeyi dene
            try:
                cursor.execute("""
                    INSERT INTO played_tracks (track_id, track_name, artist_name, played_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    track_info.get('id') or track_info.get('track_id', ''),
                    track_info.get('name') or track_info.get('track_name', 'Bilinmeyen'),
                    track_info.get('artist') or track_info.get('artist_name', 'Bilinmeyen'),
                    datetime.now().isoformat()
                ))
                conn.commit()
                logger.info(f"Tablo oluşturuldu ve şarkı kaydedildi: {track_info.get('name', track_info.get('track_name', 'Bilinmeyen'))}")
                
                # Last.fm'e kaydet
                scrobble_to_lastfm(track_info)
                
            except sqlite3.Error as retry_e:
                logger.error(f"İkinci denemede şarkı kaydedilirken SQLite hatası: {retry_e}")
    finally:
        if 'conn' in locals():
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

def check_port_availability(port):
    """Port kullanılabilirliğini kontrol eder"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('0.0.0.0', port))
        sock.close()
        return True
    except:
        return False

def require_port_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('port_authorized'):
            flash('Port erişimi için yetkilendirme gerekli.', 'warning')
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/authorize-port', methods=['POST'])
@admin_login_required
def authorize_port():
    """Port erişimi için yetkilendirme"""
    password = request.form.get('port_password')
    if password == os.getenv('PORT_AUTH_PASSWORD'):
        session['port_authorized'] = True
        flash('Port erişimi yetkilendirildi.', 'success')
    else:
        flash('Geçersiz port yetkilendirme şifresi.', 'danger')
    return redirect(url_for('admin_panel'))

def is_port_open(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0

def toggle_port(port):
    if is_port_open(port):
        # Portu kapat
        subprocess.run(['sudo', 'iptables', '-A', 'INPUT', '-p', 'tcp', '--dport', str(port), '-j', 'DROP'])
        return False
    else:
        # Portu aç
        subprocess.run(['sudo', 'iptables', '-D', 'INPUT', '-p', 'tcp', '--dport', str(port), '-j', 'DROP'])
        return True

@app.route('/toggle-port', methods=['POST'])
@admin_login_required
def toggle_port_route():
    port = int(os.getenv('PORT', 9187))
    try:
        is_open = toggle_port(port)
        return jsonify({
            'success': True,
            'message': f'Port {port} {"açıldı" if is_open else "kapatıldı"}',
            'is_open': is_open
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

def get_bluetooth_devices():
    """Bluetooth cihazlarını tarar ve listeler"""
    try:
        # Bluetooth servisinin çalışıp çalışmadığını kontrol et
        bus = dbus.SystemBus()
        manager = dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
        objects = manager.GetManagedObjects()
        
        devices = []
        for path, interfaces in objects.items():
            if 'org.bluez.Device1' in interfaces:
                device = interfaces['org.bluez.Device1']
                devices.append({
                    'name': device.get('Name', 'Bilinmeyen Cihaz'),
                    'address': device.get('Address', ''),
                    'paired': device.get('Paired', False),
                    'connected': device.get('Connected', False),
                    'path': path
                })
        
        return {'success': True, 'devices': devices}
    except dbus.exceptions.DBusException as e:
        logger.error(f"Bluetooth DBus hatası: {str(e)}")
        return {'success': False, 'error': 'Bluetooth servisi çalışmıyor'}
    except Exception as e:
        logger.error(f"Bluetooth tarama hatası: {str(e)}")
        return {'success': False, 'error': str(e)}

def get_audio_devices():
    """Ses cihazlarını sistem komutları ile listeler"""
    try:
        # aplay komutu ile ses cihazlarını listele
        result = subprocess.run(['aplay', '-l'], capture_output=True, text=True)
        if result.returncode == 0:
            devices = []
            for line in result.stdout.split('\n'):
                if 'card' in line and 'device' in line:
                    # Cihaz bilgilerini parse et
                    parts = line.split(':')
                    if len(parts) >= 2:
                        device_info = parts[1].strip()
                        devices.append({
                            'name': device_info,
                            'type': 'output',
                            'id': line.split()[1]  # card numarası
                        })
            return {'success': True, 'devices': devices}
        else:
            return {'success': False, 'error': 'Ses cihazları listelenemedi'}
    except Exception as e:
        logger.error(f"Ses cihazları listelenirken hata: {str(e)}")
        return {'success': False, 'error': str(e)}

# Otomatik başlatma için yeni fonksiyon
def auto_start_playback():
    """Sistem başladığında otomatik olarak çalmayı başlatır"""
    try:
        spotify = get_spotify_client()
        if spotify:
            # Çalma durumunu kontrol et
            playback = spotify.current_playback()
            if not playback or not playback.get('is_playing'):
                # Çalmayı başlat
                spotify.start_playback()
                logger.info("Otomatik çalma başlatıldı")
    except Exception as e:
        logger.error(f"Otomatik çalma başlatılırken hata: {e}")

def get_lastfm_recommendations(limit=10):
    """Last.fm'den kullanıcının dinleme geçmişine göre öneriler alır"""
    try:
        if not LASTFM_USERNAME:
            logger.error("Last.fm kullanıcı adı yapılandırılmamış")
            return []

        # Kullanıcının son çalınan şarkılarını al
        user = lastfm_network.get_user(LASTFM_USERNAME)
        recent_tracks = user.get_recent_tracks(limit=50)
        
        # Son çalınan şarkılardan sanatçıları topla
        artists = set()
        for track in recent_tracks:
            if track.track.artist:
                artists.add(track.track.artist.name)
        
        # Her sanatçı için benzer sanatçıları al
        similar_artists = set()
        for artist in list(artists)[:5]:  # İlk 5 sanatçı için
            try:
                artist_obj = lastfm_network.get_artist(artist)
                similar = artist_obj.get_similar(limit=5)
                for similar_artist in similar:
                    similar_artists.add(similar_artist.item.name)
            except Exception as e:
                logger.warning(f"Sanatçı için benzer sanatçılar alınamadı: {artist}, Hata: {e}")
        
        # Benzer sanatçıların en popüler şarkılarını al
        recommendations = []
        for artist_name in list(similar_artists)[:10]:  # İlk 10 benzer sanatçı
            try:
                artist = lastfm_network.get_artist(artist_name)
                top_tracks = artist.get_top_tracks(limit=5)
                for track in top_tracks:
                    if len(recommendations) >= limit:
                        break
                    recommendations.append({
                        'artist': artist_name,
                        'track': track.item.title
                    })
            except Exception as e:
                logger.warning(f"Sanatçı için popüler şarkılar alınamadı: {artist_name}, Hata: {e}")
        
        return recommendations[:limit]
    except Exception as e:
        logger.error(f"Last.fm önerileri alınırken hata: {e}")
        return []

@app.route('/api/recommendations')
@admin_login_required
def get_recommendations():
    """Last.fm'den önerileri alır ve Spotify URI'lerine dönüştürür"""
    try:
        recommendations = get_lastfm_recommendations(limit=10)
        if not recommendations:
            return jsonify({'success': False, 'error': 'Öneri alınamadı'}), 500

        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı yok'}), 503

        # Last.fm önerilerini Spotify'da ara
        spotify_recommendations = []
        for rec in recommendations:
            try:
                # Spotify'da şarkıyı ara
                results = spotify.search(
                    q=f"artist:{rec['artist']} track:{rec['track']}",
                    type='track',
                    limit=1,
                    market='TR'
                )
                
                if results['tracks']['items']:
                    track = results['tracks']['items'][0]
                    # Filtreleri kontrol et
                    is_allowed, _ = check_song_filters(track['uri'], spotify)
                    if is_allowed:
                        spotify_recommendations.append({
                            'id': track['uri'],
                            'name': track['name'],
                            'artist': rec['artist'],
                            'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None
                        })
            except Exception as e:
                logger.warning(f"Şarkı Spotify'da bulunamadı: {rec['artist']} - {rec['track']}, Hata: {e}")

        return jsonify({
            'success': True,
            'recommendations': spotify_recommendations
        })

    except Exception as e:
        logger.error(f"Öneriler alınırken hata: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/lastfm/settings', methods=['GET'])
@admin_login_required
def get_lastfm_settings():
    """Last.fm ayarlarını getirir"""
    try:
        settings = {
            'api_key': LASTFM_API_KEY,
            'api_secret': LASTFM_API_SECRET,
            'username': LASTFM_USERNAME,
            'is_configured': bool(LASTFM_API_KEY and LASTFM_API_SECRET and LASTFM_USERNAME)
        }
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        logger.error(f"Last.fm ayarları alınırken hata: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/lastfm/settings', methods=['POST'])
@admin_login_required
def update_lastfm_settings():
    """Last.fm ayarlarını günceller"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Geçersiz veri formatı'}), 400

        api_key = data.get('api_key')
        api_secret = data.get('api_secret')
        username = data.get('username')

        if not all([api_key, api_secret, username]):
            return jsonify({'success': False, 'error': 'Tüm alanlar gerekli'}), 400

        # .env dosyasını güncelle
        env_path = '.env'
        env_lines = []
        
        # Mevcut .env dosyasını oku
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                env_lines = f.readlines()

        # Last.fm ayarlarını güncelle veya ekle
        lastfm_settings = {
            'LASTFM_API_KEY': api_key,
            'LASTFM_API_SECRET': api_secret,
            'LASTFM_USERNAME': username
        }

        updated_lines = []
        lastfm_keys_found = set()

        # Mevcut satırları güncelle
        for line in env_lines:
            line = line.strip()
            if not line or line.startswith('#'):
                updated_lines.append(line)
                continue

            key, value = line.split('=', 1)
            if key in lastfm_settings:
                lastfm_keys_found.add(key)
                updated_lines.append(f"{key}={lastfm_settings[key]}")
            else:
                updated_lines.append(line)

        # Eksik Last.fm ayarlarını ekle
        for key, value in lastfm_settings.items():
            if key not in lastfm_keys_found:
                updated_lines.append(f"{key}={value}")

        # .env dosyasını güncelle
        with open(env_path, 'w') as f:
            f.write('\n'.join(updated_lines))

        # Global değişkenleri güncelle
        global LASTFM_API_KEY, LASTFM_API_SECRET, LASTFM_USERNAME, lastfm_network
        LASTFM_API_KEY = api_key
        LASTFM_API_SECRET = api_secret
        LASTFM_USERNAME = username
        lastfm_network = pylast.LastFMNetwork(
            api_key=LASTFM_API_KEY,
            api_secret=LASTFM_API_SECRET
        )

        return jsonify({
            'success': True,
            'message': 'Last.fm ayarları güncellendi',
            'settings': {
                'api_key': api_key,
                'api_secret': api_secret,
                'username': username,
                'is_configured': True
            }
        })

    except Exception as e:
        logger.error(f"Last.fm ayarları güncellenirken hata: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/lastfm/test-connection')
@admin_login_required
def test_lastfm_connection():
    """Last.fm bağlantısını test eder"""
    try:
        if not all([LASTFM_API_KEY, LASTFM_API_SECRET, LASTFM_USERNAME]):
            return jsonify({
                'success': False,
                'error': 'Last.fm ayarları eksik'
            }), 400

        # Last.fm bağlantısını test et
        user = lastfm_network.get_user(LASTFM_USERNAME)
        recent_tracks = user.get_recent_tracks(limit=1)
        
        return jsonify({
            'success': True,
            'message': 'Last.fm bağlantısı başarılı',
            'user_info': {
                'username': LASTFM_USERNAME,
                'recent_track': str(recent_tracks[0].track) if recent_tracks else None
            }
        })

    except Exception as e:
        logger.error(f"Last.fm bağlantı testi sırasında hata: {e}")
        return jsonify({
            'success': False,
            'error': f'Last.fm bağlantı hatası: {str(e)}'
        }), 500

# Spotify istemcisi için global değişken
spotify_client = None

def get_spotify_client():
    """Spotify istemcisini oluşturur veya mevcut istemciyi döndürür."""
    global spotify_client
    
    # Eğer istemci zaten varsa ve token geçerliyse, onu döndür
    if spotify_client:
        try:
            # Token'ın geçerliliğini kontrol et
            spotify_client.current_user()
            return spotify_client
        except:
            # Token geçersizse, istemciyi sıfırla
            spotify_client = None
    
    # Token dosyasını kontrol et
    if not os.path.exists(TOKEN_FILE):
        logger.warning("Spotify token dosyası bulunamadı.")
        return None
    
    try:
        # Token bilgilerini yükle
        with open(TOKEN_FILE, 'r') as f:
            token_info = json.load(f)
        
        # Token'ın süresi dolmuş mu kontrol et
        if token_info.get('expires_at', 0) < time.time():
            logger.info("Spotify token'ı süresi dolmuş, yenileniyor...")
            auth_manager = get_spotify_auth()
            token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            save_token(token_info)
        
        # Yeni istemci oluştur
        auth_manager = get_spotify_auth()
        auth_manager.token_info = token_info
        spotify_client = spotipy.Spotify(auth_manager=auth_manager)
        
        # Test et
        spotify_client.current_user()
        logger.info("Spotify istemcisi başarıyla oluşturuldu.")
        return spotify_client
        
    except Exception as e:
        logger.error(f"Spotify istemcisi oluşturulurken hata: {e}")
        spotify_client = None
        return None

def get_spotify_auth():
    """Spotify yetkilendirme yöneticisini oluşturur."""
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        cache_path=TOKEN_FILE
    )

def save_token(token_info):
    """Spotify token bilgilerini dosyaya kaydeder."""
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_info, f)
        return True
    except Exception as e:
        logger.error(f"Token kaydedilirken hata: {e}")
        return False

def load_token():
    """Spotify token bilgilerini dosyadan yükler."""
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Token yüklenirken hata: {e}")
    return None

def _run_command(command):
    """Sistem komutlarını çalıştırır ve sonuçları döndürür."""
    try:
        logger.debug(f"Komut çalıştırılıyor: {command}")
        
        # Komut listesi değilse, listeye çevir
        if isinstance(command, str):
            command = command.split()
            
        # Komutu çalıştır
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Çıktıyı parse et
        output = result.stdout.strip()
        logger.debug(f"Komut çıktısı: {output[:100]}...")
        
        # Komut tipine göre işle
        if command[0] == 'list_sinks':
            sinks = []
            default_sink = None
            
            for line in output.split('\n'):
                if 'Default Sink' in line:
                    default_sink = line.split(':')[1].strip()
                elif 'Sink' in line and '#' in line:
                    sink_info = line.split('#')[1].strip()
                    sinks.append({
                        'name': sink_info,
                        'is_default': sink_info == default_sink
                    })
            
            return {
                'success': True,
                'sinks': sinks,
                'default_sink_name': default_sink
            }
            
        elif command[0] == 'discover_bluetooth':
            devices = []
            for line in output.split('\n'):
                if 'Device' in line:
                    device_info = line.split('Device')[1].strip()
                    devices.append({
                        'name': device_info,
                        'paired': 'Paired' in line,
                        'connected': 'Connected' in line
                    })
            
            return {
                'success': True,
                'devices': devices
            }
            
        else:
            return {
                'success': True,
                'output': output
            }
            
    except subprocess.CalledProcessError as e:
        logger.error(f"Komut çalıştırma hatası: {str(e)}")
        return {
            'success': False,
            'error': f"Komut hatası: {e.stderr}"
        }
    except Exception as e:
        logger.error(f"Beklenmeyen hata: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': f"Beklenmeyen hata: {str(e)}"
        }

if __name__ == '__main__':
    try:
        # Çevre değişkenlerini kontrol et
        check_env_variables()
        
        logger.info("=================================================")
        logger.info("Mekan Müzik Sistemi başlatılıyor...")
        logger.info("=================================================")

        # Veritabanını başlat
        init_db()

        # Token kontrolü
        check_token_on_startup()

        # Arka plan görevini başlat
        start_queue_player()

        # Otomatik çalmayı başlat
        auto_start_playback()

        port = int(os.getenv('PORT', 9187))
        
        # Port kullanılabilirlik kontrolü
        if not check_port_availability(port):
            logger.error(f"Port {port} zaten kullanımda veya erişilemez!")
            exit(1)
            
        logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişilebilir.")
        logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişilebilir.")
        app.run(host='0.0.0.0', port=port, debug=False)
    except ValueError as e:
        logger.error(f"Başlatma hatası: {e}")
        exit(1)
