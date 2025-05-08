from flask import Blueprint, request, jsonify, session
from src.utils import get_spotify_client, get_spotify_auth, load_token, save_token, settings, save_settings, time_profiles, auto_advance_enabled

spotify_bp = Blueprint('spotify', __name__)

@spotify_bp.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings)

@spotify_bp.route('/api/settings', methods=['POST'])
def update_settings():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Yetkisiz erişim'})
    
    new_settings = request.get_json()
    if not new_settings:
        return jsonify({'success': False, 'error': 'Geçersiz ayarlar'})
    
    settings.update(new_settings)
    save_settings(settings)
    return jsonify({'success': True})

@spotify_bp.route('/api/time-profiles', methods=['GET'])
def get_time_profiles():
    return jsonify(time_profiles)

@spotify_bp.route('/api/auto-advance', methods=['POST'])
def toggle_auto_advance():
    global auto_advance_enabled
    auto_advance_enabled = not auto_advance_enabled
    return jsonify({'success': True, 'auto_advance': auto_advance_enabled}) 