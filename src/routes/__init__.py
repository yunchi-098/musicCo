from .admin import admin_bp
from .player import player_bp
from .queue import queue_bp
from .spotify import spotify_bp
from .audio import audio_bp

__all__ = [
    'admin_bp',
    'player_bp',
    'queue_bp',
    'spotify_bp',
    'audio_bp'
] 