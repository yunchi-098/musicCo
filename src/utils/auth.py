import json
import logging
from functools import wraps
from flask import session, redirect, url_for, flash
from ..config import SETTINGS_FILE, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

def admin_login_required(f):
    """Admin girişi gerektiren rotalar için dekoratör."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Bu sayfaya erişmek için giriş yapmalısınız.', 'warning')
            return redirect(url_for('admin.admin'))
        return f(*args, **kwargs)
    return decorated_function

def load_settings():
    """Ayarları dosyadan yükler."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
        return settings
    except (FileNotFoundError, json.JSONDecodeError):
        # Varsayılan ayarları kaydet ve döndür
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS

def save_settings(settings):
    """Ayarları dosyaya kaydeder."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Ayarlar kaydedilirken hata: {str(e)}")
        return False 