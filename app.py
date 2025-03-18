import os
import json
import threading
import time
import logging
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth

import subprocess
import logging

class AudioManager:
    @staticmethod
    def get_output_devices():
        """Mevcut ses çıkış cihazlarını ve bağlı bluetooth cihazlarını getirir."""
        try:
            # PulseAudio cihazlarını getir
            result = subprocess.run(['pacmd', 'list-sinks'], capture_output=True, text=True)
            if result.returncode != 0:
                logging.error(f"pacmd komutu çalıştırılırken hata: {result.stderr}")
                return []
            
            devices = []
            device_data = {}

            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith('* index:') or line.startswith('index:'):
                    if device_data:
                        devices.append(device_data.copy())
                    is_default = line.startswith('*')
                    idx = line.split(':')[1].strip()
                    device_data = {
                        'index': idx,
                        'is_default': is_default,
                        'name': '',
                        'description': '',
                        'type': 'audio'
                    }
                elif device_data:
                    if 'name:' in line:
                        device_data['name'] = line.split('name:')[1].strip().strip('"<>')
                    elif 'device.description' in line:
                        device_data['description'] = line.split('=')[1].strip().strip('"')
                    # Bluetooth cihazı olup olmadığını kontrol et
                    elif 'device.bus' in line and 'bluetooth' in line.lower():
                        device_data['type'] = 'bluetooth'
            
            if device_data:
                devices.append(device_data.copy())
            
            # Bağlı bluetooth cihazlarını da kontrol et
            try:
                bt_result = subprocess.run(['bluetoothctl', 'info'], capture_output=True, text=True)
                if bt_result.returncode == 0 and "Missing device address argument" not in bt_result.stderr:
                    mac_address = None
                    device_name = None
                    is_connected = False
                    
                    for line in bt_result.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("Device "):
                            mac_address = line.split(" ")[1]
                        elif line.startswith("Name: "):
                            device_name = line.split(": ")[1]
                        elif line.startswith("Connected: ") and "yes" in line.lower():
                            is_connected = True
                    
                    if mac_address and device_name and is_connected:
                        # Zaten list-sinks'de görünmüyorsa ekle
                        if not any(d for d in devices if 'bluetooth' in d.get('name', '').lower() and device_name.lower() in d.get('name', '').lower()):
                            devices.append({
                                'mac_address': mac_address,
                                'name': device_name,
                                'description': f'Bluetooth Cihazı: {device_name}',
                                'type': 'bluetooth',
                                'is_default': False
                            })
            except Exception as bt_error:
                logging.error(f"Bluetooth bilgisi alınırken hata: {bt_error}")
            
            return devices
        except Exception as e:
            logging.error(f"Ses çıkış cihazları listelenirken hata: {e}")
            return []
    @staticmethod
    def scan_bluetooth_devices():
        """Kullanılabilir bluetooth cihazlarını tarar."""
        try:
            result = subprocess.run(['bluetoothctl', 'devices'], capture_output=True, text=True)
            if result.returncode != 0:
                logging.error(f"bluetoothctl komutu çalıştırılırken hata: {result.stderr}")
                return []
            
            devices = []
            for line in result.stdout.splitlines():
                if "Device" in line:
                    parts = line.strip().split(' ', 2)
                    if len(parts) >= 3:
                        device_data = {
                            'mac_address': parts[1],
                            'name': parts[2],
                            'type': 'bluetooth'
                        }
                        devices.append(device_data)
            
            return devices
        except Exception as e:
            logging.error(f"Bluetooth cihazları taranırken hata: {e}")
            return []
        
    
    @staticmethod
    def set_default_output(device_index):
        """Belirtilen cihazı varsayılan çıkış cihazı olarak ayarlar."""
        try:
            # Varsayılan çıkış cihazını değiştir
            subprocess.run(['pacmd', 'set-default-sink', str(device_index)], check=True)
            
            # Tüm oynatılan sesleri yeni çıkış cihazına taşı
            result = subprocess.run(['pacmd', 'list-sink-inputs'], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if 'index:' in line:
                    idx = line.split(':')[1].strip()
                    subprocess.run(['pacmd', 'move-sink-input', idx, str(device_index)])

            return True
        except Exception as e:
            logging.error(f"Varsayılan ses çıkış cihazı ayarlanırken hata: {e}")
            return False
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'mekanmuzikuygulamasi'  # Gerçek uygulamada güvenli bir şekilde değiştirin

# Spotify API bilgileri
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'
SPOTIFY_REDIRECT_URI = 'http://192.168.1.103:8080/callback'
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private'

# Token bilgisini saklayacağımız dosya
TOKEN_FILE = 'spotify_token.json'

# İzin verilen müzik türleri
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie']

# Kullanıcı ayarları dosyası
SETTINGS_FILE = 'settings.json'

# Varsayılan ayarlar
default_settings = {
    'max_queue_length': 20,
    'max_user_requests': 2,
    'active_device_id': None,
    'active_genres': ALLOWED_GENRES
}

# Global değişkenler
spotify_client = None
song_queue = []
user_requests = {}  # Kullanıcı IP adreslerine göre istek sayısı

# Ayarları yükle
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    else:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(default_settings, f)
        return default_settings

# Token bilgisini dosyadan yükle
def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Token dosyasını okuma hatası: {e}")
    return None

# Token bilgisini dosyaya kaydet
def save_token(token_info):
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi")
    except Exception as e:
        logger.error(f"Token kaydetme hatası: {e}")

settings = load_settings()

def get_spotify_auth():
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        open_browser=True,  # Tarayıcı açılmasını önle
        cache_path=None  # Spotipy'nin kendi önbelleğini kullanmıyoruz
    )

