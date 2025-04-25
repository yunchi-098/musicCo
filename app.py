# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Regex kütüphanesi
import subprocess
from functools import wraps
# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi

# --- Yapılandırılabilir Ayarlar ---
# Spotify API Bilgileri - KENDİ BİLGİLERİNİZLE DEĞİŞTİRİN!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78' # ÖRNEK - DEĞİŞTİR
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426' # ÖRNEK - DEĞİŞTİR
# Cihazınızın AĞ üzerindeki IP adresini ve Flask portunu yazın (Örn: http://192.168.1.100:8080/callback)
SPOTIFY_REDIRECT_URI = 'http://100.81.225.104:8080/callback' # ÖRNEK - DEĞİŞTİR
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

# Diğer Dosya Yolları
TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12 # Saniye cinsinden Bluetooth tarama süresi
# ---------------------------------

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class AudioManager:
    """PipeWire ve Bluetooth ile ses cihazlarını yöneten sınıf."""

    @staticmethod
    def _run_command(command, timeout=10):
        """Helper function to run shell commands."""
        try:
            # PipeWire komutları genellikle daha hızlıdır, ancak timeout kalabilir
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
            return True, result.stdout, result.stderr
        except FileNotFoundError:
            logger.error(f"Command not found: {command[0]}. Is PipeWire installed and in PATH?")
            return False, "", f"Command not found: {command[0]}"
        except subprocess.CalledProcessError as e:
            logger.error(f"Command '{' '.join(command)}' failed with error: {e.stderr}")
            return False, e.stdout, e.stderr
        except subprocess.TimeoutExpired:
            logger.error(f"Command '{' '.join(command)}' timed out after {timeout} seconds.")
            return False, "", f"Command timed out after {timeout} seconds."
        except Exception as e:
            logger.error(f"Error running command '{' '.join(command)}': {e}", exc_info=True)
            return False, "", f"Unexpected error: {e}"

    @staticmethod
    def get_default_pipewire_sink_info():
        """Sistemin mevcut varsayılan PipeWire sink'inin bilgilerini (node adı ve açıklama) alır."""
        default_sink_name = None
        default_sink_description = None

        # 1. Varsayılan sink'in node adını al
        success_meta, stdout_meta, stderr_meta = AudioManager._run_command(['pw-metadata', '-n', 'settings', '0', 'default.audio.sink'], timeout=5)
        if success_meta:
            # Çıktı genellikle şu formatta olur: 'default.audio.sink = {"name":"alsa_output.pci-0000_00_1f.3.analog-stereo"}'
            match = re.search(r'"name"\s*:\s*"([^"]+)"', stdout_meta)
            if match:
                default_sink_name = match.group(1)
                logger.debug(f"Varsayılan PipeWire sink node adı: {default_sink_name}")

                # 2. Node adını kullanarak açıklamasını al (pw-dump ile)
                success_dump, stdout_dump, stderr_dump = AudioManager._run_command(['pw-dump', 'Node', default_sink_name], timeout=5)
                if success_dump:
                    try:
                        # pw-dump tek bir node için bile liste döndürür
                        node_info_list = json.loads(stdout_dump)
                        if node_info_list and isinstance(node_info_list, list):
                            node_info = node_info_list[0] # İlk elemanı al
                            props = node_info.get('info', {}).get('props', {})
                            default_sink_description = props.get('node.description', default_sink_name) # Açıklama yoksa node adını kullan
                            logger.debug(f"Varsayılan PipeWire sink açıklaması: {default_sink_description}")
                        else:
                             logger.warning(f"Varsayılan sink ({default_sink_name}) için pw-dump çıktısı anlaşılamadı.")
                             default_sink_description = default_sink_name # Fallback
                    except json.JSONDecodeError as e:
                        logger.error(f"pw-dump çıktısı JSON olarak ayrıştırılamadı: {e}")
                        default_sink_description = default_sink_name # Fallback
                    except Exception as e:
                        logger.error(f"pw-dump çıktısı işlenirken hata: {e}", exc_info=True)
                        default_sink_description = default_sink_name # Fallback
                else:
                    logger.warning(f"Varsayılan sink ({default_sink_name}) için pw-dump başarısız: {stderr_dump}")
                    default_sink_description = default_sink_name # Fallback
            else:
                logger.error(f"pw-metadata çıktısından varsayılan sink adı çıkarılamadı: {stdout_meta}")
        else:
            logger.error(f"Varsayılan PipeWire sink alınamadı: {stderr_meta}")

        return default_sink_name, default_sink_description

    @staticmethod
    def set_default_pipewire_sink(node_name):
        """Belirtilen node adını sistemin varsayılan PipeWire sink'i olarak ayarlar."""
        logger.info(f"Setting default PipeWire sink to node '{node_name}'...")
        # JSON formatında node adını içeren komutu oluştur
        command = ['pw-metadata', '-n', 'settings', '0', 'default.audio.sink', f'{{"name":"{node_name}"}}']
        success, stdout, stderr = AudioManager._run_command(command, timeout=10)
        if success:
            logger.info(f"Default PipeWire sink successfully set to node '{node_name}'.")
            # Açıklamayı tekrar alıp mesajda göstermek daha kullanıcı dostu olabilir
            _, sink_desc = AudioManager.get_default_pipewire_sink_info()
            friendly_name = sink_desc if sink_desc else node_name
            return True, f"Varsayılan ses çıkışı '{friendly_name}' olarak ayarlandı."
        else:
            err_msg = f"Node '{node_name}' varsayılan yapılamadı: {stderr}"
            if "No such object" in stderr or "invalid node" in stderr: # PipeWire hata mesajları değişebilir
                 err_msg = f"Sink (Node) bulunamadı veya geçersiz: '{node_name}'."
            logger.error(f"Failed to set default PipeWire sink: {stderr}")
            return False, err_msg

    @staticmethod
    def get_pipewire_sinks():
        """Mevcut PipeWire sink'lerini (Node) ve varsayılanı listeler."""
        sinks = []
        default_sink_node_name, _ = AudioManager.get_default_pipewire_sink_info() # Sadece node adını al

        success_dump, stdout_dump, stderr_dump = AudioManager._run_command(['pw-dump', 'Node'], timeout=10)

        if not success_dump:
            logger.error(f"Error listing PipeWire nodes (pw-dump): {stderr_dump}")
            return [], default_sink_node_name # Return default even if list fails

        try:
            all_nodes = json.loads(stdout_dump)
            if not isinstance(all_nodes, list):
                 logger.error("pw-dump çıktısı beklenildiği gibi bir liste değil.")
                 return [], default_sink_node_name

            for node in all_nodes:
                if not isinstance(node, dict): continue # Beklenmeyen formatı atla

                info = node.get('info', {})
                props = info.get('props', {})
                media_class = props.get('media.class')

                # Sadece ses çıkışlarını (sink) al
                if media_class == 'Audio/Sink':
                    try:
                        node_id = node.get('id') # Node ID (sayısal)
                        node_name = props.get('node.name', f'node_{node_id}') # Benzersiz node adı
                        # Açıklama için çeşitli yerlere bakılabilir
                        description = props.get('node.description', props.get('device.description', node_name))
                        # Bluetooth cihaz adını daha iyi almak için:
                        if 'bluez' in node_name:
                            # 'device.alias' veya 'bluez5.device.alias' daha iyi olabilir
                            bt_alias = props.get('device.alias', props.get('bluez5.device.alias', description))
                            description = bt_alias if bt_alias != description else description # Eğer alias farklıysa onu kullan

                        state = info.get('state', 'unknown').upper() # Durumu al (running, idle, suspended)
                        is_default = (node_name == default_sink_node_name)

                        sinks.append({
                            'id': node_id, # PipeWire Node ID
                            'name': node_name, # PipeWire Node Name (benzersiz)
                            'description': description, # Kullanıcı dostu açıklama
                            'state': state,
                            'is_default': is_default
                        })
                    except Exception as parse_err:
                        logger.warning(f"Could not parse PipeWire node info: {node.get('id', 'N/A')} - Error: {parse_err}")

            logger.info(f"Found PipeWire sinks: {len(sinks)} (Default Node: {default_sink_node_name})")
            return sinks, default_sink_node_name

        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from pw-dump: {e}")
            return [], default_sink_node_name
        except Exception as e:
            logger.error(f"Error processing pw-dump output: {e}", exc_info=True)
            return [], default_sink_node_name

    # --- Bluetooth Fonksiyonları (Değişiklik Yok) ---
    @staticmethod
    def get_paired_bluetooth_devices():
        """Sadece eşleştirilmiş Bluetooth cihazlarını listeler."""
        devices = []
        success_paired, stdout_paired, stderr_paired = AudioManager._run_command(['bluetoothctl', 'paired-devices'], timeout=10)
        if not success_paired:
             logger.error(f"Error listing paired Bluetooth devices: {stderr_paired}")
             return []

        paired_macs = set()
        for line in stdout_paired.splitlines():
            if line.startswith("Device"):
                parts = line.strip().split(' ', 2)
                if len(parts) >= 2:
                    paired_macs.add(parts[1])

        for mac_address in paired_macs:
            is_connected = False
            alias = mac_address # Default name
            success_info, stdout_info, stderr_info = AudioManager._run_command(['bluetoothctl', 'info', mac_address], timeout=5)
            if success_info:
                if 'Connected: yes' in stdout_info: is_connected = True
                alias_match = re.search(r'Alias:\s*(.*)', stdout_info)
                if alias_match: alias = alias_match.group(1).strip()
                name_match = re.search(r'Name:\s*(.*)', stdout_info) # Fallback to Name if Alias fails
                if not alias_match and name_match: alias = name_match.group(1).strip()
            else:
                 logger.warning(f"Could not get info for paired device {mac_address}: {stderr_info}")

            devices.append({
                'mac_address': mac_address,
                'name': alias,
                'type': 'bluetooth',
                'connected': is_connected,
                'paired': True # Mark as paired
            })
        logger.info(f"Listed paired Bluetooth devices: {len(devices)}")
        return devices

    @staticmethod
    def discover_bluetooth_devices(scan_duration=BLUETOOTH_SCAN_DURATION):
        """Kısa süreliğine Bluetooth taraması yapar ve bulunan tüm cihazları listeler."""
        logger.info(f"Starting Bluetooth discovery for {scan_duration} seconds...")
        scan_process = None
        discovered_devices = {} # Use dict to avoid duplicates by MAC

        try:
            # Start scanning in the background
            scan_process = subprocess.Popen(['bluetoothctl', 'scan', 'on'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(scan_duration) # Wait for devices to be discovered
        except Exception as e:
            logger.error(f"Failed to start Bluetooth scan: {e}")
        finally:
            # Ensure scanning is turned off
            if scan_process:
                try:
                    scan_process.terminate() # Try terminating gently first
                    scan_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    scan_process.kill() # Force kill if terminate fails
                except Exception: pass # Ignore other errors during cleanup
            # Explicitly turn scan off
            off_success, _, off_stderr = AudioManager._run_command(['bluetoothctl', 'scan', 'off'], timeout=5)
            if not off_success: logger.warning(f"Could not turn off Bluetooth scan: {off_stderr}")

        logger.info("Bluetooth discovery finished. Fetching device list...")

        # Get all devices visible after scan
        success_devs, stdout_devs, stderr_devs = AudioManager._run_command(['bluetoothctl', 'devices'], timeout=10)
        if not success_devs:
            logger.error(f"Error listing discovered Bluetooth devices: {stderr_devs}")
            return []

        # Get paired devices to mark them
        success_paired, stdout_paired, stderr_paired = AudioManager._run_command(['bluetoothctl', 'paired-devices'], timeout=10)
        paired_macs = set()
        if success_paired:
            for line in stdout_paired.splitlines():
                if line.startswith("Device"):
                    parts = line.strip().split(' ', 1)
                    if len(parts) >= 2: paired_macs.add(parts[1].split(' ')[0]) # Get only MAC
        else:
            logger.warning(f"Could not get paired devices list while processing discovered devices: {stderr_paired}")

        # Process discovered devices
        for line in stdout_devs.splitlines():
            if line.startswith("Device"):
                parts = line.strip().split(' ', 2)
                if len(parts) >= 3:
                    mac_address = parts[1]
                    device_name = parts[2]
                    is_paired = mac_address in paired_macs
                    is_connected = False # Assume not connected unless confirmed

                    # Get connection status only for paired devices (info often fails for unpaired)
                    if is_paired:
                        success_info, stdout_info, _ = AudioManager._run_command(['bluetoothctl', 'info', mac_address], timeout=3)
                        if success_info and 'Connected: yes' in stdout_info:
                            is_connected = True
                        # Use alias from info if available for paired devices
                        alias_match = re.search(r'Alias:\s*(.*)', stdout_info)
                        if alias_match: device_name = alias_match.group(1).strip()


                    discovered_devices[mac_address] = {
                        'mac_address': mac_address,
                        'name': device_name,
                        'type': 'bluetooth',
                        'connected': is_connected,
                        'paired': is_paired
                    }

        result_list = list(discovered_devices.values())
        logger.info(f"Discovered {len(result_list)} Bluetooth devices after scan.")
        return result_list


    @staticmethod
    def pair_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazını eşleştirir ve bağlar."""
        try:
            logging.info(f"Pairing/Connecting Bluetooth device {mac_address}...")
            try: subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=5)
            except Exception: pass
            time.sleep(1)
            # Pair first
            logger.info(f"Attempting to pair with {mac_address}...")
            pair_cmd = subprocess.run(['bluetoothctl', 'pair', mac_address], capture_output=True, text=True, timeout=20) # Pairing can take time
            if pair_cmd.returncode != 0 and "already exists" not in pair_cmd.stderr.lower():
                logger.error(f"Pairing failed for {mac_address}: {pair_cmd.stderr}")
                # Try trusting and connecting anyway, sometimes pairing isn't strictly needed if trusted
                # return False # Optionally exit here if pairing fails
            else:
                 logger.info(f"Pairing successful or device already paired: {mac_address}")

            # Trust the device
            trust_cmd = subprocess.run(['bluetoothctl', 'trust', mac_address], capture_output=True, text=True, timeout=10)
            if trust_cmd.returncode != 0: logging.warning(f"Could not trust device {mac_address} (might be already trusted): {trust_cmd.stderr}")
            else: logger.info(f"Device trusted: {mac_address}")

            # Try connecting
            connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
            if connect_cmd.returncode == 0 and ('Connection successful' in connect_cmd.stdout.lower() or 'already connected' in connect_cmd.stderr.lower()):
                logging.info(f"Bluetooth device successfully connected: {mac_address}"); time.sleep(3); return True
            else:
                logging.warning(f"First connection attempt failed ({mac_address}), retrying... Error: {connect_cmd.stderr}"); time.sleep(3)
                connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
                if connect_cmd.returncode == 0 and ('Connection successful' in connect_cmd.stdout.lower() or 'already connected' in connect_cmd.stderr.lower()):
                     logging.info(f"Bluetooth device successfully connected on second attempt: {mac_address}"); time.sleep(3); return True
                else:
                     logging.error(f"Bluetooth device connection failed ({mac_address}): {connect_cmd.stderr}")
                     subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=10); return False
        except FileNotFoundError: logger.error("Command 'bluetoothctl' not found."); return False
        except subprocess.TimeoutExpired: logger.error(f"Timeout during Bluetooth operation for {mac_address}."); return False
        except Exception as e: logger.error(f"Error during Bluetooth pairing/connection ({mac_address}): {e}", exc_info=True); return False

    @staticmethod
    def disconnect_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazının bağlantısını keser."""
        try:
            logging.info(f"Disconnecting Bluetooth device {mac_address}...")
            cmd = subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, check=True, timeout=10)
            logging.info(f"Bluetooth device successfully disconnected: {mac_address}"); time.sleep(2); return True
        except FileNotFoundError: logger.error("Command 'bluetoothctl' not found."); return False
        except subprocess.CalledProcessError as e:
             logger.error(f"Error disconnecting Bluetooth device ({mac_address}): {e.stderr}")
             if 'not connected' in e.stderr.lower(): logging.info(f"Device ({mac_address}) was already disconnected."); return True
             return False
        except subprocess.TimeoutExpired: logger.error(f"Timeout disconnecting Bluetooth device ({mac_address})."); return False
        except Exception as e: logger.error(f"Error during Bluetooth disconnection ({mac_address}): {e}", exc_info=True); return False

# --- Flask Uygulaması ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
app.jinja_env.globals['AudioManager'] = AudioManager
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION # Şablona ekle

# --- Global Değişkenler ---
spotify_client = None
song_queue = []
user_requests = {}
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] }
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
auto_advance_enabled = True

