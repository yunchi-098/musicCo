from flask import Blueprint, request, jsonify
from src.utils import _run_command, get_spotify_client, _ensure_spotify_uri, check_filters, update_time_profile

player_bp = Blueprint('player', __name__)

@player_bp.route('/api/play', methods=['POST'])
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

@player_bp.route('/api/pause', methods=['POST'])
def pause():
    return jsonify(_run_command(['pause']))

@player_bp.route('/api/resume', methods=['POST'])
def resume():
    return jsonify(_run_command(['resume']))

@player_bp.route('/api/next', methods=['POST'])
def next_track():
    return jsonify(_run_command(['next']))

@player_bp.route('/api/previous', methods=['POST'])
def previous_track():
    return jsonify(_run_command(['previous']))

@player_bp.route('/api/volume', methods=['POST'])
def set_volume():
    volume = request.form.get('volume')
    if not volume:
        return jsonify({'success': False, 'error': 'Ses seviyesi gerekli'})
    return jsonify(_run_command(['volume', volume])) 