def get_spotify_client():
    global spotify_client
    
    # Eğer mevcut bir spotify_client varsa ve çalışıyorsa, onu kullan
    if spotify_client:
        try:
            # Test için basit bir işlem yap
            spotify_client.current_user()
            return spotify_client
        except:
            logger.warning("Mevcut Spotify istemcisi geçersiz. Yenileniyor...")
    
    # Token bilgisini yüklemeyi dene
    token_info = load_token()
    if not token_info:
        logger.warning("Token bilgisi bulunamadı. Lütfen yeniden yetkilendirin.")
        return None
    
    # Token'ın geçerliliğini kontrol et ve gerekirse yenile
    auth_manager = get_spotify_auth()
    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Token süresi dolmuş, yenileniyor...")
            token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            save_token(token_info)
        
        # Yeni bir Spotify istemcisi oluştur
        new_spotify_client = spotipy.Spotify(auth=token_info['access_token'])
        
        # Test amaçlı basit bir sorgu yap
        try:
            new_spotify_client.current_user()
            spotify_client = new_spotify_client  # Global değişkeni güncelle
            logger.info("Spotify istemcisi başarıyla oluşturuldu.")
            return spotify_client
        except Exception as e:
            logger.error(f"Yeni oluşturulan istemci ile doğrulama hatası: {e}")
            return None
    except Exception as e:
        logger.error(f"Token işlemi sırasında hata: {e}")
        return None

# Admin giriş kontrolü için decorator
def admin_login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html', allowed_genres=settings['active_genres'])

@app.route('/admin')
def admin():
    # Eğer zaten giriş yapılmışsa direkt panel sayfasına yönlendir
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    if request.form.get('password') == 'mekan123':  # Basit parola kontrolü
        session['admin_logged_in'] = True
        logger.info("Admin girişi başarılı")
        return redirect(url_for('admin_panel'))
    logger.warning("Başarısız admin girişi denemesi")
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    spotify = get_spotify_client()
    devices = []
    spotify_authenticated = False  # Default to False
    if not spotify:
        logger.warning("Admin paneline erişim için Spotify yetkilendirmesi gerekli")
        return redirect(url_for('spotify_auth'))

    try:
        result = spotify.devices()
        devices = result.get('devices', [])
        logger.info(f"Bulunan cihazlar: {len(devices)}")
        spotify_authenticated = True
    except Exception as e:
        logger.error(f"Cihazları listelerken hata: {e}")
        if "unauthorized" in str(e).lower():
            return redirect(url_for('spotify_auth'))

    return render_template(
        'admin_panel.html', 
        settings=settings,
        devices=devices,
        queue=song_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        active_device_id=settings.get('active_device_id')
    )

