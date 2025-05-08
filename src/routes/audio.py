from flask import Blueprint, request, jsonify
from src.utils import _run_command

audio_bp = Blueprint('audio', __name__)

@audio_bp.route('/api/volume', methods=['POST'])
def set_volume():
    volume = request.form.get('volume')
    if not volume:
        return jsonify({'success': False, 'error': 'Ses seviyesi gerekli'})
    return jsonify(_run_command(['volume', volume])) 