import os

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'default_insecure_key_please_change')
    
    # Spotify API settings
    SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'
    SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'
    SPOTIFY_REDIRECT_URI = 'http://100.81.225.104:8080/callback'
    SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'
    
    # File paths
    TOKEN_FILE = 'spotify_token.json'
    SETTINGS_FILE = 'settings.json'
    BLACKLIST_FILE = 'blacklist.json'
    QUEUE_FILE = 'queue.json'
    HISTORY_FILE = 'history.json'
    EX_SCRIPT_PATH = 'ex.py'
    
    # Other settings
    BLUETOOTH_SCAN_DURATION = 12
    ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
    
    # Admin settings
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123")
    
    # Default settings
    DEFAULT_SETTINGS = {
        'max_queue_length': 100,
        'auto_advance': True,
        'allowed_genres': ALLOWED_GENRES,
        'blacklist': []
    }
    
    # Spotify scopes
    SPOTIFY_SCOPES = [
        'user-read-playback-state',
        'user-modify-playback-state',
        'playlist-read-private',
        'user-read-currently-playing',
        'user-read-recently-played'
    ]

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

class TestingConfig(Config):
    TESTING = True
    DEBUG = True

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
} 