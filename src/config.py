import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Temel dizin
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Spotify API Yapılandırması
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'
SPOTIFY_REDIRECT_URI = 'http://100.81.225.104:8080/callback'
SPOTIFY_SCOPES = [
    'user-read-playback-state',
    'user-modify-playback-state',
    'playlist-read-private',
    'user-read-currently-playing',
    'user-read-recently-played'
]

# Dosya Yolları
TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLACKLIST_FILE = 'blacklist.json'
QUEUE_FILE = 'queue.json'
HISTORY_FILE = 'history.json'

# Uygulama Ayarları
SECRET_KEY = os.urandom(24)
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

# Varsayılan Ayarlar
DEFAULT_SETTINGS = {
    'volume': 50,
    'crossfade': 5,
    'repeat': 'off',
    'shuffle': False,
    'equalizer': {
        'enabled': False,
        'preset': 'flat'
    }
}

# Bluetooth Ayarları
BLUETOOTH_SCAN_DURATION = 12
EX_SCRIPT_PATH = 'ex.py'

# Müzik Türleri
ALLOWED_GENRES = [
    'pop', 'rock', 'jazz', 'electronic', 'hip-hop',
    'classical', 'r&b', 'indie', 'turkish'
]

# Flask ayarları
SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')

# Varsayılan ayarlar
DEFAULT_SETTINGS = {
    'auto_advance': True,
    'auto_advance_delay': 5,
    'max_queue_size': 100,
    'max_history_size': 1000,
    'active_device_id': None,
    'volume': 50,
    'crossfade': 0,
    'repeat_mode': 'off',
    'shuffle': False
} 