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
        return render_template('index.html')
    
    @app.route('/admin/login', methods=['POST'])
    def admin_login():
        password = request.form.get('password')
        if password == app.config['ADMIN_PASSWORD']:
            session['admin'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Geçersiz şifre'})
    
    @app.route('/admin/control')
    def admin_control():
        if not session.get('admin'):
            return redirect(url_for('index'))
        return render_template('admin.html')
    
    @app.route('/api/play', methods=['POST'])
    def play():
        track_uri = request.form.get('track_uri')
        if not track_uri:
            return jsonify({'success': False, 'error': 'Track URI gerekli'})
        
        track_uri = _ensure_spotify_uri(track_uri, 'track')
        if not track_uri:
            return jsonify({'success': False, 'error': 'Geçersiz Track URI'})
        
        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı yok'})
        
        # Filtreleri kontrol et
        is_allowed, message = check_filters(track_uri, spotify)
        if not is_allowed:
            return jsonify({'success': False, 'error': message})
        
        result = _run_command(['play', track_uri])
        if result.get('success'):
            update_time_profile(track_uri, spotify)
        return jsonify(result)
    
    @app.route('/api/pause', methods=['POST'])
    def pause():
        return jsonify(_run_command(['pause']))
    
    @app.route('/api/resume', methods=['POST'])
    def resume():
        return jsonify(_run_command(['resume']))
    
    @app.route('/api/next', methods=['POST'])
    def next_track():
        return jsonify(_run_command(['next']))
    
    @app.route('/api/previous', methods=['POST'])
    def previous_track():
        return jsonify(_run_command(['previous']))
    
    @app.route('/api/volume', methods=['POST'])
    def set_volume():
        volume = request.form.get('volume')
        if not volume:
            return jsonify({'success': False, 'error': 'Ses seviyesi gerekli'})
        return jsonify(_run_command(['volume', volume]))
    
    @app.route('/api/queue', methods=['GET'])
    def get_queue():
        with queue_lock:
            return jsonify({'queue': queue})
    
    @app.route('/api/queue/add', methods=['POST'])
    def add_to_queue():
        track_uri = request.form.get('track_uri')
        if not track_uri:
            return jsonify({'success': False, 'error': 'Track URI gerekli'})
        
        track_uri = _ensure_spotify_uri(track_uri, 'track')
        if not track_uri:
            return jsonify({'success': False, 'error': 'Geçersiz Track URI'})
        
        spotify = get_spotify_client()
        if not spotify:
            return jsonify({'success': False, 'error': 'Spotify bağlantısı yok'})
        
        # Filtreleri kontrol et
        is_allowed, message = check_filters(track_uri, spotify)
        if not is_allowed:
            return jsonify({'success': False, 'error': message})
        
        with queue_lock:
            if len(queue) >= settings['max_queue_length']:
                return jsonify({'success': False, 'error': 'Kuyruk dolu'})
            queue.append(track_uri)
            update_time_profile(track_uri, spotify)
        return jsonify({'success': True})
    
    @app.route('/api/queue/remove', methods=['POST'])
    def remove_from_queue():
        index = request.form.get('index')
        if not index:
            return jsonify({'success': False, 'error': 'İndeks gerekli'})
        
        try:
            index = int(index)
        except ValueError:
            return jsonify({'success': False, 'error': 'Geçersiz indeks'})
        
        with queue_lock:
            if 0 <= index < len(queue):
                queue.pop(index)
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'Geçersiz indeks'})
    
    @app.route('/api/settings', methods=['GET'])
    def get_settings():
        return jsonify(settings)
    
    @app.route('/api/settings', methods=['POST'])
    def update_settings():
        if not session.get('admin'):
            return jsonify({'success': False, 'error': 'Yetkisiz erişim'})
        
        new_settings = request.get_json()
        if not new_settings:
            return jsonify({'success': False, 'error': 'Geçersiz ayarlar'})
        
        settings.update(new_settings)
        save_settings(settings)
        return jsonify({'success': True})
    
    @app.route('/api/time-profiles', methods=['GET'])
    def get_time_profiles():
        return jsonify(time_profiles)
    
    @app.route('/api/auto-advance', methods=['POST'])
    def toggle_auto_advance():
        global auto_advance_enabled
        auto_advance_enabled = not auto_advance_enabled
        return jsonify({'success': True, 'auto_advance': auto_advance_enabled})

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)