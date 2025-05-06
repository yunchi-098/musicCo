import os
import json
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from .config import (
    TOKEN_FILE, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI, SPOTIFY_SCOPES
)

logger = logging.getLogger(__name__)

class SpotifyClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SpotifyClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        self.client = None
        self._load_token()
    
    def _load_token(self):
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    token_info = json.load(f)
                self.client = spotipy.Spotify(auth=token_info['access_token'])
                logger.info("Token başarıyla yüklendi")
            except Exception as e:
                logger.error(f"Token yüklenirken hata: {e}")
                self.client = None
    
    def get_client(self):
        if not self.client:
            try:
                self.client = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET,
                    redirect_uri=SPOTIFY_REDIRECT_URI,
                    scope=SPOTIFY_SCOPES,
                    cache_path=TOKEN_FILE
                ))
                logger.info("Yeni Spotify istemcisi oluşturuldu")
            except Exception as e:
                logger.error(f"Spotify istemcisi oluşturulurken hata: {e}")
                self.client = None
        return self.client
    
    def save_token(self, token_info):
        try:
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_info, f)
            logger.info(f"Token başarıyla kaydedildi: {TOKEN_FILE}")
            self.client = spotipy.Spotify(auth=token_info['access_token'])
        except Exception as e:
            logger.error(f"Token kaydedilirken hata: {e}")
    
    def remove_token(self):
        try:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            self.client = None
            logger.info("Token dosyası silindi")
        except Exception as e:
            logger.error(f"Token silinirken hata: {e}")
    
    def get_auth_url(self):
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SPOTIFY_SCOPES,
            cache_path=TOKEN_FILE
        )
        return auth_manager.get_authorize_url()
    
    def get_token_from_code(self, code):
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SPOTIFY_SCOPES,
            cache_path=TOKEN_FILE
        )
        return auth_manager.get_access_token(code)

# Singleton instance
spotify_client = SpotifyClient() 