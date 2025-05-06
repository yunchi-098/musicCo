import json
import logging
from ..config import QUEUE_FILE, HISTORY_FILE

logger = logging.getLogger(__name__)

class QueueService:
    def __init__(self):
        self._queue = []
        self._history = []
        self._load_queue()
        self._load_history()

    def _load_queue(self):
        """Kuyruk bilgisini dosyadan yükler."""
        try:
            with open(QUEUE_FILE, 'r') as f:
                self._queue = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._queue = []

    def _save_queue(self):
        """Kuyruk bilgisini dosyaya kaydeder."""
        try:
            with open(QUEUE_FILE, 'w') as f:
                json.dump(self._queue, f)
            return True
        except Exception as e:
            logger.error(f"Kuyruk kaydedilirken hata: {str(e)}")
            return False

    def _load_history(self):
        """Geçmiş bilgisini dosyadan yükler."""
        try:
            with open(HISTORY_FILE, 'r') as f:
                self._history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._history = []

    def _save_history(self):
        """Geçmiş bilgisini dosyaya kaydeder."""
        try:
            with open(HISTORY_FILE, 'w') as f:
                json.dump(self._history, f)
            return True
        except Exception as e:
            logger.error(f"Geçmiş kaydedilirken hata: {str(e)}")
            return False

    def get_queue(self):
        """Mevcut kuyruğu döndürür."""
        return self._queue

    def add_to_queue(self, track):
        """Kuyruğa şarkı ekler."""
        self._queue.append(track)
        return self._save_queue()

    def remove_from_queue(self, track_id):
        """Kuyruktan şarkı çıkarır."""
        self._queue = [t for t in self._queue if t['id'] != track_id]
        return self._save_queue()

    def clear_queue(self):
        """Kuyruğu temizler."""
        self._queue = []
        return self._save_queue()

    def get_history(self):
        """Çalma geçmişini döndürür."""
        return self._history

    def add_to_history(self, track):
        """Geçmişe şarkı ekler."""
        self._history.append(track)
        if len(self._history) > 100:  # Geçmişi 100 şarkı ile sınırla
            self._history = self._history[-100:]
        return self._save_history()

    def clear_history(self):
        """Geçmişi temizler."""
        self._history = []
        return self._save_history()

queue_service = QueueService() 