@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    """
    Spotify cihazlarını yenileme endpoint'i
    """
    spotify = get_spotify_client()
    if not spotify:
        logger.warning("Cihazları yenilemek için Spotify yetkilendirmesi gerekli")
        return redirect(url_for('spotify_auth'))
    
    try:
        result = spotify.devices()
        devices = result.get('devices', [])
        logger.info(f"Cihazlar yenilendi: {len(devices)} cihaz bulundu")
        
        if settings['active_device_id']:
            device_exists = any(device['id'] == settings['active_device_id'] for device in devices)
            if not device_exists:
                logger.warning(f"Aktif cihaz ({settings['active_device_id']}) artık mevcut değil")
                settings['active_device_id'] = None
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(settings, f)
        
        return redirect(url_for('admin_panel'))
    except Exception as e:
        logger.error(f"Cihazları yenilerken hata: {e}")
        if "unauthorized" in str(e).lower():
            return redirect(url_for('spotify_auth'))
        return redirect(url_for('admin_panel'))

@app.route('/remove-song/<song_id>', methods=['POST'])
@admin_login_required
def remove_song(song_id):
    global song_queue
    song_queue = [song for song in song_queue if song['id'] != song_id]
    logger.info(f"Şarkı kuyruktan kaldırıldı: {song_id}")
    return redirect(url_for('admin_panel'))

@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
    song_id = request.form.get('song_id')
    if not song_id:
        logger.warning("Eksik şarkı ID'si")
        return redirect(url_for('admin_panel'))
    
    spotify = get_spotify_client()
    if not spotify:
        logger.warning("Şarkı eklemek için Spotify yetkilendirmesi gerekli")
        return redirect(url_for('spotify_auth'))
    
    try:
        song_info = spotify.track(song_id)
        song_name = song_info['name']
        
        song_queue.append({
            'id': song_id,
            'name': song_name,
            'artist': song_info['artists'][0]['name']
        })
        logger.info(f"Şarkı kuyruğa eklendi: {song_id} - {song_name}")
        return redirect(url_for('admin_panel'))
    except Exception as e:
        logger.error(f"Şarkı eklerken hata: {e}")
        if "unauthorized" in str(e).lower():
            return redirect(url_for('spotify_auth'))
        return redirect(url_for('admin_panel'))
   
@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
    settings['max_user_requests'] = int(request.form.get('max_user_requests', 2))
    settings['active_device_id'] = request.form.get('active_device_id')
    settings['active_genres'] = [genre for genre in ALLOWED_GENRES if request.form.get(f'genre_{genre}')]
    
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)
    
    logger.info(f"Ayarlar güncellendi: {settings}")
    return redirect(url_for('admin_panel'))

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    try:
        auth_manager = get_spotify_auth()
        auth_url = auth_manager.get_authorize_url()
        logger.info(f"Spotify yetkilendirme URL'si: {auth_url}")
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Spotify yetkilendirme hatası: {e}")
        return f"Hata: {str(e)}"

@app.route('/callback')
def callback():
    admin_logged_in = session.get('admin_logged_in', False)
    
    auth_manager = get_spotify_auth()
    if 'code' not in request.args:
        logger.error("Callback'te kod parametresi bulunamadı")
        return redirect(url_for('admin'))
    
    code = request.args.get('code')
    try:
        token_info = auth_manager.get_access_token(code)
        spotify = spotipy.Spotify(auth=token_info['access_token'])
        try:
            user_profile = spotify.current_user()
            logger.info(f"Token doğrulandı. Kullanıcı: {user_profile.get('display_name')}")
            save_token(token_info)
            global spotify_client
            spotify_client = spotify
            session['spotify_authenticated'] = True
            session['spotify_user'] = user_profile.get('display_name')
            logger.info("Spotify yetkilendirme başarılı, token kaydedildi")
            
            if admin_logged_in:
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('index'))
        except Exception as validation_error:
            logger.error(f"Token doğrulama hatası: {validation_error}")
            return redirect(url_for('admin'))
    except Exception as e:
        logger.error(f"Token alırken hata: {e}")
        return redirect(url_for('admin'))
    
@app.route('/api/output-devices')
def api_output_devices():
    devices = AudioManager.get_output_devices()
    logger.info(f"Found {len(devices)} output devices: {devices}")
    return jsonify({
        'devices': devices
    })