# --- Yardımcı Fonksiyonlar (Ayarlar, Token, Auth - Değişiklik Yok) ---
def load_settings():
    default_settings = {'max_queue_length': 20, 'max_user_requests': 5, 'active_device_id': None, 'active_genres': ALLOWED_GENRES[:5]}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f: loaded = json.load(f)
            for key in default_settings:
                if key in loaded: default_settings[key] = loaded[key]
            logger.info(f"Ayarlar yüklendi: {SETTINGS_FILE}")
        except Exception as e: logger.error(f"Ayar dosyası ({SETTINGS_FILE}) okunamadı/bozuk: {e}")
    else: logger.info(f"Ayar dosyası bulunamadı, varsayılanlar oluşturuluyor: {SETTINGS_FILE}"); save_settings(default_settings)
    return default_settings
def save_settings(current_settings):
    try:
        with open(SETTINGS_FILE, 'w') as f: json.dump(current_settings, f, indent=4)
        logger.info(f"Ayarlar kaydedildi: {SETTINGS_FILE}")
    except Exception as e: logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)
settings = load_settings()
def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f: return json.load(f)
        except Exception as e: logger.error(f"Token dosyası okuma hatası ({TOKEN_FILE}): {e}")
    return None
def save_token(token_info):
    try:
        with open(TOKEN_FILE, 'w') as f: json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi.")
    except Exception as e: logger.error(f"Token kaydetme hatası: {e}")
