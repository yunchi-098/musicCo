#şarkı blackliste ekleme # <-- This comment seems irrelevant now but kept as original
# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Spotify URL parse ve URI kontrolü için
import subprocess # ex.py ve spotifyd için
from functools import wraps
# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi
from threading import Lock
from src import (
    spotify_client,
    queue_manager,
    player,
    admin_login_required,
    load_settings,
    save_settings,
    format_track_info,
    format_artist_info,
    format_playlist_info,
    TOKEN_FILE,
    SETTINGS_FILE,
    BLACKLIST_FILE,
    QUEUE_FILE,
    HISTORY_FILE,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI,
    SECRET_KEY,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    DEFAULT_SETTINGS,
    SPOTIFY_SCOPES
)
from src.routes.admin import admin_bp
from src.routes.player import player_bp
from src.routes.queue import queue_bp
from src.routes.spotify import spotify_bp
from src.routes.audio import audio_bp

# Logging ayarları
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

def create_app():
    """Flask uygulamasını oluşturur ve yapılandırır."""
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # Blueprint'leri kaydet
    app.register_blueprint(admin_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(spotify_bp)
    app.register_blueprint(audio_bp)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8080, debug=True)