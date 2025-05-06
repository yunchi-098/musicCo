import json
import logging
from functools import wraps
from flask import session, redirect, url_for, flash
from .config import SETTINGS_FILE, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Bu sayfaya erişmek için giriş yapmalısınız.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return DEFAULT_SETTINGS.copy()
    except Exception as e:
        logger.error(f"Ayarlar yüklenirken hata: {e}")
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Ayarlar kaydedilirken hata: {e}")
        return False

def format_track_info(track):
    """Şarkı bilgilerini formatlar"""
    if not track:
        return None
    
    artists = [artist['name'] for artist in track.get('artists', [])]
    return {
        'name': track.get('name', 'Bilinmeyen Şarkı'),
        'artists': ', '.join(artists) if artists else 'Bilinmeyen Sanatçı',
        'uri': track.get('uri', ''),
        'duration_ms': track.get('duration_ms', 0),
        'album': track.get('album', {}).get('name', 'Bilinmeyen Albüm'),
        'image_url': track.get('album', {}).get('images', [{}])[0].get('url', '')
    }

def format_artist_info(artist):
    """Sanatçı bilgilerini formatlar"""
    if not artist:
        return None
    
    return {
        'name': artist.get('name', 'Bilinmeyen Sanatçı'),
        'uri': artist.get('uri', ''),
        'image_url': artist.get('images', [{}])[0].get('url', '') if artist.get('images') else ''
    }

def format_playlist_info(playlist):
    """Çalma listesi bilgilerini formatlar"""
    if not playlist:
        return None
    
    return {
        'name': playlist.get('name', 'Bilinmeyen Çalma Listesi'),
        'uri': playlist.get('uri', ''),
        'image_url': playlist.get('images', [{}])[0].get('url', '') if playlist.get('images') else '',
        'tracks_count': playlist.get('tracks', {}).get('total', 0)
    } 