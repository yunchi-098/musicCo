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

from src.config import (
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

def create_app(config_name='development'):
    """Flask uygulamasını oluşturur ve yapılandırır."""
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # Blueprint'leri kaydet
    app.register_blueprint(admin_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(spotify_bp)
    app.register_blueprint(audio_bp)

    # Route'ları kaydet
    register_routes(app)

    return app

def register_routes(app):
    @app.route('/')
    def index():
        """Ana sayfayı gösterir."""
        try:
            # Spotify bağlantı durumunu kontrol et
            spotify_authenticated = spotify_service.is_authenticated()
            
            # Şu an çalan şarkı bilgisini al
            currently_playing_info = None
            if spotify_authenticated:
                try:
                    current = spotify_service.get_current_playback()
                    if current and current.get('item'):
                        currently_playing_info = {
                            'name': current['item']['name'],
                            'artist': current['item']['artists'][0]['name'],
                            'is_playing': current['is_playing']
                        }
                except Exception as e:
                    logger.error(f"Şu an çalan şarkı bilgisi alınamadı: {str(e)}")

            # Kuyruk bilgisini al
            queue = queue_service.get_queue()

            return render_template('index.html',
                                 spotify_authenticated=spotify_authenticated,
                                 currently_playing_info=currently_playing_info,
                                 queue=queue)
        except Exception as e:
            logger.error(f"Ana sayfa yüklenirken hata: {str(e)}")
            flash('Bir hata oluştu. Lütfen tekrar deneyin.', 'error')
            return redirect(url_for('admin.admin'))

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8080, debug=True)