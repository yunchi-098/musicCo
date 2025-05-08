# -*- coding: utf-8 -*-
import os
import json
import logging
from flask import Flask, render_template, redirect, url_for
from src.config import config
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
    app.config.from_object(config[config_name])

    # Blueprint'leri kaydet
    app.register_blueprint(admin_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(spotify_bp)
    app.register_blueprint(audio_bp)

    # Ana sayfa route'u
    @app.route('/')
    def index():
        return render_template('index.html')

    # Admin sayfasına yönlendirme
    @app.route('/admin')
    def admin_redirect():
        return redirect(url_for('admin.login'))

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8080, debug=True)