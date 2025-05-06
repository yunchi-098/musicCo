import json
import logging
from .config import QUEUE_FILE, HISTORY_FILE, BLACKLIST_FILE

logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self):
        self.queue = []
        self.history = []
        self.blacklist = []
        self._load_data()
    
    def _load_data(self):
        try:
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                    self.queue = json.load(f)
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            if os.path.exists(BLACKLIST_FILE):
                with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                    self.blacklist = json.load(f)
        except Exception as e:
            logger.error(f"Veri yüklenirken hata: {e}")
    
    def _save_queue(self):
        try:
            with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Kuyruk kaydedilirken hata: {e}")
    
    def _save_history(self):
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Geçmiş kaydedilirken hata: {e}")
    
    def _save_blacklist(self):
        try:
            with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.blacklist, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Kara liste kaydedilirken hata: {e}")
    
    def add_to_queue(self, track):
        self.queue.append(track)
        self._save_queue()
    
    def remove_from_queue(self, track_uri):
        self.queue = [t for t in self.queue if t['uri'] != track_uri]
        self._save_queue()
    
    def clear_queue(self):
        self.queue = []
        self._save_queue()
    
    def add_to_history(self, track):
        self.history.append(track)
        if len(self.history) > 1000:  # Geçmiş boyutunu sınırla
            self.history = self.history[-1000:]
        self._save_history()
    
    def add_to_blacklist(self, artist_uri, artist_name):
        if not any(a['uri'] == artist_uri for a in self.blacklist):
            self.blacklist.append({'uri': artist_uri, 'name': artist_name})
            self._save_blacklist()
    
    def remove_from_blacklist(self, artist_uri):
        self.blacklist = [a for a in self.blacklist if a['uri'] != artist_uri]
        self._save_blacklist()
    
    def is_artist_blacklisted(self, artist_uri):
        return any(a['uri'] == artist_uri for a in self.blacklist)
    
    def get_queue(self):
        return self.queue
    
    def get_history(self):
        return self.history
    
    def get_blacklist(self):
        return self.blacklist

# Singleton instance
queue_manager = QueueManager() 