@app.route('/api/scan-bluetooth')
@admin_login_required
def api_scan_bluetooth():
    try:
        devices = AudioManager.scan_bluetooth_devices()
        logger.info(f"Bluetooth taraması: {len(devices)} cihaz bulundu")
        return jsonify({
            'success': True,
            'devices': devices
        })
    except Exception as e:
        logger.error(f"Bluetooth tarama hatası: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@staticmethod
def pair_bluetooth_device(mac_address):
    """Belirtilen MAC adresine sahip bluetooth cihazını eşleştirir ve bağlar."""
    try:
        # Eşleştirme
        pair_cmd = subprocess.run(['bluetoothctl', 'pair', mac_address], 
                                  capture_output=True, text=True, timeout=30)
        if pair_cmd.returncode != 0:
            logging.error(f"Bluetooth cihazı eşleştirme hatası: {pair_cmd.stderr}")
            return False
        
        # Güvenilir yapma
        trust_cmd = subprocess.run(['bluetoothctl', 'trust', mac_address], 
                                   capture_output=True, text=True)
        
        # Bağlantı kurma
        connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], 
                                     capture_output=True, text=True, timeout=30)
        if connect_cmd.returncode != 0:
            logging.error(f"Bluetooth cihazı bağlantı hatası: {connect_cmd.stderr}")
            return False
        
        logging.info(f"Bluetooth cihazı başarıyla eşleştirildi ve bağlandı: {mac_address}")
        return True
    except Exception as e:
        logging.error(f"Bluetooth cihazı eşleştirme/bağlama sırasında hata: {e}")
        return False

@staticmethod
def disconnect_bluetooth_device(mac_address):
    """Belirtilen MAC adresine sahip bluetooth cihazının bağlantısını keser."""
    try:
        cmd = subprocess.run(['bluetoothctl', 'disconnect', mac_address], 
                             capture_output=True, text=True)
        if cmd.returncode != 0:
            logging.error(f"Bluetooth cihazı bağlantısı kesme hatası: {cmd.stderr}")
            return False
        
        logging.info(f"Bluetooth cihazı bağlantısı başarıyla kesildi: {mac_address}")
        return True
    except Exception as e:
        logging.error(f"Bluetooth cihazı bağlantısını kesme sırasında hata: {e}")
        return False
    
@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    try:
        data = request.get_json()
        if not data or 'mac_address' not in data:
            logger.error("Eksik mac_address parametresi")
            return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
        
        mac_address = data['mac_address']
        logger.info(f"Bluetooth cihazı bağlantısını kesme isteği: {mac_address}")
        
        success = AudioManager.disconnect_bluetooth_device(mac_address)
        
        if success:
            return jsonify({
                'success': True,
                'message': f"Bluetooth cihazı bağlantısı kesildi: {mac_address}",
                'devices': AudioManager.get_output_devices()
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Bluetooth cihazı bağlantısı kesilemedi',
                'devices': AudioManager.get_output_devices()
            }), 500
    except Exception as e:
        logger.error(f"Bluetooth bağlantısını kesme isteği sırasında hata: {e}")
        return jsonify({'success': False, 'error': f'Hata: {str(e)}'}), 500

@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    try:
        data = request.get_json()
        if not data or 'mac_address' not in data:
            logger.error("Eksik mac_address parametresi")
            return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
        
        mac_address = data['mac_address']
        logger.info(f"Bluetooth cihazı eşleştirme isteği: {mac_address}")
        
        success = AudioManager.pair_bluetooth_device(mac_address)
        
        if success:
            return jsonify({
                'success': True,
                'message': f"Bluetooth cihazı eşleştirildi ve bağlandı: {mac_address}",
                'devices': AudioManager.get_output_devices()
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Bluetooth cihazı eşleştirilemedi',
                'devices': AudioManager.scan_bluetooth_devices()
            }), 500
    except Exception as e:
        logger.error(f"Bluetooth eşleştirme isteği sırasında hata: {e}")
        return jsonify({'success': False, 'error': f'Hata: {str(e)}'}), 500

