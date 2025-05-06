from flask import Blueprint, jsonify, request
import logging
import subprocess
from ..utils.auth import admin_login_required, load_settings, save_settings

logger = logging.getLogger(__name__)
audio_bp = Blueprint('audio', __name__)

@audio_bp.route('/equalizer', methods=['GET'])
@admin_login_required
def get_equalizer():
    """Ekolayzer ayarlarını döndürür."""
    try:
        settings = load_settings()
        return jsonify(settings.get('equalizer', {}))
    except Exception as e:
        logger.error(f"Ekolayzer ayarları alınırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@audio_bp.route('/equalizer', methods=['POST'])
@admin_login_required
def set_equalizer():
    """Ekolayzer ayarlarını günceller."""
    try:
        settings = load_settings()
        equalizer = request.json.get('equalizer')
        
        if not equalizer:
            return jsonify({'error': 'Ekolayzer ayarları gerekli'}), 400

        settings['equalizer'] = equalizer
        if save_settings(settings):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Ekolayzer ayarları kaydedilemedi'}), 500
    except Exception as e:
        logger.error(f"Ekolayzer ayarları güncellenirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@audio_bp.route('/bluetooth/scan', methods=['POST'])
@admin_login_required
def scan_bluetooth():
    """Bluetooth cihazlarını tarar."""
    try:
        from ..config import EX_SCRIPT_PATH
        result = subprocess.run(['python3', EX_SCRIPT_PATH], capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({'status': 'success', 'output': result.stdout})
        else:
            return jsonify({'error': 'Bluetooth taraması başarısız', 'details': result.stderr}), 500
    except Exception as e:
        logger.error(f"Bluetooth taraması yapılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@audio_bp.route('/bluetooth/connect', methods=['POST'])
@admin_login_required
def connect_bluetooth():
    """Bluetooth cihazına bağlanır."""
    try:
        device_address = request.json.get('address')
        if not device_address:
            return jsonify({'error': 'Cihaz adresi gerekli'}), 400

        result = subprocess.run(['bluetoothctl', 'connect', device_address], capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({'status': 'success', 'output': result.stdout})
        else:
            return jsonify({'error': 'Bluetooth bağlantısı başarısız', 'details': result.stderr}), 500
    except Exception as e:
        logger.error(f"Bluetooth bağlantısı yapılırken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500

@audio_bp.route('/bluetooth/disconnect', methods=['POST'])
@admin_login_required
def disconnect_bluetooth():
    """Bluetooth cihazından bağlantıyı keser."""
    try:
        device_address = request.json.get('address')
        if not device_address:
            return jsonify({'error': 'Cihaz adresi gerekli'}), 400

        result = subprocess.run(['bluetoothctl', 'disconnect', device_address], capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({'status': 'success', 'output': result.stdout})
        else:
            return jsonify({'error': 'Bluetooth bağlantısı kesilemedi', 'details': result.stderr}), 500
    except Exception as e:
        logger.error(f"Bluetooth bağlantısı kesilirken hata: {str(e)}")
        return jsonify({'error': str(e)}), 500 