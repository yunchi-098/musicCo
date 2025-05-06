import time
import logging
import threading
from .spotify_client import spotify_client
from .queue_manager import queue_manager
from .config import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

class Player:
    def __init__(self):
        self.auto_advance_enabled = DEFAULT_SETTINGS['auto_advance']
        self.auto_advance_delay = DEFAULT_SETTINGS['auto_advance_delay']
        self._stop_event = threading.Event()
        self._player_thread = None
    
    def start_auto_advance(self):
        if not self._player_thread or not self._player_thread.is_alive():
            self._stop_event.clear()
            self._player_thread = threading.Thread(target=self._auto_advance_loop)
            self._player_thread.daemon = True
            self._player_thread.start()
    
    def stop_auto_advance(self):
        self._stop_event.set()
        if self._player_thread:
            self._player_thread.join()
    
    def _auto_advance_loop(self):
        while not self._stop_event.is_set():
            try:
                if not self.auto_advance_enabled:
                    time.sleep(1)
                    continue
                
                spotify = spotify_client.get_client()
                if not spotify:
                    logger.warning("Spotify bağlantısı yok")
                    time.sleep(5)
                    continue
                
                current = spotify.current_playback()
                if not current or not current['is_playing']:
                    queue = queue_manager.get_queue()
                    if queue:
                        next_track = queue[0]
                        try:
                            spotify.start_playback(uris=[next_track['uri']])
                            queue_manager.remove_from_queue(next_track['uri'])
                            queue_manager.add_to_history(next_track)
                            logger.info(f"Otomatik geçiş: {next_track['name']}")
                        except Exception as e:
                            logger.error(f"Otomatik geçiş hatası: {e}")
                
                time.sleep(self.auto_advance_delay)
            except Exception as e:
                logger.error(f"Otomatik geçiş döngüsünde hata: {e}")
                time.sleep(5)
    
    def play_track(self, track_uri):
        spotify = spotify_client.get_client()
        if not spotify:
            return False
        
        try:
            spotify.start_playback(uris=[track_uri])
            return True
        except Exception as e:
            logger.error(f"Şarkı çalma hatası: {e}")
            return False
    
    def pause(self):
        spotify = spotify_client.get_client()
        if not spotify:
            return False
        
        try:
            spotify.pause_playback()
            return True
        except Exception as e:
            logger.error(f"Duraklatma hatası: {e}")
            return False
    
    def resume(self):
        spotify = spotify_client.get_client()
        if not spotify:
            return False
        
        try:
            spotify.start_playback()
            return True
        except Exception as e:
            logger.error(f"Devam ettirme hatası: {e}")
            return False
    
    def skip(self):
        spotify = spotify_client.get_client()
        if not spotify:
            return False
        
        try:
            spotify.next_track()
            return True
        except Exception as e:
            logger.error(f"Geçiş hatası: {e}")
            return False
    
    def set_volume(self, volume):
        spotify = spotify_client.get_client()
        if not spotify:
            return False
        
        try:
            spotify.volume(volume)
            return True
        except Exception as e:
            logger.error(f"Ses ayarlama hatası: {e}")
            return False

# Singleton instance
player = Player() 