@app.route('/api/set-output-device', methods=['POST'])
def set_output_device():
    """Belirtilen cihazı varsayılan çıkış cihazı olarak ayarlar."""
    try:
        data = request.get_json()
        if not data or 'device_index' not in data:
            return jsonify({'success': False, 'error': 'Cihaz indeksi gerekli'}), 400

        device_index = data['device_index']
        success = AudioManager.set_default_output(device_index)

        if success:
            return jsonify({
                'success': True,
                'message': f"Cihaz değiştirildi: {device_index}",
                'devices': AudioManager.get_output_devices()
            })
        else:
            return jsonify({'success': False, 'error': 'Cihaz değiştirilemedi'}), 500
    except Exception as e:
        logging.error(f"Cihaz değiştirme isteği sırasında hata: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/logout')
def logout():
    global spotify_client
    spotify_client = None
    session.pop('admin_logged_in', None)
    session.pop('spotify_authenticated', None)
    session.pop('spotify_user', None)
    session.clear()
    
    if os.path.exists(TOKEN_FILE):
        try:
            os.remove(TOKEN_FILE)
            logger.info("Token dosyası silindi")
        except Exception as e:
            logger.error(f"Token dosyası silinirken hata: {e}")
    
    return redirect(url_for('admin'))

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search_query')
    genre_filter = request.form.get('genre_filter')
    logger.info(f"Arama: '{search_query}', Tür: '{genre_filter}'")
    
    if genre_filter not in settings['active_genres']:
        logger.warning(f"İzin verilmeyen tür: {genre_filter}")
        return jsonify({'error': 'Bu müzik türü şu anda izin verilen listede değil'})
    
    user_ip = request.remote_addr
    if user_ip in user_requests and user_requests[user_ip] >= settings['max_user_requests']:
        logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip}")
        return jsonify({'error': 'Maksimum şarkı ekleme limitine ulaştınız'})
    
    spotify = get_spotify_client()
    if not spotify:
        logger.error("Arama için Spotify oturumu bulunamadı")
        return jsonify({'error': 'Spotify oturumu bulunamadı'})
    
    try:
        results = spotify.search(q=f'{search_query} genre:{genre_filter}', type='track', limit=10)
        tracks = results['tracks']['items']
        logger.info(f"Arama sonuçları: {len(tracks)} şarkı bulundu")
        search_results = []
        for track in tracks:
            search_results.append({
                'id': track['id'],
                'name': track['name'],
                'artist': track['artists'][0]['name'],
                'album': track['album']['name'],
                'image': track['album']['images'][0]['url'] if track['album']['images'] else None
            })
        return jsonify({'results': search_results})
    except Exception as e:
        logger.error(f"Spotify araması sırasında hata: {e}")
        return jsonify({'error': f'Arama hatası: {str(e)}'})

@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    if not request.is_json:
        logger.error("İstek JSON formatında değil")
        return jsonify({'error': 'İstek JSON formatında olmalıdır'}), 400
    
    data = request.get_json()
    logger.info(f"Kuyruk ekleme isteği alındı: {data}")
    
    if not data or 'track_id' not in data:
        logger.error("İstekte track_id bulunamadı")
        return jsonify({'error': 'Geçersiz istek, track_id gerekli'}), 400
    
    if len(song_queue) >= settings['max_queue_length']:
        logger.warning("Kuyruk maksimum kapasitede")
        return jsonify({'error': 'Şarkı kuyruğu dolu'})
    
    user_ip = request.remote_addr
    if user_ip not in user_requests:
        user_requests[user_ip] = 0
    if user_requests[user_ip] >= settings['max_user_requests']:
        logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip}")
        return jsonify({'error': 'Maksimum şarkı ekleme limitine ulaştınız'})
    
    spotify = get_spotify_client()
    if not spotify:
        logger.error("Kuyruk ekleme için Spotify oturumu bulunamadı")
        return jsonify({'error': 'Spotify oturumu bulunamadı'})
    
    try:
        track = spotify.track(data['track_id'])
        song_queue.append({
            'id': data['track_id'],
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'added_by': user_ip,
            'added_at': time.time()
        })
        user_requests[user_ip] += 1
        logger.info(f"Şarkı kuyruğa eklendi: {track['name']} - {track['artists'][0]['name']}")
        logger.info(f"Güncel kuyruk uzunluğu: {len(song_queue)}")
        return jsonify({'success': True, 'message': 'Şarkı kuyruğa eklendi'})
    except Exception as e:
        logger.error(f"Spotify şarkı bilgisi alırken hata: {e}")
        return jsonify({'error': f'Sağlanan track bilgisi alınamadı: {str(e)}'}), 500

