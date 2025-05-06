from flask import Blueprint, jsonify, request, redirect, url_for, session
import logging
from ..services.spotify_service import spotify_service
from ..utils.auth import admin_login_required
from ..utils.formatters import format_track_info, format_artist_info, format_playlist_info

logger = logging.getLogger(__name__)
spotify_bp = Blueprint('spotify', __name__)

@spotify_bp.route('/login')
def login():
    """Spotify giriş sayfasına yönlendirir."""
    auth_url = spotify_service.get_auth_url()
    return redirect(auth_url)

@spotify_bp.route('/callback')
def callback():
    """Spotify yetkilendirme callback'ini işler."""
    try:
        code = request.args.get('code')
        if not code:
            return jsonify({'error': 'Yetkilendirme kodu bulunamadı'}), 400

        token_info = spotify_service.get_token_from_code(code)
        if not token_info:
            return jsonify({'error': 'Token alınamadı'}), 500

        if spotify_service.save_token(token_info):
            return redirect(url_for('admin.admin_panel'))
        else:
            return jsonify({'error': 'Token kaydedilemedi'}), 500
    except Exception as e:
        logger.error(f"Callback işlenirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@spotify_bp.route('/search')
@admin_login_required
def search():
    """Spotify'da arama yapar."""
    try:
        query = request.args.get('q')
        if not query:
            return jsonify({'error': 'Arama sorgusu gerekli'}), 400

        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        results = spotify.search(query, limit=20, type='track,artist,playlist')
        
        formatted_results = {
            'tracks': [format_track_info(track) for track in results.get('tracks', {}).get('items', [])],
            'artists': [format_artist_info(artist) for artist in results.get('artists', {}).get('items', [])],
            'playlists': [format_playlist_info(playlist) for playlist in results.get('playlists', {}).get('items', [])]
        }
        
        return jsonify(formatted_results)
    except Exception as e:
        logger.error(f"Arama yapılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@spotify_bp.route('/devices')
@admin_login_required
def get_devices():
    """Kullanılabilir cihazları listeler."""
    try:
        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        devices = spotify.devices()
        return jsonify(devices.get('devices', []))
    except Exception as e:
        logger.error(f"Cihazlar listelenirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@spotify_bp.route('/transfer-playback', methods=['POST'])
@admin_login_required
def transfer_playback():
    """Çalma işlemini başka bir cihaza aktarır."""
    try:
        device_id = request.json.get('device_id')
        if not device_id:
            return jsonify({'error': 'Cihaz ID\'si gerekli'}), 400

        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        spotify.transfer_playback(device_id)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Çalma aktarılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500 