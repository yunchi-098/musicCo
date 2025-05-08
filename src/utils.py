import os
import json
import time
import subprocess
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import current_app
from threading import Lock

# Global değişkenler
queue = []
queue_lock = Lock()
settings = {}
time_profiles = {}
auto_advance_enabled = True

def _run_command(command):
    """ex.py scriptini çalıştırır ve sonucu döndürür."""
    try:
        script_path = current_app.config['EX_SCRIPT_PATH']
        result = subprocess.run(['python3', script_path] + command, capture_output=True, text=True)
        return {'success': True, 'output': result.stdout}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_spotify_auth():
    """Spotify kimlik doğrulama yöneticisini oluşturur."""
    try:
        return SpotifyOAuth(
            client_id=current_app.config['SPOTIFY_CLIENT_ID'],
            client_secret=current_app.config['SPOTIFY_CLIENT_SECRET'],
            redirect_uri=current_app.config['SPOTIFY_REDIRECT_URI'],
            scope=current_app.config['SPOTIFY_SCOPE']
        )
    except Exception as e:
        return None

def get_spotify_client():
    """Spotify API istemcisini oluşturur ve döndürür."""
    try:
        auth_manager = get_spotify_auth()
        if not auth_manager:
            return None
        return spotipy.Spotify(auth_manager=auth_manager)
    except Exception as e:
        return None

def load_token():
    """Spotify token'ını dosyadan yükler."""
    try:
        if os.path.exists(current_app.config['TOKEN_FILE']):
            with open(current_app.config['TOKEN_FILE'], 'r') as f:
                return json.load(f)
    except:
        pass
    return None

def save_token(token):
    """Spotify token'ını dosyaya kaydeder."""
    try:
        with open(current_app.config['TOKEN_FILE'], 'w') as f:
            json.dump(token, f)
    except:
        pass

def _ensure_spotify_uri(uri_or_url, expected_type='track'):
    """URL veya URI'yi Spotify URI'sine dönüştürür."""
    if not uri_or_url:
        return None
    
    # Eğer zaten bir URI ise
    if uri_or_url.startswith(f'spotify:{expected_type}:'):
        return uri_or_url
    
    # URL'den URI'ye dönüştür
    try:
        if 'open.spotify.com' in uri_or_url:
            parts = uri_or_url.split('/')
            if len(parts) >= 3:
                return f'spotify:{expected_type}:{parts[-1].split("?")[0]}'
    except:
        pass
    
    return None

def check_filters(track_uri, spotify):
    """Şarkının filtreleri geçip geçmediğini kontrol eder."""
    try:
        track = spotify.track(track_uri)
        if not track:
            return False, "Şarkı bulunamadı"
        
        # Tür kontrolü
        if settings.get('allowed_genres'):
            artist = spotify.artist(track['artists'][0]['id'])
            genres = artist['genres']
            if not any(genre in settings['allowed_genres'] for genre in genres):
                return False, "Bu türde şarkılar izin verilmiyor"
        
        # Kara liste kontrolü
        if track_uri in settings.get('blacklist', []):
            return False, "Bu şarkı kara listede"
        
        return True, ""
    except Exception as e:
        return False, str(e)

def update_time_profile(track_uri, spotify):
    """Şarkının zaman profilini günceller."""
    try:
        track = spotify.track(track_uri)
        if not track:
            return
        
        current_hour = time.localtime().tm_hour
        if current_hour not in time_profiles:
            time_profiles[current_hour] = {}
        
        if track_uri not in time_profiles[current_hour]:
            time_profiles[current_hour][track_uri] = 1
        else:
            time_profiles[current_hour][track_uri] += 1
    except:
        pass

def load_settings():
    """Ayarları dosyadan yükler."""
    global settings
    try:
        if os.path.exists(current_app.config['SETTINGS_FILE']):
            with open(current_app.config['SETTINGS_FILE'], 'r') as f:
                settings = json.load(f)
        else:
            settings = current_app.config['DEFAULT_SETTINGS'].copy()
    except:
        settings = current_app.config['DEFAULT_SETTINGS'].copy()

def save_settings(settings):
    """Ayarları dosyaya kaydeder."""
    try:
        with open(current_app.config['SETTINGS_FILE'], 'w') as f:
            json.dump(settings, f)
    except:
        pass