@app.route('/queue')
def view_queue():
    return render_template('queue.html', queue=song_queue)

@app.route('/api/queue')
def api_get_queue():
    return jsonify({
        'queue': song_queue,
        'queue_length': len(song_queue),
        'max_length': settings['max_queue_length']
    })

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue
    song_queue = []
    logger.info("Şarkı kuyruğu temizlendi")
    return redirect(url_for('admin_panel'))

@app.route('/check-auth-status')
def check_auth_status():
    is_admin = session.get('admin_logged_in', False)
    is_spotify_authenticated = session.get('token_info', False)
    spotify_user = session.get('spotify_user', None)
    
    if is_spotify_authenticated and spotify_user:
        return jsonify({
            'admin_logged_in': is_admin,
            'spotify_authenticated': True,
            'user': spotify_user
        })
    
    spotify = get_spotify_client()
    if spotify:
        try:
            user = spotify.current_user()
            session['spotify_authenticated'] = True
            session['spotify_user'] = user.get('display_name')
            return jsonify({
                'admin_logged_in': is_admin,
                'spotify_authenticated': True,
                'user': user.get('display_name')
            })
        except Exception as e:
            logger.error(f"Spotify kullanıcı bilgisi alırken hata: {e}")
    
    return jsonify({
        'admin_logged_in': is_admin,
        'spotify_authenticated': False
    })

@app.route('/refresh-token')
@admin_login_required
def refresh_token():
    """
    Token'ı manuel olarak yenileme endpoint'i
    """
    global spotify_client
    spotify_client = None  # Mevcut istemciyi temizle
    
    token_info = load_token()
    if not token_info:
        logger.warning("Yenilenecek token bulunamadı.")
        return redirect(url_for('spotify_auth'))
    
    auth_manager = get_spotify_auth()
    try:
        if 'refresh_token' not in token_info:
            logger.error("Token bilgisinde refresh_token eksik.")
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            return redirect(url_for('spotify_auth'))
        
        new_token = auth_manager.refresh_access_token(token_info['refresh_token'])
        save_token(new_token)
        
        spotify_client = spotipy.Spotify(auth=new_token['access_token'])
        
        try:
            user = spotify_client.current_user()
            session['spotify_authenticated'] = True
            session['spotify_user'] = user.get('display_name')
            logger.info("Token başarıyla yenilendi!")
        except Exception as e:
            logger.error(f"Yeni token ile kullanıcı doğrulama hatası: {e}")
            return redirect(url_for('spotify_auth'))
        
        return redirect(url_for('admin_panel'))
    except Exception as e:
        logger.error(f"Token yenileme hatası: {e}")
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        return redirect(url_for('spotify_auth'))

# -----------------------------------------------------------------------------
# BACKGROUND THREAD: Şarkı Kuyruğu Oynatıcısı
# -----------------------------------------------------------------------------
def background_queue_player():
    """
    Bu fonksiyon arka planda çalışır ve kuyruğa eklenen şarkıları kontrol edip çalar.
    """
    global spotify_client
    
    while True:
        spotify = get_spotify_client()
        
        if not spotify:
            logger.warning("Spotify istemcisi bulunamadı, çalma yapılamıyor")
            time.sleep(10)
            continue
        
        if song_queue and settings['active_device_id']:
            try:
                current_playback = spotify.current_playback()
            except Exception as e:
                logger.error(f"Playback durumu kontrol hatası: {e}")
                spotify_client = None
                time.sleep(5)
                continue

            if current_playback is None or not current_playback.get('is_playing'):
                if song_queue:
                    next_song = song_queue.pop(0)
                    try:
                        spotify.start_playback(
                            device_id=settings['active_device_id'],
                            uris=[f"spotify:track:{next_song['id']}"]
                        )
                        logger.info(f"Şarkı çalıyor: {next_song['name']} - {next_song['artist']}")
                        user_ip = next_song.get('added_by')
                        if user_ip in user_requests:
                            user_requests[user_ip] = max(0, user_requests[user_ip] - 1)
                    except Exception as e:
                        logger.error(f"Şarkı çalma hatası: {e}")
                        song_queue.insert(0, next_song)
            else:
                progress = current_playback.get('progress_ms', 0)
                duration = current_playback.get('item', {}).get('duration_ms', 0)
                remaining = duration - progress
                if remaining < 5000 and song_queue:
                    logger.info("Şarkı bitmeye yakın, sıradaki şarkı hazırlanıyor")
        else:
            if not settings['active_device_id']:
                logger.warning("Aktif cihaz seçilmemiş, çalma yapılamıyor")
            elif not song_queue:
                logger.debug("Şarkı kuyruğu boş")
        
        time.sleep(3)