def get_spotify_auth():
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_'):
         raise ValueError("Spotify Client ID ve Secret app.py içinde ayarlanmamış!")
    return SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPE, open_browser=False, cache_path=None)
def get_spotify_client():
    global spotify_client
    token_info = load_token()
    if not token_info: return None
    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(e); return None
    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token süresi dolmuş, yenileniyor...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val: logger.error("Refresh token bulunamadı."); os.remove(TOKEN_FILE); spotify_client = None; return None
            new_token_info = auth_manager.refresh_access_token(refresh_token_val)
            if not new_token_info: logger.error("Token yenilenemedi."); os.remove(TOKEN_FILE); spotify_client = None; return None
            token_info = new_token_info; save_token(token_info)
        new_spotify_client = spotipy.Spotify(auth=token_info.get('access_token'))
        try: new_spotify_client.current_user(); spotify_client = new_spotify_client; return spotify_client
        except Exception as e:
            logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası: {e}")
            if "invalid access token" in str(e).lower() or "token expired" in str(e).lower() or "unauthorized" in str(e).lower(): os.remove(TOKEN_FILE)
            spotify_client = None; return None
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API hatası (token işlemi sırasında): {e}")
        if e.http_status == 401 or e.http_status == 403: os.remove(TOKEN_FILE)
        spotify_client = None; return None
    except Exception as e:
        logger.error(f"Spotify token işlemi sırasında genel hata: {e}", exc_info=True)
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None; return None

