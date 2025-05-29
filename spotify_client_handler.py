# spotify_client_handler.py
import os
import json
import time
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import config # Yeni oluşturduğumuz config.py'dan

logger = logging.getLogger(__name__)

# Bu modül içinde yönetilecek global bir Spotify client örneği
_spotify_client_instance = None

def load_spotify_token():
    """Token'ı dosyadan yükler."""
    if os.path.exists(config.TOKEN_FILE):
        try:
            with open(config.TOKEN_FILE, 'r', encoding='utf-8') as f:
                token_info = json.load(f)
            if 'access_token' in token_info and 'refresh_token' in token_info:
                logger.info(f"Token dosyadan başarıyla yüklendi: {config.TOKEN_FILE}")
                return token_info
            else:
                logger.warning(f"Token dosyasında ({config.TOKEN_FILE}) eksik anahtarlar var. Dosya siliniyor.")
                try: os.remove(config.TOKEN_FILE)
                except OSError as rm_err: logger.error(f"Token dosyası silinemedi: {rm_err}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Token dosyası ({config.TOKEN_FILE}) bozuk JSON içeriyor: {e}. Dosya siliniyor.")
            try: os.remove(config.TOKEN_FILE)
            except OSError as rm_err: logger.error(f"Bozuk token dosyası silinemedi: {rm_err}")
            return None
        except Exception as e:
            logger.error(f"Token dosyası okuma hatası ({config.TOKEN_FILE}): {e}", exc_info=True)
            return None
    else:
        logger.info(f"Token dosyası bulunamadı: {config.TOKEN_FILE}")
        return None

def save_spotify_token(token_info):
    """Token'ı dosyaya kaydeder."""
    try:
        if not token_info or 'access_token' not in token_info or 'refresh_token' not in token_info:
            logger.error("Kaydedilecek token bilgisi eksik veya geçersiz.")
            return False
        with open(config.TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_info, f, indent=4)
        logger.info(f"Token başarıyla dosyaya kaydedildi: {config.TOKEN_FILE}")
        return True
    except Exception as e:
        logger.error(f"Token kaydetme hatası ({config.TOKEN_FILE}): {e}", exc_info=True)
        return False

def create_spotify_oauth_manager():
    """SpotifyOAuth nesnesini oluşturur."""
    if not config.SPOTIFY_CLIENT_ID or config.SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not config.SPOTIFY_CLIENT_SECRET or config.SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not config.SPOTIFY_REDIRECT_URI or config.SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.critical("KRİTİK HATA: Spotify API bilgileri (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) config.py içinde doğru şekilde ayarlanmamış!")
        raise ValueError("Spotify API bilgileri eksik veya yanlış!")
    logger.debug(f"SpotifyOAuth oluşturuluyor. Redirect URI: {config.SPOTIFY_REDIRECT_URI}")
    return SpotifyOAuth(
        client_id=config.SPOTIFY_CLIENT_ID,
        client_secret=config.SPOTIFY_CLIENT_SECRET,
        redirect_uri=config.SPOTIFY_REDIRECT_URI,
        scope=config.SPOTIFY_SCOPE,
        open_browser=False, # Sunucu tarafı için tarayıcı açmamalı
        cache_path=None # Token yönetimini kendimiz yapıyoruz
    )