def start_queue_player():
    thread = threading.Thread(target=background_queue_player)
    thread.daemon = True
    thread.start()
    logger.info("Arka plan şarkı çalma görevi başlatıldı")

@app.route('/play_queue', endpoint='play_queue')
def play_queue_dummy():
    # Dummy endpoint to satisfy url_for('play_queue') calls from your template.
    return jsonify({'message': 'Şarkı kuyruğu arka planda çalıyor'}), 200

@app.route('/previous_track', endpoint='previous_track')
def previous_track_dummy():
    # Dummy endpoint for previous track functionality
    return jsonify({'message': 'Önceki şarkı işlevi henüz uygulanmadı.'}), 200

@app.route('/next_track', endpoint='next_track')
def next_track_dummy():
    # Dummy endpoint for next track functionality
    return jsonify({'message': 'Sonraki şarkı işlevi henüz uygulanmadı.'}), 200

@app.route('/toggle_play_pause', endpoint='toggle_play_pause')
def toggle_play_pause_dummy():
    # Dummy endpoint for play/pause functionality
    return jsonify({'message': 'Çalma/durdurma işlevi henüz uygulanmadı.'}), 200


# -----------------------------------------------------------------------------
# DUMMY ENDPOINT: play_queue
# -----------------------------------------------------------------------------
# Eğer bir template veya başka bir yerden url_for('play_queue') çağrısı yapılıyorsa,
# bu endpoint tanımlandığından BuildError önlenecektir.
@app.route('/play_queue')
def play_queue_endpoint():
    return jsonify({'message': 'Şarkı kuyruğu arka planda çalıyor'}), 200

# -----------------------------------------------------------------------------
# Uygulama Başlangıcı: Token kontrolü ve arka plan görevlerinin başlatılması
# -----------------------------------------------------------------------------
def check_token_on_startup():
    global spotify_client
    token_info = load_token()
    if token_info:
        auth_manager = get_spotify_auth()
        try:
            if auth_manager.is_token_expired(token_info):
                logger.info("Başlangıçta bulunan token süresi dolmuş, yenileniyor...")
                try:
                    new_token = auth_manager.refresh_access_token(token_info['refresh_token'])
                    save_token(new_token)
                    logger.info("Token başarıyla yenilendi")
                    spotify_client = spotipy.Spotify(auth=new_token['access_token'])
                    spotify_client.current_user()
                    logger.info("Spotify istemcisi başlatıldı ve doğrulandı")
                    return True
                except Exception as e:
                    logger.error(f"Token yenileme hatası: {e}")
                    if os.path.exists(TOKEN_FILE):
                        os.remove(TOKEN_FILE)
                    return False
            else:
                spotify_client = spotipy.Spotify(auth=token_info['access_token'])
                try:
                    spotify_client.current_user()
                    logger.info("Mevcut token ile Spotify istemcisi başlatıldı ve doğrulandı")
                    return True
                except Exception as e:
                    logger.error(f"Token doğrulama hatası: {e}")
                    if os.path.exists(TOKEN_FILE):
                        os.remove(TOKEN_FILE)
                    return False
        except Exception as e:
            logger.error(f"Başlangıç token kontrolünde hata: {e}")
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
    else:
        logger.warning("Başlangıçta token bulunamadı")
    return False

if __name__ == '__main__':
    logger.info("------- Uygulama başlatılıyor -------")
    logger.info(f"Yüklenen ayarlar: {settings}")
    
    check_token_on_startup()
    start_queue_player()
    
    app.run(host='0.0.0.0', port=8080, debug=True)
