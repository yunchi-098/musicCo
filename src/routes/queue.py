from flask import Blueprint, jsonify, request
import logging
from ..services.spotify_service import spotify_service
from ..services.queue_service import queue_service
from ..utils.auth import admin_login_required
from ..utils.formatters import format_track_info

logger = logging.getLogger(__name__)
queue_bp = Blueprint('queue', __name__)

@queue_bp.route('/queue')
@admin_login_required
def get_queue():
    """Kuyruk bilgilerini döndürür."""
    try:
        queue = queue_service.get_queue()
        return jsonify(queue)
    except Exception as e:
        logger.error(f"Kuyruk bilgileri alınırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@queue_bp.route('/queue/add', methods=['POST'])
@admin_login_required
def add_to_queue():
    """Kuyruğa şarkı ekler."""
    try:
        track_uri = request.json.get('uri')
        if not track_uri:
            return jsonify({'error': 'Şarkı URI\'si gerekli'}), 400

        spotify = spotify_service.get_client()
        if not spotify:
            return jsonify({'error': 'Spotify bağlantısı bulunamadı'}), 401

        track = spotify.track(track_uri)
        if not track:
            return jsonify({'error': 'Şarkı bulunamadı'}), 404

        track_info = format_track_info(track)
        if queue_service.add_to_queue(track_info):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Şarkı kuyruğa eklenemedi'}), 500
    except Exception as e:
        logger.error(f"Kuyruğa şarkı eklenirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@queue_bp.route('/queue/remove/<track_id>', methods=['DELETE'])
@admin_login_required
def remove_from_queue(track_id):
    """Kuyruktan şarkı çıkarır."""
    try:
        if queue_service.remove_from_queue(track_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Şarkı kuyruktan çıkarılamadı'}), 500
    except Exception as e:
        logger.error(f"Kuyruktan şarkı çıkarılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@queue_bp.route('/queue/clear', methods=['POST'])
@admin_login_required
def clear_queue():
    """Kuyruğu temizler."""
    try:
        if queue_service.clear_queue():
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Kuyruk temizlenemedi'}), 500
    except Exception as e:
        logger.error(f"Kuyruk temizlenirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@queue_bp.route('/history')
@admin_login_required
def get_history():
    """Çalma geçmişini döndürür."""
    try:
        history = queue_service.get_history()
        return jsonify(history)
    except Exception as e:
        logger.error(f"Çalma geçmişi alınırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@queue_bp.route('/history/clear', methods=['POST'])
@admin_login_required
def clear_history():
    """Çalma geçmişini temizler."""
    try:
        if queue_service.clear_history():
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Çalma geçmişi temizlenemedi'}), 500
    except Exception as e:
        logger.error(f"Çalma geçmişi temizlenirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500 