from flask import Blueprint, request, jsonify
from src.utils import queue, queue_lock, get_spotify_client, _ensure_spotify_uri, check_filters, update_time_profile, settings

queue_bp = Blueprint('queue', __name__)

@queue_bp.route('/api/queue', methods=['GET'])
def get_queue():
    with queue_lock:
        return jsonify({'queue': queue})

@queue_bp.route('/api/queue/add', methods=['POST'])
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

@queue_bp.route('/api/queue/remove', methods=['POST'])
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