# --- Admin Giriş Decorator'ı (Değişiklik Yok) ---
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            flash("Bu sayfaya erişmek için yönetici girişi yapmalısınız.", "warning")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Zaman Profili ve Öneri Fonksiyonları (Değişiklik Yok) ---
def get_current_time_profile():
    hour = time.localtime().tm_hour
    if 6 <= hour < 12: return 'sabah'
    elif 12 <= hour < 18: return 'oglen'
    elif 18 <= hour < 24: return 'aksam'
    else: return 'gece'
def update_time_profile(track_id, spotify):
    if not spotify or not track_id: logger.warning("update_time_profile: eksik parametre."); return
    profile_name = get_current_time_profile()
    logger.debug(f"'{profile_name}' profili güncelleniyor, track_id: {track_id}")
    try:
        track_info = spotify.track(track_id, market='TR')
        if not track_info: logger.warning(f"Şarkı detayı alınamadı: {track_id}"); return
        track_name = track_info.get('name', '?'); artists = track_info.get('artists')
        primary_artist_id = artists[0].get('id') if artists else None; primary_artist_name = artists[0].get('name') if artists else '?'
        profile_entry = {'id': track_id, 'artist_id': primary_artist_id, 'name': track_name, 'artist_name': primary_artist_name}
        time_profiles[profile_name].append(profile_entry)
        if len(time_profiles[profile_name]) > 5: time_profiles[profile_name] = time_profiles[profile_name][-5:]
        logger.info(f"'{profile_name}' profiline eklendi: '{track_name}'")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken hata (ID: {track_id}): {e}", exc_info=True)
def suggest_song_for_time(spotify):
    if not spotify: logger.warning("suggest_song_for_time: spotify istemcisi eksik."); return None
    profile_name = get_current_time_profile(); profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None
    seed_tracks = []; seed_artists = []
    last_entry = profile_data[-1]
    if last_entry.get('id'): seed_tracks.append(last_entry['id'])
    if last_entry.get('artist_id'): seed_artists.append(last_entry['artist_id'])
    if not seed_tracks and not seed_artists: logger.warning(f"'{profile_name}' profili öneri için tohum içermiyor."); return None
    try:
        logger.info(f"'{profile_name}' için öneri isteniyor: seeds={seed_tracks+seed_artists}")
        recs = spotify.recommendations(seed_tracks=seed_tracks, seed_artists=seed_artists, limit=5, market='TR')
        if recs and recs.get('tracks'):
            for suggested_track in recs['tracks']:
                 if not any(song.get('id') == suggested_track['id'] for song in song_queue):
                    logger.info(f"'{profile_name}' için öneri bulundu: '{suggested_track.get('name')}'")
                    artists = suggested_track.get('artists', []); suggested_track['artist'] = ', '.join([a.get('name') for a in artists]) if artists else '?'
                    return suggested_track
            logger.info(f"'{profile_name}' önerileri kuyrukta mevcut.")
        else: logger.info(f"'{profile_name}' için öneri alınamadı."); return None
    except Exception as e: logger.error(f"'{profile_name}' için öneri alınırken hata: {e}", exc_info=True); return None

# --- Flask Rotaları ---

@app.route('/')
def index():
    """Ana sayfayı gösterir."""
    return render_template('index.html', allowed_genres=settings.get('active_genres', ALLOWED_GENRES))

@app.route('/admin')
def admin():
    """Admin giriş sayfasını veya paneli gösterir."""
    if session.get('admin_logged_in'): return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    """Admin giriş isteğini işler."""
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123")
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True; logger.info("Admin girişi başarılı")
        flash("Yönetim paneline hoş geldiniz!", "success"); return redirect(url_for('admin_panel'))
    else:
        logger.warning("Başarısız admin girişi denemesi"); flash("Yanlış şifre girdiniz.", "danger")
        return redirect(url_for('admin'))

@app.route('/logout')
@admin_login_required
def logout():
    """Admin çıkış işlemini yapar."""
    global spotify_client; spotify_client = None; session.clear()
    logger.info("Admin çıkışı yapıldı."); flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    """Yönetim panelini gösterir."""
    global auto_advance_enabled
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None

    # PipeWire sink'lerini ve varsayılanı al
    pipewire_sinks, default_pipewire_sink_node_name = AudioManager.get_pipewire_sinks()

    if spotify:
        try:
            result = spotify.devices(); spotify_devices = result.get('devices', [])
            spotify_authenticated = True; session['spotify_authenticated'] = True
            try: user = spotify.current_user(); spotify_user = user.get('display_name', '?'); session['spotify_user'] = spotify_user
            except Exception as user_err: logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}"); session.pop('spotify_user', None)
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'):
                    item = playback['item']; is_playing = playback.get('is_playing', False)
                    track_name = item.get('name', '?'); artists = item.get('artists', [])
                    artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
                    images = item.get('album', {}).get('images', []); image_url = images[0].get('url') if images else None
                    currently_playing_info = {'id': item.get('id'), 'name': track_name, 'artist': artist_name, 'image_url': image_url, 'is_playing': is_playing}
                    logger.debug(f"Şu An Çalıyor: {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'}")
            except Exception as pb_err: logger.warning(f"Çalma durumu alınamadı: {pb_err}")
        except Exception as e:
            logger.error(f"Spotify API hatası (Admin Panel): {e}")
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE); spotify_client = None
    else: spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)

    return render_template(
        'admin_panel.html',
        settings=settings,
        spotify_devices=spotify_devices,
        queue=song_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        pipewire_sinks=pipewire_sinks, # PipeWire listesi
        default_pipewire_sink=default_pipewire_sink_node_name, # Varsayılan PipeWire sink node adı
        currently_playing_info=currently_playing_info,
        auto_advance_enabled=auto_advance_enabled
    )