def get_spotify_client(force_refresh=False):
    """Mevcut Spotify istemcisini döndürür veya yenisini oluşturur/yeniler."""
    global _spotify_client_instance
    if _spotify_client_instance and not force_refresh:
        try:
            _spotify_client_instance.current_user() # Basit bir test çağrısı
            logger.debug("Mevcut Spotify istemcisi geçerli.")
            return _spotify_client_instance
        except spotipy.SpotifyException as e:
            logger.warning(f"Mevcut Spotify istemcisi ile hata ({e.http_status}): {e.msg}. Yeniden oluşturulacak.")
            _spotify_client_instance = None # Hata durumunda sıfırla
        except Exception as e: # Örneğin ağ hatası
            logger.error(f"Mevcut Spotify istemcisi ile bilinmeyen bir test hatası: {e}. Yeniden oluşturulacak.", exc_info=True)
            _spotify_client_instance = None

    token_info = load_spotify_token()
    if not token_info:
        logger.info("Geçerli token bulunamadı. Yetkilendirme gerekli.")
        return None

    try:
        auth_manager = create_spotify_oauth_manager()
    except ValueError as e: # API bilgileri eksikse
        logger.error(f"Spotify yetkilendirme yöneticisi oluşturulamadı: {e}")
        return None

    if auth_manager.is_token_expired(token_info):
        logger.info("Spotify token süresi dolmuş, yenileniyor...")
        refresh_token_val = token_info.get('refresh_token')
        if not refresh_token_val:
            logger.error("Refresh token bulunamadı. Token dosyası silinip yeniden yetkilendirme denenmeli.")
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
            return None
        try:
            auth_manager.token = token_info # Spotipy'nin iç state'ini ayarlamak için
            new_token_info = auth_manager.refresh_access_token(refresh_token_val)
            if not new_token_info:
                logger.error("Token yenilenemedi (API'den boş yanıt?). Token dosyası silinip yeniden yetkilendirme denenmeli.")
                if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
                return None
            
            # new_token_info sadece access_token ve expires_at içerebilir, refresh_token'ı eski token'dan almamız gerekebilir.
            # Spotipy'nin refresh_access_token'ı tam token_info objesini döndürmeli.
            if not isinstance(new_token_info, dict) or 'access_token' not in new_token_info:
                 logger.error(f"Token yenileme beklenmedik formatta veri döndürdü: {type(new_token_info)}. Token dosyası silinip yeniden yetkilendirme denenmeli.")
                 if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
                 return None

            logger.info("Token başarıyla yenilendi.")
            if not save_spotify_token(new_token_info): # Kaydetme işlemi yeni token'ı tam olarak almalı
                logger.error("Yenilenen token kaydedilemedi!")
            token_info = new_token_info # Güncel token ile devam et
        except spotipy.SpotifyOauthError as oauth_err:
            logger.error(f"Token yenileme sırasında OAuth hatası: {oauth_err}. Refresh token geçersiz olabilir. Token dosyası siliniyor.")
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
            return None
        except Exception as refresh_err:
            logger.error(f"Token yenileme sırasında beklenmedik hata: {refresh_err}", exc_info=True)
            return None # Yenileme başarısız olursa client oluşturma

    access_token = token_info.get('access_token')
    if not access_token:
        logger.error("Token bilgisinde access_token bulunamadı.")
        return None

    new_client = spotipy.Spotify(auth=access_token)
    try:
        user_info = new_client.current_user() # İstemcinin çalışıp çalışmadığını kontrol et
        logger.info(f"Spotify istemcisi başarıyla oluşturuldu/doğrulandı. Kullanıcı: {user_info.get('display_name', '?')}")
        _spotify_client_instance = new_client # Başarılı istemciyi sakla
        return _spotify_client_instance
    except spotipy.SpotifyException as e:
        logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası ({e.http_status}): {e.msg}. Token geçersiz olabilir.")
        if e.http_status == 401 or e.http_status == 403: # Yetkilendirme hatası
            logger.warning("Yetkilendirme hatası alındı. Token dosyası siliniyor.")
            if os.path.exists(config.TOKEN_FILE): os.remove(config.TOKEN_FILE)
        _spotify_client_instance = None # Başarısızsa sıfırla
        return None
    except Exception as e:
        logger.error(f"Yeni Spotify istemcisi ile doğrulama sırasında bilinmeyen hata: {e}", exc_info=True)
        _spotify_client_instance = None
        return None

def clear_spotify_client():
    """Force clears the cached Spotify client instance."""
    global _spotify_client_instance
    _spotify_client_instance = None
    logger.info("Spotify client instance cleared.")