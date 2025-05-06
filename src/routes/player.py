from flask import Blueprint, jsonify, request
import logging
from ..services.spotify_service import spotify_service
from ..utils.auth import admin_login_required
from ..utils.formatters import format_track_info

logger = logging.getLogger(__name__)
player_bp = Blueprint('player', __name__)

@player_bp.route('/play', methods=['POST'])
@admin_login_required
def play():
    """Çalmayı başlatır."""
    try:
        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        spotify.start_playback()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Çalma başlatılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@player_bp.route('/pause', methods=['POST'])
@admin_login_required
def pause():
    """Çalmayı duraklatır."""
    try:
        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        spotify.pause_playback()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Çalma duraklatılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@player_bp.route('/next', methods=['POST'])
@admin_login_required
def next_track():
    """Sonraki şarkıya geçer."""
    try:
        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        spotify.next_track()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Sonraki şarkıya geçilirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@player_bp.route('/previous', methods=['POST'])
@admin_login_required
def previous_track():
    """Önceki şarkıya geçer."""
    try:
        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        spotify.previous_track()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Önceki şarkıya geçilirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@player_bp.route('/volume', methods=['POST'])
@admin_login_required
def set_volume():
    """Ses seviyesini ayarlar."""
    try:
        volume = request.json.get('volume')
        if volume is None or not isinstance(volume, int) or volume < 0 or volume > 100:
            return jsonify({'error': 'Geçersiz ses seviyesi'}), 400

        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        spotify.volume(volume)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Ses seviyesi ayarlanırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@player_bp.route('/currently-playing')
@admin_login_required
def get_currently_playing():
    """Şu an çalan şarkı bilgilerini döndürür."""
    try:
        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        current = spotify.current_playback()
        if not current or not current.get('item'):
            return jsonify({'error': 'Şu an çalan şarkı bulunamadı'}), 404

        track_info = format_track_info(current['item'])
        track_info['is_playing'] = current.get('is_playing', False)
        track_info['progress_ms'] = current.get('progress_ms', 0)
        
        return jsonify(track_info)
    except Exception as e:
        logger.error(f"Şu an çalan şarkı bilgileri alınırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500 