# --- Çalma Kontrol Rotaları (Değişiklik Yok) ---
@app.route('/player/pause')
@admin_login_required
def player_pause():
    global auto_advance_enabled; spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        logger.info(f"Admin: Duraklatma isteği (Cihaz: {active_spotify_connect_device_id or '?'}).")
        spotify.pause_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = False; logger.info("Admin: Otomatik geçiş DURAKLATILDI.")
        flash('Müzik duraklatıldı ve otomatik geçiş kapatıldı.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify duraklatma hatası: {e}")
        if e.http_status == 401 or e.http_status == 403: flash('Spotify yetkilendirme hatası.', 'danger'); global spotify_client; spotify_client = None; os.remove(TOKEN_FILE)
        elif e.http_status == 404: flash(f'Duraklatma hatası: Cihaz bulunamadı ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE': flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        else: flash(f'Spotify duraklatma hatası: {e.msg}', 'danger')
    except Exception as e: logger.error(f"Duraklatma sırasında genel hata: {e}", exc_info=True); flash('Müzik duraklatılırken bir hata oluştu.', 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/player/resume')
@admin_login_required
def player_resume():
    global auto_advance_enabled; spotify = get_spotify_client()
    active_spotify_connect_device_id = settings.get('active_device_id')
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        logger.info(f"Admin: Sürdürme isteği (Cihaz: {active_spotify_connect_device_id or '?'}).")
        spotify.start_playback(device_id=active_spotify_connect_device_id)
        auto_advance_enabled = True; logger.info("Admin: Otomatik geçiş SÜRDÜRÜLDÜ.")
        flash('Müzik sürdürüldü ve otomatik sıraya geçiş açıldı.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify sürdürme hatası: {e}")
        if e.http_status == 401 or e.http_status == 403: flash('Spotify yetkilendirme hatası.', 'danger'); global spotify_client; spotify_client = None; os.remove(TOKEN_FILE)
        elif e.http_status == 404: flash(f'Sürdürme hatası: Cihaz bulunamadı ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE': flash('Aktif Spotify cihazı bulunamadı!', 'warning')
        elif e.reason == 'PREMIUM_REQUIRED': flash('Bu işlem için Spotify Premium gerekli.', 'warning')
        else: flash(f'Spotify sürdürme hatası: {e.msg}', 'danger')
    except Exception as e: logger.error(f"Sürdürme sırasında genel hata: {e}", exc_info=True); flash('Müzik sürdürülürken bir hata oluştu.', 'danger')
    return redirect(url_for('admin_panel'))

# --- Diğer Rotalar (Spotify Connect, Ayarlar, Auth, Search, Queue - Değişiklik Yok) ---
@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    spotify = get_spotify_client()
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        result = spotify.devices(); devices = result.get('devices', [])
        logger.info(f"Spotify Connect Cihazları yenilendi: {len(devices)} cihaz")
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device and not any(d['id'] == active_spotify_connect_device for d in devices):
            logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device}) listede yok. Ayar temizleniyor.")
            settings['active_device_id'] = None; save_settings(settings)
            flash('Ayarlardaki aktif Spotify Connect cihazı artık mevcut değil.', 'warning')
        flash('Spotify Connect cihaz listesi yenilendi.', 'info')
    except Exception as e:
        logger.error(f"Spotify Connect Cihazlarını yenilerken hata: {e}")
        flash('Spotify Connect cihaz listesi yenilenirken bir hata oluştu.', 'danger')
        if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403): global spotify_client; spotify_client = None; os.remove(TOKEN_FILE)
    return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    global settings
    try:
        settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        settings['active_genres'] = [genre for genre in ALLOWED_GENRES if request.form.get(f'genre_{genre}')]
        if 'active_spotify_connect_device_id' in request.form:
             new_spotify_device_id = request.form.get('active_spotify_connect_device_id')
             settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {settings['active_device_id']}")
        save_settings(settings); logger.info(f"Ayarlar güncellendi: {settings}")
        flash("Ayarlar başarıyla güncellendi.", "success")
    except ValueError: logger.error("Ayarları güncellerken geçersiz sayısal değer."); flash("Geçersiz sayısal değer girildi!", "danger")
    except Exception as e: logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True); flash("Ayarlar güncellenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    if os.path.exists(TOKEN_FILE): logger.warning("Mevcut token varken yeniden yetkilendirme.")
    try: auth_manager = get_spotify_auth(); auth_url = auth_manager.get_authorize_url(); logger.info("Spotify yetkilendirme URL'sine yönlendiriliyor."); return redirect(auth_url)
    except ValueError as e: logger.error(f"Spotify yetkilendirme hatası: {e}"); flash(f"Spotify Yetkilendirme Hatası: {e}", "danger"); return redirect(url_for('admin_panel'))
    except Exception as e: logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True); flash("Spotify yetkilendirme başlatılamadı.", "danger"); return redirect(url_for('admin_panel'))

@app.route('/callback')
def callback():
    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(f"Callback hatası: {e}"); return f"Callback Hatası: {e}", 500
    if 'error' in request.args: error = request.args.get('error'); logger.error(f"Spotify yetkilendirme hatası (callback): {error}"); return f"Spotify Yetkilendirme Hatası: {error}", 400
    if 'code' not in request.args: logger.error("Callback'te 'code' yok."); return "Geçersiz callback isteği.", 400
    code = request.args.get('code')
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        if not token_info: logger.error("Spotify'dan token alınamadı."); return "Token alınamadı.", 500
        save_token(token_info); global spotify_client; spotify_client = None
        logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
        if session.get('admin_logged_in'): flash("Spotify yetkilendirmesi başarıyla tamamlandı!", "success"); return redirect(url_for('admin_panel'))
        else: return redirect(url_for('index'))
    except Exception as e: logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True); return "Token işlenirken bir hata oluştu.", 500

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search_query')
    logger.info(f"Arama isteği: '{search_query}'")
    if not search_query: return jsonify({'error': 'Arama terimi girin.'}), 400
    spotify = get_spotify_client()
    if not spotify: logger.error("Arama: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503
    try:
        results = spotify.search(q=search_query, type='track', limit=10, market='TR')
        tracks = results.get('tracks', {}).get('items', [])
        logger.info(f"Arama sonucu: {len(tracks)} şarkı.")
        search_results = []
        for track in tracks:
            artists = track.get('artists', []); album = track.get('album', {}); images = album.get('images', [])
            search_results.append({'id': track.get('id'), 'name': track.get('name'), 'artist': ', '.join([a.get('name') for a in artists]), 'album': album.get('name'), 'image': images[-1].get('url') if images else None})
        return jsonify({'results': search_results})
    except Exception as e: logger.error(f"Spotify araması hatası: {e}", exc_info=True); return jsonify({'error': 'Arama sırasında sorun oluştu.'}), 500

@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
    song_input = request.form.get('song_id', '').strip()
    if not song_input: flash("Şarkı ID/URL girin.", "warning"); return redirect(url_for('admin_panel'))
    song_id = song_input
    if 'https://developer.spotify.com/documentation/web-api/reference/add-to-queue2' in song_input:
        match = re.search(r'/track/([a-zA-Z0-9]+)', song_input)
        if match: song_id = match.group(1)
        else: logger.warning(f"Geçersiz Spotify URL: {song_input}"); flash("Geçersiz Spotify URL.", "danger"); return redirect(url_for('admin_panel'))
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning(f"Kuyruk dolu, admin ekleyemedi: {song_id}"); flash("Kuyruk dolu!", "warning"); return redirect(url_for('admin_panel'))
    spotify = get_spotify_client()
    if not spotify: logger.warning("Admin ekleme: Spotify gerekli"); flash("Spotify yetkilendirmesi gerekli.", "warning"); return redirect(url_for('spotify_auth'))
    try:
        song_info = spotify.track(song_id, market='TR')
        if not song_info: logger.warning(f"Admin ekleme: Şarkı bulunamadı ID={song_id}"); flash(f"Şarkı bulunamadı (ID: {song_id}).", "danger"); return redirect(url_for('admin_panel'))
        artists = song_info.get('artists');
        song_queue.append({'id': song_id, 'name': song_info.get('name', '?'), 'artist': ', '.join([a.get('name') for a in artists]), 'added_by': 'admin', 'added_at': time.time()})
        logger.info(f"Şarkı eklendi (Admin): {song_id} - {song_info.get('name')}")
        flash(f"'{song_info.get('name')}' eklendi.", "success"); update_time_profile(song_id, spotify)
    except spotipy.SpotifyException as e:
        logger.error(f"Admin eklerken Spotify hatası (ID={song_id}): {e}")
        if e.http_status == 401 or e.http_status == 403: flash("Spotify yetkilendirme hatası.", "danger"); return redirect(url_for('spotify_auth'))
        else: flash(f"Spotify hatası: {e.msg}", "danger")
    except Exception as e: logger.error(f"Admin eklerken genel hata (ID={song_id}): {e}", exc_info=True); flash("Şarkı eklenirken hata.", "danger")
    return redirect(url_for('admin_panel'))

# --- Bluetooth API Rotaları (Değişiklik Yok) ---
@app.route('/pair-bluetooth-device', methods=['POST'])
@admin_login_required
def pair_bluetooth_device_route():
    data = request.get_json()
    mac = data.get('mac_address')
    if not mac:
        return jsonify({'success': False, 'message': 'MAC adresi eksik.'}), 400
    success = AudioManager.pair_bluetooth_device(mac)
    return jsonify({'success': success, 'message': 'Cihaz eşleştirildi.' if success else 'Eşleştirme başarısız.'})

@app.route('/connect-bluetooth-device', methods=['POST'])
@admin_login_required
def connect_bluetooth_device_route():
    data = request.get_json()
    mac = data.get('mac_address')
    if not mac:
        return jsonify({'success': False, 'message': 'MAC adresi eksik.'}), 400
    success = AudioManager.pair_bluetooth_device(mac)  # pairing bağlamayı da kapsar
    return jsonify({'success': success, 'message': 'Cihaz bağlandı.' if success else 'Bağlantı başarısız.'})

@app.route('/disconnect-bluetooth-device', methods=['POST'])
@admin_login_required
def disconnect_bluetooth_device_route():
    data = request.get_json()
    mac = data.get('mac_address')
    if not mac:
        return jsonify({'success': False, 'message': 'MAC adresi eksik.'}), 400
    success = AudioManager.disconnect_bluetooth_device(mac)
    return jsonify({'success': success, 'message': 'Bağlantı kesildi.' if success else 'Bağlantı kesilemedi.'})

# --- Queue Rotaları (Değişiklik Yok) ---
@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    if not request.is_json: return jsonify({'error': 'Geçersiz format.'}), 400
    data = request.get_json(); track_id = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: track_id={track_id}")
    if not track_id: return jsonify({'error': 'Eksik ID.'}), 400
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning("Kuyruk dolu."); return jsonify({'error': 'Kuyruk dolu.'}), 429
    user_ip = request.remote_addr; max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: logger.warning(f"Limit aşıldı: {user_ip}"); return jsonify({'error': f'Limit aşıldı ({max_requests}).'}), 429
    spotify = get_spotify_client()
    if not spotify: logger.error("Ekleme: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı yok.'}), 503
    try:
        update_time_profile(track_id, spotify)
        profile_name = get_current_time_profile()
        if profile_name in time_profiles and time_profiles[profile_name] and time_profiles[profile_name][-1].get('id') == track_id:
            added_track_info = time_profiles[profile_name][-1]
            song_queue.append({'id': added_track_info['id'], 'name': added_track_info['name'], 'artist': added_track_info['artist_name'], 'added_by': user_ip, 'added_at': time.time()})
            user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
            logger.info(f"Şarkı eklendi: {added_track_info['name']}. Kuyruk: {len(song_queue)}")
            return jsonify({'success': True, 'message': 'Şarkı kuyruğa eklendi!'})
        else: logger.error(f"Profil güncellenemediği için eklenemedi: {track_id}"); return jsonify({'error': 'Şarkı eklenirken sorun oluştu (profil).'}), 500
    except Exception as e: logger.error(f"Kuyruğa ekleme hatası (ID: {track_id}): {e}", exc_info=True); return jsonify({'error': 'Şarkı eklenirken sorun oluştu.'}), 500

@app.route('/remove-song/<song_id>', methods=['POST'])
@admin_login_required
def remove_song(song_id):
    global song_queue; initial_length = len(song_queue)
    song_queue = [song for song in song_queue if song.get('id') != song_id]
    if len(song_queue) < initial_length: logger.info(f"Şarkı kaldırıldı (Admin): ID={song_id}"); flash("Şarkı kaldırıldı.", "success")
    else: logger.warning(f"Kaldırılacak şarkı bulunamadı: ID={song_id}"); flash("Şarkı bulunamadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue, user_requests; song_queue = []; user_requests = {}
    logger.info("Kuyruk temizlendi (Admin)."); flash("Kuyruk temizlendi.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/queue')
def view_queue():
    global spotify_client; current_q = list(song_queue); currently_playing_info = None
    spotify = get_spotify_client()
    if spotify:
        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']; is_playing = playback.get('is_playing', False)
                track_name = item.get('name'); artists = item.get('artists', [])
                artist_name = ', '.join([a.get('name') for a in artists]); images = item.get('album', {}).get('images', [])
                image_url = images[-1].get('url') if images else None
                currently_playing_info = {'name': track_name, 'artist': artist_name, 'image_url': image_url, 'is_playing': is_playing}
                logger.debug(f"Şu An Çalıyor (Kuyruk): {track_name} - {'Çalıyor' if is_playing else 'Duraklatıldı'}")
        except spotipy.SpotifyException as e:
            logger.warning(f"Çalma durumu hatası (Kuyruk): {e}")
            if e.http_status == 401 or e.http_status == 403: spotify_client = None; os.remove(TOKEN_FILE)
        except Exception as e: logger.error(f"Çalma durumu genel hatası (Kuyruk): {e}", exc_info=True)
    return render_template('queue.html', queue=current_q, currently_playing_info=currently_playing_info)

@app.route('/api/queue')
def api_get_queue():
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue), 'max_length': settings.get('max_queue_length', 20)})

# --- PipeWire/Bluetooth API Rotaları ---
@app.route('/api/pipewire-sinks') # URL güncellendi
@admin_login_required
def api_pipewire_sinks():
    """Mevcut PipeWire sink'lerini (Node) ve varsayılanı döndürür."""
    sinks, default_sink_node_name = AudioManager.get_pipewire_sinks()
    return jsonify({'sinks': sinks, 'default_sink': default_sink_node_name})

@app.route('/api/set-pipewire-sink', methods=['POST']) # URL ve parametre güncellendi
@admin_login_required
def api_set_pipewire_sink():
    """Seçilen node'u sistemin varsayılan PipeWire sink'i olarak ayarlar."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); node_name = data.get('node_name') # Parametre adı değişti
    if not node_name: logger.error("API isteğinde 'node_name' eksik."); return jsonify({'success': False, 'error': 'Node adı gerekli'}), 400

    logger.info(f"API: Varsayılan PipeWire sink ayarlama isteği: {node_name}")
    success, message = AudioManager.set_default_pipewire_sink(node_name)

    # İşlem sonrası güncel listeleri al
    updated_pipewire_sinks, new_default_sink_node_name = AudioManager.get_pipewire_sinks()
    # Bluetooth listesini de alalım (bağlantı durumu değişmiş olabilir)
    updated_bt_devices = AudioManager.get_paired_bluetooth_devices() # Sadece eşleşmişleri alalım
    status_code = 200 if success else 500
    response_data = {
        'success': success,
        'pipewire_sinks': updated_pipewire_sinks, # Anahtar adı değişti
        'default_sink': new_default_sink_node_name,
        'bluetooth_devices': updated_bt_devices
    }
    if success: response_data['message'] = message
    else: response_data['error'] = message
    return jsonify(response_data), status_code

@app.route('/api/scan-bluetooth') # Bu endpoint artık sadece eşleşmişleri listeler
@admin_login_required
def api_scan_bluetooth():
    """Eşleştirilmiş Bluetooth cihazlarını ve durumlarını listeler."""
    logger.info("API: Eşleştirilmiş Bluetooth cihaz listeleme isteği alındı.")
    devices = AudioManager.get_paired_bluetooth_devices()
    return jsonify({'success': True, 'devices': devices})

@app.route('/api/discover-bluetooth') # Yeni endpoint
@admin_login_required
def api_discover_bluetooth():
    """Kısa süreliğine Bluetooth taraması yapar ve bulunan tüm cihazları listeler."""
    logger.info(f"API: Yeni Bluetooth cihaz keşfi isteği alındı (Süre: {BLUETOOTH_SCAN_DURATION}s).")
    devices = AudioManager.discover_bluetooth_devices(scan_duration=BLUETOOTH_SCAN_DURATION)
    # Hata durumu kontrolü eklenebilir, ancak discover_bluetooth_devices boş liste dönebilir
    return jsonify({'success': True, 'devices': devices})


@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazını eşleştirir/bağlar."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
    logger.info(f"API: Bluetooth cihazı eşleştirme/bağlama isteği: {mac_address}")
    success = AudioManager.pair_bluetooth_device(mac_address)
    # İşlem sonrası güncel listeleri al (eşleşmişleri ve pipewire'ı)
    updated_pipewire_sinks, new_default_sink = AudioManager.get_pipewire_sinks()
    updated_bt_devices = AudioManager.get_paired_bluetooth_devices()
    message = f"Bluetooth cihazı bağlandı/eşleştirildi: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlanamadı/eşleştirilemedi."
    status_code = 200 if success else 500
    return jsonify({
        'success': success,
        'message': message,
        'pipewire_sinks': updated_pipewire_sinks, # Anahtar adı değişti
        'default_sink': new_default_sink,
        'bluetooth_devices': updated_bt_devices # Sadece eşleşmişleri döndür
    }), status_code

@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazının bağlantısını keser."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
    logger.info(f"API: Bluetooth cihazı bağlantısını kesme isteği: {mac_address}")
    success = AudioManager.disconnect_bluetooth_device(mac_address)
    # İşlem sonrası güncel listeleri al (eşleşmişleri ve pipewire'ı)
    updated_pipewire_sinks, new_default_sink = AudioManager.get_pipewire_sinks()
    updated_bt_devices = AudioManager.get_paired_bluetooth_devices()
    message = f"Bluetooth cihazı bağlantısı kesildi: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlantısı kesilemedi."
    status_code = 200 if success else 500
    return jsonify({
        'success': success,
        'message': message,
        'pipewire_sinks': updated_pipewire_sinks, # Anahtar adı değişti
        'default_sink': new_default_sink,
        'bluetooth_devices': updated_bt_devices # Sadece eşleşmişleri döndür
    }), status_code


# --- Arka Plan Şarkı Çalma İş Parçacığı (Değişiklik Yok) ---
def background_queue_player():
    global spotify_client, song_queue, user_requests, settings, auto_advance_enabled
    logger.info("Arka plan şarkı çalma/öneri görevi başlatılıyor...")
    last_played_song_id = None; last_suggested_song_id = None
    while True:
        try:
            spotify = get_spotify_client()
            active_spotify_connect_device_id = settings.get('active_device_id')
            if not spotify or not active_spotify_connect_device_id: time.sleep(10); continue
            current_playback = None
            try: current_playback = spotify.current_playback(additional_types='track,episode', market='TR')
            except spotipy.SpotifyException as pb_err:
                logger.error(f"Arka plan: Playback kontrol hatası: {pb_err}")
                if pb_err.http_status == 401 or pb_err.http_status == 403: spotify_client = None; os.remove(TOKEN_FILE)
                time.sleep(10); continue
            except Exception as pb_err: logger.error(f"Arka plan: Playback kontrol genel hata: {pb_err}", exc_info=True); time.sleep(15); continue
            is_playing_now = False; current_track_id_now = None
            if current_playback:
                is_playing_now = current_playback.get('is_playing', False); item = current_playback.get('item')
                current_track_id_now = item.get('id') if item else None
            if song_queue and not is_playing_now and auto_advance_enabled:
                logger.info(f"Arka plan: Çalma durdu, otomatik ilerleme aktif. Kuyruktan çalınıyor...")
                next_song = song_queue.pop(0)
                if next_song.get('id') == last_played_song_id: logger.debug(f"Şarkı ({next_song.get('name')}) zaten son çalınandı, atlanıyor."); last_played_song_id = None; time.sleep(1); continue
                logger.info(f"Arka plan: Çalınacak: {next_song.get('name')} ({next_song.get('id')})")
                try:
                    spotify.start_playback(device_id=active_spotify_connect_device_id, uris=[f"spotify:track:{next_song['id']}"])
                    logger.info(f"===> Şarkı çalmaya başlandı: {next_song.get('name')}")
                    last_played_song_id = next_song['id']; last_suggested_song_id = None
                    user_ip = next_song.get('added_by')
                    if user_ip and user_ip != 'admin' and user_ip != 'auto-time': user_requests[user_ip] = max(0, user_requests.get(user_ip, 0) - 1); logger.debug(f"Kullanıcı {user_ip} limiti azaltıldı: {user_requests.get(user_ip)}")
                    time.sleep(1); continue
                except spotipy.SpotifyException as start_err:
                    logger.error(f"Arka plan: Şarkı başlatılamadı ({next_song.get('id')}): {start_err}")
                    song_queue.insert(0, next_song)
                    if start_err.http_status == 401 or start_err.http_status == 403: spotify_client = None; os.remove(TOKEN_FILE)
                    elif start_err.http_status == 404 and 'device_id' in str(start_err).lower(): logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device_id}) bulunamadı."); settings['active_device_id'] = None; save_settings(settings)
                    time.sleep(5); continue
                except Exception as start_err: logger.error(f"Arka plan: Şarkı başlatılırken genel hata ({next_song.get('id')}): {start_err}", exc_info=True); song_queue.insert(0, next_song); time.sleep(10); continue
            elif not song_queue and not is_playing_now:
                suggested = suggest_song_for_time(spotify)
                if suggested and suggested.get('id') != last_suggested_song_id:
                    song_queue.append({'id': suggested['id'], 'name': suggested['name'], 'artist': suggested.get('artist', '?'), 'added_by': 'auto-time', 'added_at': time.time()})
                    last_suggested_song_id = suggested['id']; logger.info(f"Otomatik öneri eklendi: {suggested['name']}")
            elif is_playing_now:
                 if current_track_id_now and current_track_id_now != last_played_song_id: logger.debug(f"Arka plan: Yeni şarkı algılandı: {current_track_id_now}"); last_played_song_id = current_track_id_now; last_suggested_song_id = None
            time.sleep(5)
        except Exception as loop_err: logger.error(f"Arka plan döngü hatası: {loop_err}", exc_info=True); time.sleep(15)

# --- Uygulama Başlangıcı ---
def check_token_on_startup():
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client()
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Yetkilendirme gerekli olabilir.")

def start_queue_player():
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("=================================================")
    logger.info(f"Ayarlar Yüklendi: {SETTINGS_FILE}")

    # API Bilgileri kontrolü
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.error("LÜTFEN app.py dosyasında Spotify API bilgilerinizi (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) doğru şekilde ayarlayın!")
    else:
         logger.info("Spotify API bilgileri app.py içinde tanımlı görünüyor.")
         logger.info(f"Kullanılacak Redirect URI: {SPOTIFY_REDIRECT_URI}")
         logger.info("!!! BU URI'nin Spotify Developer Dashboard'da kayıtlı olduğundan emin olun !!!")

    # Başlangıç kontrolleri ve arka plan görevini başlatma
    check_token_on_startup()
    start_queue_player()

    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişilebilir.")
    logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişilebilir.")

    # debug=True otomatik yeniden yüklemeyi sağlar
    app.run(host='0.0.0.0', port=port, debug=True)
