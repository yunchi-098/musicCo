import json
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ..config import (
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI,
    SPOTIFY_SCOPES,
    TOKEN_FILE
)

logger = logging.getLogger(__name__)

class SpotifyService:
    def __init__(self):
        self._client = None
        self._token_info = None

    def get_client(self):
        """Spotify istemcisini döndürür veya oluşturur."""
        if self._client is None:
            token_info = self._get_token()
            if token_info:
                self._client = spotipy.Spotify(auth=token_info['access_token'])
        return self._client

    def _get_token(self):
        """Token bilgisini dosyadan okur."""
        try:
            with open(TOKEN_FILE, 'r') as f:
                self._token_info = json.load(f)
            return self._token_info
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def get_auth_url(self):
        """Spotify yetkilendirme URL'sini döndürür."""
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SPOTIFY_SCOPES
        )
        return sp_oauth.get_authorize_url()

    def get_token_from_code(self, code):
        """Yetkilendirme kodundan token alır."""
        try:
            sp_oauth = SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=SPOTIFY_SCOPES
            )
            token_info = sp_oauth.get_access_token(code)
            return token_info
        except Exception as e:
            logger.error(f"Token alınırken hata: {str(e)}")
            return None

    def save_token(self, token_info):
        """Token bilgisini dosyaya kaydeder."""
        try:
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_info, f)
            self._token_info = token_info
            return True
        except Exception as e:
            logger.error(f"Token kaydedilirken hata: {str(e)}")
            return False

    def refresh_token(self):
        """Token'ı yeniler."""
        if not self._token_info:
            return False

        try:
            sp_oauth = SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=SPOTIFY_SCOPES
            )
            token_info = sp_oauth.refresh_access_token(self._token_info['refresh_token'])
            return self.save_token(token_info)
        except Exception as e:
            logger.error(f"Token yenilenirken hata: {str(e)}")
            return False

spotify_service = SpotifyService() 