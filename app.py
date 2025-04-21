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
# Eğer raspotify.service veya conf dosyanız farklı bir yerdeyse,
# aşağıdaki yolları buna göre düzenleyin.
RASPOTIFY_SERVICE_NAME = "raspotify.service"
# RASPOTIFY_CONFIG_FILE = "/etc/raspotify/conf" # Genellikle /etc altında olur
# Kullanıcı ev dizinindeki yolu kullanmak genellikle sudo tee ile daha kolay olabilir:
RASPOTIFY_CONFIG_FILE = os.path.expanduser("~/.config/raspotify/conf") # VEYA /etc/raspotify/conf
# Eğer dosya yoksa oluşturulacak, varsa üzerine yazılacak.
# ÖNEMLİ: Bu dosyanın Flask uygulamasını çalıştıran kullanıcı tarafından
# sudo tee ile yazılabildiğinden emin olun (veya dosya izinlerini ayarlayın).

# DAC'ınızı aplay -L çıktısında tanımlayan bir anahtar kelime.
DAC_IDENTIFIER = "PCM5102" # veya "DAC", "USB Audio", "snd_rpi_hifiberry_dac" vb.

# Spotify API Bilgileri - KENDİ BİLGİLERİNİZLE DEĞİŞTİRİN!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78' # ÖRNEK - DEĞİŞTİR
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426' # ÖRNEK - DEĞİŞTİR
# Cihazınızın AĞ üzerindeki IP adresini ve Flask portunu yazın (Örn: http://192.168.1.100:8080/callback)
SPOTIFY_REDIRECT_URI = 'http://192.168.1.103:8080/callback' # ÖRNEK - DEĞİŞTİR
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

# Diğer Dosya Yolları
TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
# ---------------------------------

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class AudioManager:
    """ALSA ve Raspotify ile ses cihazlarını yöneten sınıf."""

    @staticmethod
    def _ensure_config_dir_exists():
        """Raspotify yapılandırma dosyasının dizininin var olduğundan emin olur."""
        config_dir = os.path.dirname(RASPOTIFY_CONFIG_FILE)
        if not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir, exist_ok=True)
                logger.info(f"Raspotify yapılandırma dizini oluşturuldu: {config_dir}")
            except Exception as e:
                logger.error(f"Raspotify yapılandırma dizini oluşturulamadı ({config_dir}): {e}")
                return False
        return True

    @staticmethod
    def get_output_devices():
        """Mevcut ALSA ses çıkış cihazlarını (DAC ve bluealsa) getirir."""
        devices = []
        try:
            result = subprocess.run(['aplay', '-L'], capture_output=True, text=True, check=True, timeout=10)
            alsa_device_name = None
            description = None
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and not line[0].isspace() and line != 'null' and not line.startswith('-') and line != 'default':
                    if alsa_device_name and description:
                        device_type = 'other'
                        if DAC_IDENTIFIER and DAC_IDENTIFIER.lower() in description.lower(): device_type = 'dac'
                        elif 'bluealsa' in alsa_device_name.lower(): device_type = 'bluetooth'
                        devices.append({'name': alsa_device_name, 'description': description.split(',')[0].strip(), 'type': device_type})
                    alsa_device_name = line
                    description = None
                elif alsa_device_name and line and line[0].isspace():
                    if description is None: description = line.strip()
            if alsa_device_name and description and alsa_device_name != 'null' and alsa_device_name != 'default':
                device_type = 'other'
                if DAC_IDENTIFIER and DAC_IDENTIFIER.lower() in description.lower(): device_type = 'dac'
                elif 'bluealsa' in alsa_device_name.lower(): device_type = 'bluetooth'
                devices.append({'name': alsa_device_name, 'description': description.split(',')[0].strip(), 'type': device_type})

            for device in devices:
                 if device['type'] == 'bluetooth':
                    try:
                        match = re.search(r'DEV=([0-9A-Fa-f:]+)', device['name'])
                        mac = match.group(1) if match else None
                        friendly_name = f"BT Cihazı ({mac})" if mac else "Bluetooth Cihazı"
                        if mac:
                             try:
                                 info_result = subprocess.run(['bluetoothctl', 'info', mac], capture_output=True, text=True, timeout=5)
                                 if info_result.returncode == 0:
                                     name_match = re.search(r'Name:\s*(.*)', info_result.stdout)
                                     alias_match = re.search(r'Alias:\s*(.*)', info_result.stdout)
                                     bt_name = alias_match.group(1).strip() if alias_match else (name_match.group(1).strip() if name_match else None)
                                     if bt_name: friendly_name = f"BT: {bt_name}"
                             except Exception as bt_err: logger.warning(f"Bluetooth cihaz adı alınamadı ({mac}): {bt_err}")
                        device['description'] = friendly_name
                    except Exception as e:
                        logging.warning(f"Bluealsa cihaz adı ayrıştırılırken hata: {e}")
                        device['description'] = device.get('description', "Bluetooth Cihazı")

            current_target_device = AudioManager.get_current_librespot_device()
            for device in devices: device['is_default'] = (device['name'] == current_target_device)
            logger.info(f"Bulunan ALSA cihazları: {len(devices)} adet")
            return devices
        except FileNotFoundError: logging.error("ALSA komutu 'aplay' bulunamadı. ALSA utils kurulu mu?"); return []
        except subprocess.CalledProcessError as e: logging.error(f"ALSA cihazları listelenirken hata ('aplay -L'): {e.stderr}"); return []
        except subprocess.TimeoutExpired: logging.error("ALSA cihazları listelenirken zaman aşımı ('aplay -L')."); return []
        except Exception as e: logging.error(f"Ses çıkış cihazları listelenirken genel hata: {e}", exc_info=True); return []

    @staticmethod
    def get_current_librespot_device():
        """Raspotify yapılandırma dosyasından mevcut LIBRESPOT_DEVICE değerini okur."""
        if not os.path.exists(os.path.dirname(RASPOTIFY_CONFIG_FILE)):
             logger.warning(f"Raspotify yapılandırma dizini mevcut değil: {os.path.dirname(RASPOTIFY_CONFIG_FILE)}"); return None
        if not os.path.exists(RASPOTIFY_CONFIG_FILE):
            logger.warning(f"Raspotify yapılandırma dosyası bulunamadı: {RASPOTIFY_CONFIG_FILE}"); return None
        try:
            with open(RASPOTIFY_CONFIG_FILE, 'r') as f:
                for line in f:
                    if line.strip().startswith('LIBRESPOT_DEVICE=') and not line.strip().startswith('#'):
                        value = line.split('=', 1)[1].strip()
                        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")): value = value[1:-1]
                        logger.debug(f"Mevcut Raspotify cihazı bulundu: {value}"); return value
            logger.info(f"Aktif (yorumlanmamış) LIBRESPOT_DEVICE satırı bulunamadı: {RASPOTIFY_CONFIG_FILE}"); return None
        except Exception as e: logger.error(f"Raspotify yapılandırması ({RASPOTIFY_CONFIG_FILE}) okunurken hata: {e}", exc_info=True); return None

    @staticmethod
    def set_librespot_device(device_name):
        """Raspotify yapılandırma dosyasını günceller ve servisi yeniden başlatır."""
        if not AudioManager._ensure_config_dir_exists(): return False, f"Yapılandırma dizini oluşturulamadı/erişilemedi: {os.path.dirname(RASPOTIFY_CONFIG_FILE)}"
        try:
            logging.info(f"Raspotify çıkış cihazı {device_name} olarak ayarlanıyor...")
            lines = []
            if os.path.exists(RASPOTIFY_CONFIG_FILE):
                try:
                    with open(RASPOTIFY_CONFIG_FILE, 'r') as f: lines = f.readlines()
                except Exception as read_err: logger.error(f"Mevcut Raspotify yapılandırma dosyası okunamadı ({RASPOTIFY_CONFIG_FILE}): {read_err}"); return False, f"Mevcut yapılandırma dosyası okunamadı: {read_err}"
            else: logger.info(f"Raspotify yapılandırma dosyası mevcut değil, yeni oluşturulacak: {RASPOTIFY_CONFIG_FILE}")

            new_lines = []; found_and_updated = False; config_line = f'LIBRESPOT_DEVICE="{device_name}"\n'
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith('LIBRESPOT_DEVICE=') or stripped_line.startswith('#LIBRESPOT_DEVICE='):
                    if not found_and_updated:
                        current_val_match = re.match(r'^#?LIBRESPOT_DEVICE=(["\']?)(.*)\1$', stripped_line)
                        if current_val_match and current_val_match.group(2) == device_name and not stripped_line.startswith('#'):
                            new_lines.append(line); logger.info(f"LIBRESPOT_DEVICE zaten '{device_name}' olarak ayarlı.")
                        else: new_lines.append(config_line); logger.info(f"'{line.strip()}' satırı şununla değiştirildi/aktifleştirildi: '{config_line.strip()}'")
                        found_and_updated = True
                    else:
                         if not stripped_line.startswith('#'): new_lines.append(f"# {line.strip()}\n"); logging.warning(f"Ekstra LIBRESPOT_DEVICE satırı yorumlandı: {line.strip()}")
                         else: new_lines.append(line)
                else: new_lines.append(line)
            if not found_and_updated:
                logger.info(f"LIBRESPOT_DEVICE satırı dosyada bulunamadı, sona ekleniyor.")
                if lines and not lines[-1].strip() == "": new_lines.append("\n")
                new_lines.append("# Sound Device Selection (managed by web interface)\n"); new_lines.append(config_line)

            temp_config_content = "".join(new_lines); tee_cmd = ['sudo', 'tee', RASPOTIFY_CONFIG_FILE]
            logger.info(f"Komut çalıştırılıyor: echo '...' | {' '.join(tee_cmd)}")
            try:
                process = subprocess.Popen(tee_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=temp_config_content, timeout=10)
                if process.returncode != 0:
                     if 'permission denied' in stderr.lower(): logger.error(f"Raspotify yapılandırma dosyası yazılamadı ({RASPOTIFY_CONFIG_FILE}): İzin hatası..."); return False, f"Yapılandırma dosyası yazılamadı: İzin Hatası..."
                     else: logger.error(f"Raspotify yapılandırma dosyası yazılamadı ({RASPOTIFY_CONFIG_FILE}): {stderr}"); return False, f"Yapılandırma dosyası güncellenemedi: {stderr}"
            except subprocess.TimeoutExpired: logger.error(f"Raspotify yapılandırma dosyası yazılırken zaman aşımı (sudo tee)."); return False, "Yapılandırma dosyası yazılırken zaman aşımı."
            except FileNotFoundError: logger.error(f"Komut bulunamadı: 'sudo'."); return False, "'sudo' komutu bulunamadı."

            logging.info(f"Yapılandırma dosyası başarıyla güncellendi: {RASPOTIFY_CONFIG_FILE}")
            restart_cmd = ['sudo', 'systemctl', 'restart', RASPOTIFY_SERVICE_NAME]
            logging.info(f"Komut çalıştırılıyor: {' '.join(restart_cmd)}")
            try:
                result = subprocess.run(restart_cmd, capture_output=True, text=True, check=True, timeout=20)
                logging.info(f"Raspotify servisi başarıyla yeniden başlatıldı."); time.sleep(3); return True, f"Raspotify çıkış cihazı {device_name} olarak ayarlandı ve servis yeniden başlatıldı."
            except FileNotFoundError: logger.error(f"Komut bulunamadı: 'systemctl'."); return False, "'systemctl' komutu bulunamadı."
            except subprocess.CalledProcessError as e:
                logger.error(f"Raspotify servisi yeniden başlatılamadı ({RASPOTIFY_SERVICE_NAME}): {e.stderr}")
                if 'not found' in e.stderr.lower(): return False, f"Raspotify servisi bulunamadı: {RASPOTIFY_SERVICE_NAME}."
                elif 'masked' in e.stderr.lower(): return False, f"Raspotify servisi maskelenmiş: {RASPOTIFY_SERVICE_NAME}..."
                else: return False, f"Raspotify servisi yeniden başlatılamadı: {e.stderr}"
            except subprocess.TimeoutExpired: logger.error(f"Raspotify servisi yeniden başlatılırken zaman aşımı."); return False, "Raspotify servisi yeniden başlatılırken zaman aşımı."
        except Exception as e: logger.error(f"Raspotify cihazı ayarlanırken hata: {str(e)}", exc_info=True); return False, f"Beklenmedik hata: {str(e)}"

    @staticmethod
    def scan_bluetooth_devices():
        """Kullanılabilir (bilinen) bluetooth cihazlarını listeler."""
        try:
            result = subprocess.run(['bluetoothctl', 'devices'], capture_output=True, text=True, check=True, timeout=10)
            devices = []
            for line in result.stdout.splitlines():
                if line.startswith("Device"):
                    parts = line.strip().split(' ', 2)
                    if len(parts) >= 3:
                        is_connected = False
                        try:
                             info_result = subprocess.run(['bluetoothctl', 'info', parts[1]], capture_output=True, text=True, timeout=5)
                             if info_result.returncode == 0 and 'Connected: yes' in info_result.stdout: is_connected = True
                        except Exception: pass
                        devices.append({'mac_address': parts[1], 'name': parts[2], 'type': 'bluetooth', 'connected': is_connected})
            logger.info(f"Bluetooth cihazları listelendi: {len(devices)} adet"); return devices
        except FileNotFoundError: logger.error("Komut bulunamadı: 'bluetoothctl'. Bluez yüklü mü?"); return []
        except subprocess.CalledProcessError as e: logger.error(f"Bluetooth cihazları listelenirken hata: {e.stderr}"); return []
        except subprocess.TimeoutExpired: logger.error(f"Bluetooth cihazları listelenirken zaman aşımı."); return []
        except Exception as e: logger.error(f"Bluetooth cihazları listelenirken genel hata: {e}", exc_info=True); return []

    @staticmethod
    def pair_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazını eşleştirir ve bağlar."""
        try:
            logging.info(f"Bluetooth cihazı {mac_address} eşleştiriliyor/bağlanıyor...")
            try: subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=5)
            except Exception: pass
            trust_cmd = subprocess.run(['bluetoothctl', 'trust', mac_address], capture_output=True, text=True, timeout=10)
            if trust_cmd.returncode != 0: logging.warning(f"Cihaz güvenilir yapılamadı (zaten olabilir veya hata): {trust_cmd.stderr}")
            connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
            if connect_cmd.returncode == 0 and 'Connection successful' in connect_cmd.stdout.lower():
                logging.info(f"Bluetooth cihazı başarıyla bağlandı: {mac_address}"); time.sleep(3); return True
            else:
                logging.warning(f"İlk bağlantı denemesi başarısız ({mac_address}), tekrar deneniyor... Hata: {connect_cmd.stderr}"); time.sleep(3)
                connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
                if connect_cmd.returncode == 0 and 'Connection successful' in connect_cmd.stdout.lower():
                     logging.info(f"Bluetooth cihazı ikinci denemede başarıyla bağlandı: {mac_address}"); time.sleep(3); return True
                else:
                     logging.error(f"Bluetooth cihazı bağlantı hatası ({mac_address}): {connect_cmd.stderr}")
                     subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=10); return False
        except FileNotFoundError: logger.error("Komut bulunamadı: 'bluetoothctl'. Bluez yüklü mü?"); return False
        except subprocess.TimeoutExpired: logger.error(f"Bluetooth işlemi ({mac_address}) sırasında zaman aşımı."); return False
        except Exception as e: logger.error(f"Bluetooth cihazı eşleştirme/bağlama sırasında hata ({mac_address}): {e}", exc_info=True); return False

    @staticmethod
    def disconnect_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazının bağlantısını keser."""
        try:
            logging.info(f"Bluetooth cihazı {mac_address} bağlantısı kesiliyor...")
            cmd = subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, check=True, timeout=10)
            logging.info(f"Bluetooth cihazı bağlantısı başarıyla kesildi: {mac_address}"); time.sleep(2); return True
        except FileNotFoundError: logger.error("Komut bulunamadı: 'bluetoothctl'. Bluez yüklü mü?"); return False
        except subprocess.CalledProcessError as e:
             logger.error(f"Bluetooth bağlantısını kesme hatası ({mac_address}): {e.stderr}")
             if 'not connected' in e.stderr.lower(): logging.info(f"Cihaz ({mac_address}) zaten bağlı değil."); return True
             return False
        except subprocess.TimeoutExpired: logger.error(f"Bluetooth bağlantısını kesme ({mac_address}) sırasında zaman aşımı."); return False
        except Exception as e: logger.error(f"Bluetooth cihazı bağlantısını kesme sırasında hata ({mac_address}): {e}", exc_info=True); return False

# --- Flask Uygulaması ---
app = Flask(__name__)
# Güvenli bir anahtar kullanın, ortam değişkeninden almak en iyisidir
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
app.jinja_env.globals['AudioManager'] = AudioManager

# --- Global Değişkenler ---
spotify_client = None               # Aktif Spotify istemcisi
song_queue = []                     # Şarkı kuyruğu listesi
user_requests = {}                  # Kullanıcı IP'lerine göre istek sayıları
# Zaman profilleri {id, artist_id, name, artist_name} tutar
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] }
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
auto_advance_enabled = True         # Otomatik sıraya geçiş kontrolü (varsayılan: aktif)

# --- Yardımcı Fonksiyonlar (Ayarlar, Token, Auth) ---

def load_settings():
    """Ayarları JSON dosyasından yükler veya varsayılanları oluşturur."""
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5,
        'active_device_id': None,
        'active_genres': ALLOWED_GENRES[:5]
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                default_settings.update(loaded) # Varsayılanları koruyarak güncelle
            logger.info(f"Ayarlar yüklendi: {SETTINGS_FILE}")
        except Exception as e:
             logger.error(f"Ayar dosyası ({SETTINGS_FILE}) okunamadı/bozuk, varsayılanlar kullanılıyor: {e}")
    else:
        logger.info(f"Ayar dosyası bulunamadı, varsayılanlar oluşturuluyor: {SETTINGS_FILE}")
        save_settings(default_settings) # İlk çalıştırmada varsayılanları kaydet
    return default_settings

def save_settings(current_settings):
    """Ayarları JSON dosyasına kaydeder."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(current_settings, f, indent=4)
        logger.info(f"Ayarlar kaydedildi: {SETTINGS_FILE}")
    except Exception as e:
        logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)

# Ayarları global olarak yükle (uygulama başlangıcında)
settings = load_settings()

def load_token():
    """Spotify token'ını dosyadan yükler."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f: return json.load(f)
        except Exception as e: logger.error(f"Token dosyası okuma hatası ({TOKEN_FILE}): {e}")
    return None

def save_token(token_info):
    """Spotify token'ını dosyaya kaydeder."""
    try:
        with open(TOKEN_FILE, 'w') as f: json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi.")
    except Exception as e: logger.error(f"Token kaydetme hatası: {e}")

def get_spotify_auth():
    """SpotifyOAuth nesnesini oluşturur."""
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_'):
         raise ValueError("Spotify Client ID ve Secret app.py içinde ayarlanmamış!")
    return SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET,
                        redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPE,
                        open_browser=False, cache_path=None)

def get_spotify_client():
    """Geçerli bir Spotify istemci nesnesi döndürür, gerekirse token yeniler."""
    global spotify_client
    token_info = load_token()
    if not token_info: return None
    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(e); return None
    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token süresi dolmuş, yenileniyor...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val:
                logger.error("Refresh token bulunamadı. Yeniden yetkilendirme gerekli.")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE); spotify_client = None
                return None
            new_token_info = auth_manager.refresh_access_token(refresh_token_val)
            if not new_token_info:
                logger.error("Token yenilenemedi. Refresh token geçersiz olabilir.")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE); spotify_client = None
                return None
            token_info = new_token_info
            save_token(token_info)
        # Yeni bir istemci oluştur veya mevcut olanı doğrula
        # Eğer global client varsa ve token hala geçerliyse onu kullanmayı deneyebiliriz,
        # ama her seferinde yenisini oluşturmak daha basit olabilir.
        new_spotify_client = spotipy.Spotify(auth=token_info.get('access_token'))
        try:
            new_spotify_client.current_user() # İstemciyi test et
            spotify_client = new_spotify_client # Global istemciyi güncelle
            return spotify_client
        except Exception as e:
            logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası: {e}")
            if "invalid access token" in str(e).lower() or "token expired" in str(e).lower() or "unauthorized" in str(e).lower():
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            spotify_client = None; return None
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API hatası (token işlemi sırasında): {e}")
        if e.http_status == 401 or e.http_status == 403:
             if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None; return None
    except Exception as e:
        logger.error(f"Spotify token işlemi sırasında genel hata: {e}", exc_info=True)
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None; return None

# --- Admin Giriş Decorator'ı ---
def admin_login_required(f):
    """Admin girişi gerektiren rotalar için decorator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            flash("Bu sayfaya erişmek için yönetici girişi yapmalısınız.", "warning")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Zaman Profili ve Öneri Fonksiyonları ---
def get_current_time_profile():
    """Mevcut saate göre zaman dilimi adını döndürür."""
    hour = time.localtime().tm_hour
    if 6 <= hour < 12: return 'sabah'
    elif 12 <= hour < 18: return 'oglen'
    elif 18 <= hour < 24: return 'aksam'
    else: return 'gece'

def update_time_profile(track_id, spotify):
    """Eklenen şarkının temel bilgilerini alır ve ilgili zaman profiline kaydeder."""
    if not spotify or not track_id: logger.warning("update_time_profile: spotify istemcisi veya track_id eksik."); return
    profile_name = get_current_time_profile()
    logger.debug(f"'{profile_name}' profili güncelleniyor, track_id: {track_id}")
    try:
        track_info = spotify.track(track_id, market='TR')
        if not track_info: logger.warning(f"Şarkı detayı alınamadı: {track_id}"); return
        track_name = track_info.get('name', 'Bilinmeyen Şarkı')
        artists = track_info.get('artists')
        primary_artist_id = artists[0].get('id') if artists and artists[0].get('id') else None
        primary_artist_name = artists[0].get('name') if artists and artists[0].get('name') else 'Bilinmeyen Sanatçı'
        profile_entry = {'id': track_id, 'artist_id': primary_artist_id, 'name': track_name, 'artist_name': primary_artist_name}
        time_profiles[profile_name].append(profile_entry)
        if len(time_profiles[profile_name]) > 5: time_profiles[profile_name] = time_profiles[profile_name][-5:] # Son 5 bilgiyi tut
        logger.info(f"'{profile_name}' profiline şarkı bilgisi eklendi: '{track_name}' (Artist ID: {primary_artist_id})")
    except spotipy.SpotifyException as e: logger.warning(f"'{profile_name}' profiline eklenirken şarkı bilgisi alınamadı (ID: {track_id}): {e}")
    except Exception as e: logger.error(f"'{profile_name}' profiline eklenirken genel hata (ID: {track_id}): {e}", exc_info=True)

def suggest_song_for_time(spotify):
    """Mevcut zaman profiline göre Spotify'dan şarkı önerisi ister."""
    if not spotify: logger.warning("suggest_song_for_time: spotify istemcisi eksik."); return None
    profile_name = get_current_time_profile()
    profile_data = time_profiles.get(profile_name, [])
    if not profile_data: return None # Profil boşsa öneri yok
    seed_tracks = []; seed_artists = []
    last_entry = profile_data[-1] # Son eklenen şarkı/sanatçıdan tohum al
    if last_entry.get('id'): seed_tracks.append(last_entry['id'])
    if last_entry.get('artist_id'): seed_artists.append(last_entry['artist_id'])
    if not seed_tracks and not seed_artists: logger.warning(f"'{profile_name}' profili öneri için geçerli tohum içermiyor: {last_entry}"); return None
    try:
        logger.info(f"'{profile_name}' için öneri isteniyor: seed_tracks={seed_tracks}, seed_artists={seed_artists}")
        recs = spotify.recommendations(seed_tracks=seed_tracks, seed_artists=seed_artists, limit=5, market='TR')
        if recs and recs.get('tracks'):
            for suggested_track in recs['tracks']:
                 is_in_queue = any(song.get('id') == suggested_track['id'] for song in song_queue)
                 if not is_in_queue:
                    track_name = suggested_track.get('name', 'Bilinmeyen Öneri'); track_id = suggested_track.get('id')
                    logger.info(f"'{profile_name}' için öneri bulundu: '{track_name}' ({track_id})")
                    artists = suggested_track.get('artists', [])
                    suggested_track['artist'] = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'
                    return suggested_track # Kuyrukta olmayan ilk öneriyi döndür
            logger.info(f"'{profile_name}' için öneriler alındı ama hepsi zaten kuyrukta.")
            return None
        else: logger.info(f"'{profile_name}' için Spotify'dan tohumlara dayalı öneri alınamadı."); return None
    except spotipy.SpotifyException as e:
         logger.warning(f"'{profile_name}' için öneri alınırken Spotify API hatası: {e}")
         if e.http_status == 401 or e.http_status == 403:
              global spotify_client; spotify_client = None
              if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
         return None
    except Exception as e: logger.error(f"'{profile_name}' için öneri alınırken genel hata: {e}", exc_info=True); return None

# --- Flask Rotaları ---

@app.route('/')
def index():
    """Ana sayfayı gösterir."""
    return render_template('index.html', allowed_genres=settings.get('active_genres', ALLOWED_GENRES))

@app.route('/admin')
def admin():
    """Admin giriş sayfasını veya paneli gösterir."""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    """Admin giriş isteğini işler."""
    # Şifreyi ortam değişkeninden almak daha güvenlidir
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123")
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        logger.info("Admin girişi başarılı")
        flash("Yönetim paneline hoş geldiniz!", "success")
        return redirect(url_for('admin_panel'))
    else:
        logger.warning("Başarısız admin girişi denemesi")
        flash("Yanlış şifre girdiniz.", "danger")
        return redirect(url_for('admin'))

@app.route('/logout')
@admin_login_required # Çıkış için de login gerekli olsun
def logout():
    """Admin çıkış işlemini yapar."""
    global spotify_client
    spotify_client = None # Oturum kapanınca istemciyi sıfırla
    session.clear()
    logger.info("Admin çıkışı yapıldı.")
    flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    """Yönetim panelini gösterir."""
    global auto_advance_enabled # Global değişkene erişim için
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None # Başlangıçta None

    output_devices = AudioManager.get_output_devices()
    current_active_alsa_device = AudioManager.get_current_librespot_device()

    if spotify:
        try:
            # Cihazları al
            result = spotify.devices()
            spotify_devices = result.get('devices', [])
            spotify_authenticated = True
            session['spotify_authenticated'] = True

            # Kullanıcı bilgisini al
            try:
                 user = spotify.current_user()
                 spotify_user = user.get('display_name', 'Bilinmeyen Kullanıcı')
                 session['spotify_user'] = spotify_user
            except Exception as user_err:
                logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}")
                session.pop('spotify_user', None)

            # Şu an çalan şarkıyı ve durumunu al
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('item'): # item varsa bilgi vardır (çalıyor veya duraklatılmış)
                    item = playback['item']
                    is_playing = playback.get('is_playing', False) # is_playing durumunu al
                    track_name = item.get('name', 'Bilinmeyen Şarkı')
                    artists = item.get('artists', [])
                    artist_name = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'
                    images = item.get('album', {}).get('images', [])
                    image_url = images[0].get('url') if images else None # En büyük resmi al

                    currently_playing_info = {
                        'id': item.get('id'), # ID'yi de alalım belki lazım olur
                        'name': track_name,
                        'artist': artist_name,
                        'image_url': image_url,
                        'is_playing': is_playing # Durumu dictionary'e ekle
                    }
                    logger.debug(f"Şu An Çalıyor (Admin Panel): {track_name} - Durum: {'Çalıyor' if is_playing else 'Duraklatıldı'}")
            except spotipy.SpotifyException as pb_err:
                 logger.warning(f"Admin paneli için çalma durumu alınamadı: {pb_err}")
                 if pb_err.http_status == 401 or pb_err.http_status == 403:
                     global spotify_client; spotify_client = None
                     if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                     spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            except Exception as pb_err_general:
                logger.error(f"Admin paneli için çalma durumu alınırken genel hata: {pb_err_general}", exc_info=True)

        except Exception as e: # Spotify cihazları veya kullanıcı alınırken genel hata
            logger.error(f"Spotify API hatası (Admin Panel Genel): {e}")
            spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)
            if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            #global spotify_client; spotify_client = None
    else: # spotify istemcisi alınamadıysa
         spotify_authenticated = False; session['spotify_authenticated'] = False; session.pop('spotify_user', None)

    # Template'e tüm gerekli bilgileri gönder
    return render_template(
        'admin_panel.html',
        settings=settings,
        devices=spotify_devices,
        queue=song_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_device_id=settings.get('active_device_id'),
        output_devices=output_devices,
        current_active_alsa_device=current_active_alsa_device,
        currently_playing_info=currently_playing_info, # Çalma bilgisini (is_playing dahil) gönder
        auto_advance_enabled=auto_advance_enabled # Otomatik ilerleme durumu
    )

# --- YENİ Entegre Çalma Kontrol Rotaları ---

@app.route('/player/pause')
@admin_login_required
def player_pause():
    """Admin panelinden çalmayı duraklatır ve otomatik ilerlemeyi kapatır."""
    global auto_advance_enabled
    spotify = get_spotify_client()
    active_device_id = settings.get('active_device_id') # Ayarlardan aktif cihazı al

    if not spotify:
        flash('Spotify bağlantısı yok!', 'danger')
        return redirect(url_for('admin_panel'))

    # Aktif cihaz ID'si olmadan duraklatma genellikle çalışır ama belirtmek daha iyi
    # if not active_device_id:
    #     flash('Aktif Spotify Connect cihazı seçilmemiş!', 'warning')
    #     return redirect(url_for('admin_panel'))

    try:
        logger.info(f"Admin: Çalmayı duraklatma isteği (Cihaz: {active_device_id or 'Belirtilmedi'}).")
        spotify.pause_playback(device_id=active_device_id) # ID belirtmek daha kesin sonuç verir
        auto_advance_enabled = False # Otomatik ilerlemeyi kapat
        logger.info("Admin: Otomatik sıraya geçiş DURAKLATILDI.")
        flash('Müzik duraklatıldı ve otomatik sıraya geçiş kapatıldı.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify duraklatma hatası: {e}")
        # Hata mesajlarını kullanıcıya göster
        if e.http_status == 401 or e.http_status == 403:
            flash('Spotify yetkilendirme hatası. Lütfen tekrar yetkilendirin.', 'danger')
            global spotify_client; spotify_client = None
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404: # Cihaz bulunamadı veya başka 404
             flash(f'Duraklatma hatası: Cihaz bulunamadı veya geçersiz istek ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE':
             flash('Aktif bir Spotify cihazı bulunamadı!', 'warning')
        else:
            flash(f'Spotify duraklatma hatası: {e.msg}', 'danger')
    except Exception as e:
        logger.error(f"Duraklatma sırasında genel hata: {e}", exc_info=True)
        flash('Müzik duraklatılırken bir hata oluştu.', 'danger')

    return redirect(url_for('admin_panel'))


@app.route('/player/resume')
@admin_login_required
def player_resume():
    """Admin panelinden çalmayı sürdürür ve otomatik ilerlemeyi açar."""
    global auto_advance_enabled
    spotify = get_spotify_client()
    active_device_id = settings.get('active_device_id') # Ayarlardan aktif cihazı al

    if not spotify:
        flash('Spotify bağlantısı yok!', 'danger')
        return redirect(url_for('admin_panel'))

    # Aktif cihaz ID'si olmadan sürdürme genellikle çalışır ama belirtmek daha iyi
    # if not active_device_id:
    #     flash('Aktif Spotify Connect cihazı seçilmemiş!', 'warning')
    #     return redirect(url_for('admin_panel'))

    try:
        logger.info(f"Admin: Çalmayı sürdürme isteği (Cihaz: {active_device_id or 'Belirtilmedi'}).")
        # start_playback URI olmadan çağrıldığında çalmayı sürdürür
        spotify.start_playback(device_id=active_device_id) # ID belirtmek daha kesin sonuç verir
        auto_advance_enabled = True # Otomatik ilerlemeyi aç
        logger.info("Admin: Otomatik sıraya geçiş SÜRDÜRÜLDÜ.")
        flash('Müzik sürdürüldü ve otomatik sıraya geçiş açıldı.', 'success')
    except spotipy.SpotifyException as e:
        logger.error(f"Spotify sürdürme/başlatma hatası: {e}")
        # Hata mesajlarını kullanıcıya göster
        if e.http_status == 401 or e.http_status == 403:
            flash('Spotify yetkilendirme hatası. Lütfen tekrar yetkilendirin.', 'danger')
            global spotify_client; spotify_client = None
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        elif e.http_status == 404: # Cihaz bulunamadı veya başka 404
             flash(f'Sürdürme hatası: Cihaz bulunamadı veya geçersiz istek ({e.msg})', 'warning')
        elif e.reason == 'NO_ACTIVE_DEVICE':
             flash('Aktif bir Spotify cihazı bulunamadı!', 'warning')
        elif e.reason == 'PREMIUM_REQUIRED':
             flash('Bu işlem için Spotify Premium hesabı gerekli.', 'warning')
        else:
            flash(f'Spotify sürdürme hatası: {e.msg}', 'danger')
    except Exception as e:
        logger.error(f"Sürdürme sırasında genel hata: {e}", exc_info=True)
        flash('Müzik sürdürülürken bir hata oluştu.', 'danger')

    return redirect(url_for('admin_panel'))

# --- Diğer Rotalar ---

@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    """Spotify Connect cihaz listesini yeniler."""
    spotify = get_spotify_client()
    if not spotify: flash('Spotify bağlantısı yok!', 'danger'); return redirect(url_for('admin_panel'))
    try:
        result = spotify.devices()
        devices = result.get('devices', [])
        logger.info(f"Spotify Connect Cihazları yenilendi: {len(devices)} cihaz bulundu")
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device:
            if not any(d['id'] == active_spotify_connect_device for d in devices):
                logger.warning(f"Aktif cihaz ({active_spotify_connect_device}) listede yok. Ayar temizleniyor.")
                settings['active_device_id'] = None; save_settings(settings)
                flash('Ayarlarda kayıtlı aktif cihaz artık mevcut değil.', 'warning')
        flash('Spotify cihaz listesi yenilendi.', 'info')
    except Exception as e:
        logger.error(f"Spotify Connect Cihazlarını yenilerken hata: {e}")
        flash('Cihaz listesi yenilenirken bir hata oluştu.', 'danger')
        if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
             global spotify_client; spotify_client = None
             if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    """Admin panelinden gelen ayarları günceller."""
    global settings
    try:
        settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        # Aktif Spotify Connect Cihazını Güncelle (Formda varsa)
        if 'active_device_id' in request.form:
             new_spotify_device_id = request.form.get('active_device_id')
             settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {settings['active_device_id']}")
        settings['active_genres'] = [genre for genre in ALLOWED_GENRES if request.form.get(f'genre_{genre}')]
        save_settings(settings)
        logger.info(f"Ayarlar güncellendi: {settings}")
        flash("Ayarlar başarıyla güncellendi.", "success")
    except ValueError:
         logger.error("Ayarları güncellerken geçersiz sayısal değer alındı.")
         flash("Ayarlar güncellenirken geçersiz sayısal değer girildi!", "danger")
    except Exception as e:
         logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True)
         flash("Ayarlar güncellenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    """Kullanıcıyı Spotify yetkilendirme sayfasına yönlendirir."""
    if os.path.exists(TOKEN_FILE): logger.warning("Mevcut token varken yeniden yetkilendirme başlatılıyor.")
    try:
        auth_manager = get_spotify_auth(); auth_url = auth_manager.get_authorize_url()
        logger.info("Spotify yetkilendirme URL'sine yönlendiriliyor."); return redirect(auth_url)
    except ValueError as e: logger.error(f"Spotify yetkilendirme hatası: {e}"); flash(f"Spotify Yetkilendirme Hatası: {e}", "danger"); return redirect(url_for('admin_panel'))
    except Exception as e: logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True); flash("Spotify yetkilendirme başlatılamadı.", "danger"); return redirect(url_for('admin_panel'))

@app.route('/callback')
def callback():
    """Spotify tarafından yetkilendirme sonrası geri çağrılan endpoint."""
    try: auth_manager = get_spotify_auth()
    except ValueError as e: logger.error(f"Callback hatası: {e}"); return f"Callback Hatası: {e}", 500
    if 'error' in request.args: error = request.args.get('error'); logger.error(f"Spotify yetkilendirme hatası (callback): {error}"); return f"Spotify Yetkilendirme Hatası: {error}", 400
    if 'code' not in request.args: logger.error("Callback'te 'code' parametresi bulunamadı."); return "Geçersiz callback isteği.", 400
    code = request.args.get('code')
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        if not token_info: logger.error("Spotify'dan geçerli token alınamadı."); return "Token alınamadı.", 500
        save_token(token_info)
        global spotify_client; spotify_client = None # İstemciyi yenilemeye zorla
        logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
        if session.get('admin_logged_in'):
            flash("Spotify yetkilendirmesi başarıyla tamamlandı!", "success")
            return redirect(url_for('admin_panel'))
        else: return redirect(url_for('index')) # Admin değilse ana sayfaya
    except Exception as e: logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True); return "Token işlenirken bir hata oluştu.", 500

@app.route('/search', methods=['POST'])
def search():
    """Kullanıcı arayüzünden gelen şarkı arama isteklerini işler."""
    search_query = request.form.get('search_query')
    logger.info(f"Arama isteği: Sorgu='{search_query}'")
    if not search_query: return jsonify({'error': 'Lütfen bir arama terimi girin.'}), 400
    spotify = get_spotify_client()
    if not spotify: logger.error("Arama yapılamadı: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı şu anda mevcut değil.'}), 503
    try:
        results = spotify.search(q=search_query, type='track', limit=10, market='TR')
        tracks = results.get('tracks', {}).get('items', [])
        logger.info(f"Arama sonucu: {len(tracks)} şarkı bulundu.")
        search_results = []
        for track in tracks:
            track_id = track.get('id'); track_name = track.get('name')
            artists = track.get('artists', []); artist_name = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'
            album = track.get('album', {}); album_name = album.get('name')
            images = album.get('images', []); image_url = images[-1].get('url') if images else None
            if track_id and track_name: search_results.append({'id': track_id, 'name': track_name, 'artist': artist_name, 'album': album_name, 'image': image_url})
        return jsonify({'results': search_results})
    except Exception as e: logger.error(f"Spotify araması sırasında hata: {e}", exc_info=True); return jsonify({'error': 'Arama sırasında bir sorun oluştu.'}), 500

@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
    """Admin panelinden ID veya URL ile şarkıyı kuyruğa ekler."""
    song_input = request.form.get('song_id', '').strip()
    if not song_input: flash("Lütfen bir şarkı ID'si veya URL'si girin.", "warning"); return redirect(url_for('admin_panel'))
    song_id = song_input
    # URL'den ID çıkarma (daha sağlam bir regex ile yapılabilir)
    if 'https://developer.spotify.com/documentation/web-api/reference/add-to-queue2' in song_input:
        match = re.search(r'/track/([a-zA-Z0-9]+)', song_input)
        if match: song_id = match.group(1)
        else: logger.warning(f"Geçersiz Spotify URL formatı: {song_input}"); flash("Geçersiz Spotify URL formatı.", "danger"); return redirect(url_for('admin_panel'))
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning(f"Kuyruk dolu, admin şarkı ekleyemedi: {song_id}"); flash("Şarkı kuyruğu dolu!", "warning"); return redirect(url_for('admin_panel'))
    spotify = get_spotify_client()
    if not spotify: logger.warning("Admin şarkı ekleme: Spotify yetkilendirmesi gerekli"); flash("Şarkı eklemek için Spotify yetkilendirmesi gerekli.", "warning"); return redirect(url_for('spotify_auth'))
    try:
        song_info = spotify.track(song_id, market='TR')
        if not song_info: logger.warning(f"Admin şarkı ekleme: Şarkı bulunamadı ID={song_id}"); flash(f"Şarkı bulunamadı (ID: {song_id}).", "danger"); return redirect(url_for('admin_panel'))
        song_name = song_info.get('name', 'Bilinmeyen Şarkı'); artists = song_info.get('artists'); artist_name = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'
        song_queue.append({'id': song_id, 'name': song_name, 'artist': artist_name, 'added_by': 'admin', 'added_at': time.time()})
        logger.info(f"Şarkı kuyruğa eklendi (Admin): {song_id} - {song_name}")
        flash(f"'{song_name}' kuyruğa eklendi.", "success")
        update_time_profile(song_id, spotify) # Zaman profili için güncelle
    except spotipy.SpotifyException as e:
        logger.error(f"Admin şarkı eklerken Spotify hatası (ID={song_id}): {e}")
        if e.http_status == 401 or e.http_status == 403: flash("Spotify yetkilendirme hatası.", "danger"); return redirect(url_for('spotify_auth'))
        else: flash(f"Spotify hatası: {e.msg}", "danger")
    except Exception as e: logger.error(f"Admin şarkı eklerken genel hata (ID={song_id}): {e}", exc_info=True); flash("Şarkı eklenirken bir hata oluştu.", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Kullanıcı arayüzünden şarkıyı kuyruğa ekleme isteğini işler."""
    if not request.is_json: return jsonify({'error': 'Geçersiz istek formatı.'}), 400
    data = request.get_json(); track_id = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: track_id={track_id}")
    if not track_id: return jsonify({'error': 'Eksik şarkı IDsi.'}), 400
    if len(song_queue) >= settings.get('max_queue_length', 20): logger.warning("Kuyruk maksimum kapasitede."); return jsonify({'error': 'Şarkı kuyruğu şu anda dolu. Lütfen daha sonra deneyin.'}), 429
    user_ip = request.remote_addr; max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests: logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip} ({max_requests} istek)"); return jsonify({'error': f'Kısa süre içinde çok fazla istekte bulundunuz (Limit: {max_requests}).'}), 429
    spotify = get_spotify_client()
    if not spotify: logger.error("Kuyruğa eklenemedi: Spotify istemcisi yok."); return jsonify({'error': 'Spotify bağlantısı şu anda mevcut değil.'}), 503
    try:
        update_time_profile(track_id, spotify) # Önce profili güncelle (şarkı bilgisini almak için)
        profile_name = get_current_time_profile()
        # Profildeki son eklenen şarkı bilgisini alarak kuyruğa ekle
        if profile_name in time_profiles and time_profiles[profile_name] and time_profiles[profile_name][-1].get('id') == track_id:
            added_track_info = time_profiles[profile_name][-1]
            song_queue.append({'id': added_track_info['id'], 'name': added_track_info['name'], 'artist': added_track_info['artist_name'], 'added_by': user_ip, 'added_at': time.time()})
            user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
            logger.info(f"Şarkı kuyruğa eklendi: {added_track_info['name']} - {added_track_info['artist_name']}. Kuyruk uzunluğu: {len(song_queue)}")
            return jsonify({'success': True, 'message': 'Şarkı başarıyla kuyruğa eklendi!'})
        else: # update_time_profile başarısız olduysa veya ID eşleşmiyorsa
             logger.error(f"Şarkı bilgisi profilden alınamadığı için kuyruğa eklenemedi: {track_id}")
             return jsonify({'error': 'Şarkı eklenirken bir sorun oluştu (profil güncellenemedi).'}), 500
    except Exception as e: logger.error(f"Kuyruğa ekleme sırasında hata (ID: {track_id}): {e}", exc_info=True); return jsonify({'error': 'Şarkı eklenirken bir sorun oluştu.'}), 500

@app.route('/remove-song/<song_id>', methods=['POST'])
@admin_login_required
def remove_song(song_id):
    """Admin panelinden şarkıyı kuyruktan kaldırır."""
    global song_queue
    initial_length = len(song_queue)
    song_queue = [song for song in song_queue if song.get('id') != song_id]
    if len(song_queue) < initial_length:
         logger.info(f"Şarkı kuyruktan kaldırıldı (Admin): ID={song_id}")
         flash("Şarkı kuyruktan kaldırıldı.", "success")
    else:
         logger.warning(f"Kuyruktan kaldırılacak şarkı bulunamadı: ID={song_id}")
         flash("Kaldırılacak şarkı kuyrukta bulunamadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    """Admin panelinden tüm şarkı kuyruğunu temizler."""
    global song_queue, user_requests
    song_queue = []; user_requests = {} # Kullanıcı limitlerini de sıfırla
    logger.info("Şarkı kuyruğu ve kullanıcı limitleri temizlendi (Admin).")
    flash("Şarkı kuyruğu temizlendi.", "success")
    return redirect(url_for('admin_panel'))

@app.route('/queue')
def view_queue():
    """Kullanıcıların mevcut şarkı kuyruğunu görmesi için sayfa."""
    global spotify_client # Hata durumunda sıfırlamak için global erişim
    current_q = list(song_queue)
    currently_playing_info = None
    spotify = get_spotify_client()
    if spotify:
        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('item'):
                item = playback['item']
                is_playing = playback.get('is_playing', False)
                track_name = item.get('name')
                artists = item.get('artists', [])
                artist_name = ', '.join([a.get('name') for a in artists if a.get('name')])
                images = item.get('album', {}).get('images', [])
                image_url = images[-1].get('url') if images else None # En küçük resmi al
                currently_playing_info = {'name': track_name, 'artist': artist_name, 'image_url': image_url, 'is_playing': is_playing}
                logger.debug(f"Şu An Çalıyor (Kuyruk Sayfası): {track_name} - Durum: {'Çalıyor' if is_playing else 'Duraklatıldı'}")
        except spotipy.SpotifyException as e:
            logger.warning(f"Çalma durumu alınırken hata (Kuyruk Sayfası): {e}")
            if e.http_status == 401 or e.http_status == 403:
                 spotify_client = None
                 if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        except Exception as e: logger.error(f"Çalma durumu alınırken genel hata (Kuyruk Sayfası): {e}", exc_info=True)
    return render_template('queue.html', queue=current_q, currently_playing_info=currently_playing_info)

@app.route('/api/queue')
def api_get_queue():
    """API üzerinden mevcut kuyruk durumunu döndürür."""
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue), 'max_length': settings.get('max_queue_length', 20)})

# --- ALSA/Bluetooth API Rotaları ---
@app.route('/api/output-devices')
@admin_login_required
def api_output_devices():
    """Mevcut ALSA çıkış cihazlarını döndürür."""
    devices = AudioManager.get_output_devices()
    # current_target_device = AudioManager.get_current_librespot_device() # Bu zaten get_output_devices içinde yapılıyor
    # for device in devices: device['is_default'] = (device['name'] == current_target_device)
    return jsonify({'devices': devices})

@app.route('/api/set-output-device', methods=['POST'])
@admin_login_required
def api_set_output_device():
    """Seçilen ALSA cihazını Raspotify için ayarlar ve servisi yeniden başlatır."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); device_name = data.get('device_name')
    if not device_name: logger.error("API isteğinde 'device_name' eksik."); return jsonify({'success': False, 'error': 'Cihaz adı gerekli'}), 400
    logger.info(f"API: Çıkış cihazı ayarlama isteği: {device_name}")
    success, message = AudioManager.set_librespot_device(device_name)
    updated_devices = AudioManager.get_output_devices() # Güncel listeyi al
    # current_target_device = AudioManager.get_current_librespot_device() # get_output_devices içinde yapılıyor
    # for device in updated_devices: device['is_default'] = (device['name'] == current_target_device)
    status_code = 200 if success else 500
    response_data = {'success': success, 'devices': updated_devices}
    if success: response_data['message'] = message
    else: response_data['error'] = message
    return jsonify(response_data), status_code

@app.route('/api/scan-bluetooth')
@admin_login_required
def api_scan_bluetooth():
    """Çevredeki (bilinen) Bluetooth cihazlarını listeler."""
    logger.info("API: Bluetooth cihaz listeleme isteği alındı.")
    devices = AudioManager.scan_bluetooth_devices()
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
    updated_alsa_devices = AudioManager.get_output_devices() # Güncel ALSA listesi
    updated_bt_devices = AudioManager.scan_bluetooth_devices() # Güncel BT listesi
    message = f"Bluetooth cihazı bağlandı: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlanamadı."
    status_code = 200 if success else 500
    return jsonify({'success': success, 'message': message, 'alsa_devices': updated_alsa_devices, 'bluetooth_devices': updated_bt_devices}), status_code

@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazının bağlantısını keser."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
    logger.info(f"API: Bluetooth cihazı bağlantısını kesme isteği: {mac_address}")
    success = AudioManager.disconnect_bluetooth_device(mac_address)
    updated_alsa_devices = AudioManager.get_output_devices() # Güncel ALSA listesi
    updated_bt_devices = AudioManager.scan_bluetooth_devices() # Güncel BT listesi
    message = f"Bluetooth cihazı bağlantısı kesildi: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlantısı kesilemedi."
    status_code = 200 if success else 500
    return jsonify({'success': success, 'message': message, 'alsa_devices': updated_alsa_devices, 'bluetooth_devices': updated_bt_devices}), status_code


# --- Arka Plan Şarkı Çalma İş Parçacığı ---
def background_queue_player():
    """
    Arka planda şarkı kuyruğunu kontrol eder. 'auto_advance_enabled' ise ve
    çalma durduysa sıradakini çalar. Kuyruk boşsa ve çalma durduysa öneri yapar.
    """
    global spotify_client, song_queue, user_requests, settings, auto_advance_enabled

    logger.info("Arka plan şarkı çalma/öneri görevi başlatılıyor (Admin Kontrollü)...")
    last_played_song_id = None
    last_suggested_song_id = None

    while True:
        try:
            # --- Güncel Spotify istemcisini ve ayarları al ---
            spotify = get_spotify_client()
            active_spotify_connect_device_id = settings.get('active_device_id')

            if not spotify or not active_spotify_connect_device_id:
                time.sleep(10)
                continue

            # --- Mevcut Çalma Durumunu Kontrol Et ---
            current_playback = None
            try:
                current_playback = spotify.current_playback(additional_types='track,episode', market='TR')
            except spotipy.SpotifyException as pb_err:
                logger.error(f"Arka plan: Playback durumu kontrol hatası: {pb_err}")
                if pb_err.http_status == 401 or pb_err.http_status == 403:
                    spotify_client = None
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                time.sleep(10)
                continue
            except Exception as pb_err:
                logger.error(f"Arka plan: Playback durumu kontrolünde beklenmedik hata: {pb_err}", exc_info=True)
                time.sleep(15)
                continue

            # --- Mevcut Durumu İşle ---
            is_playing_now = False
            current_track_id_now = None
            if current_playback:
                is_playing_now = current_playback.get('is_playing', False)
                item = current_playback.get('item')
                current_track_id_now = item.get('id') if item else None

            # --- Kuyruk ve Öneri Mantığı ---

            # 1. Sıradaki Şarkıyı Çalma Koşulu (Basitleştirilmiş + Admin Kontrolü):
            if song_queue and not is_playing_now and auto_advance_enabled:
                logger.info(f"Arka plan: Çalma durdu ve otomatik ilerleme aktif. Kuyruktan çalınıyor...")
                next_song = song_queue.pop(0)

                # Hata durumunda aynı şarkıyı tekrar çalmayı önle
                if next_song.get('id') == last_played_song_id:
                    logger.debug(f"Şarkı ({next_song.get('name')}) zaten son çalınandı (hata önleme), atlanıyor.")
                    last_played_song_id = None
                    time.sleep(1)
                    continue

                logger.info(f"Arka plan: Kuyruktan çalınacak: {next_song.get('name')} ({next_song.get('id')})")
                try:
                    spotify.start_playback(
                        device_id=active_spotify_connect_device_id,
                        uris=[f"spotify:track:{next_song['id']}"]
                    )
                    logger.info(f"===> Şarkı çalmaya başlandı: {next_song.get('name')}")
                    last_played_song_id = next_song['id']
                    last_suggested_song_id = None

                    user_ip = next_song.get('added_by')
                    if user_ip and user_ip != 'admin' and user_ip != 'auto-time':
                        user_requests[user_ip] = max(0, user_requests.get(user_ip, 0) - 1)
                        logger.debug(f"Kullanıcı {user_ip} istek limiti azaltıldı: {user_requests.get(user_ip)}")

                    time.sleep(1) # Yeni durumu algılamak için kısa bekleme
                    continue # Bir sonraki döngüye geç

                except spotipy.SpotifyException as start_err:
                    logger.error(f"Arka plan: Şarkı çalma başlatılamadı ({next_song.get('id')}): {start_err}")
                    song_queue.insert(0, next_song) # Şarkıyı başa geri ekle
                    if start_err.http_status == 401 or start_err.http_status == 403:
                         spotify_client = None
                         if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                    elif start_err.http_status == 404 and 'device_id' in str(start_err).lower():
                         logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device_id}) bulunamadı. Ayar temizleniyor.")
                         settings['active_device_id'] = None
                         save_settings(settings)
                    time.sleep(5)
                    continue
                except Exception as start_err:
                     logger.error(f"Arka plan: Şarkı çalma başlatılırken genel hata ({next_song.get('id')}): {start_err}", exc_info=True)
                     song_queue.insert(0, next_song) # Şarkıyı başa geri ekle
                     time.sleep(10)
                     continue

            # 2. Şarkı Önerisi Yapma:
            elif not song_queue and not is_playing_now:
                suggested = suggest_song_for_time(spotify)
                if suggested and suggested.get('id') != last_suggested_song_id:
                    song_queue.append({
                         'id': suggested['id'],
                         'name': suggested['name'],
                         'artist': suggested.get('artist', 'Bilinmeyen'),
                         'added_by': 'auto-time',
                         'added_at': time.time()
                     })
                    last_suggested_song_id = suggested['id']
                    logger.info(f"Otomatik öneri kuyruğa eklendi: {suggested['name']}")

            # 3. Eğer Müzik Çalıyorsa:
            elif is_playing_now:
                 if current_track_id_now and current_track_id_now != last_played_song_id:
                     logger.debug(f"Arka plan: Yeni şarkı algılandı: {current_track_id_now}")
                     last_played_song_id = current_track_id_now
                     last_suggested_song_id = None # Yeni şarkı başladı, öneri takibini sıfırla

            time.sleep(5) # Normal kontrol aralığı

        except Exception as loop_err:
            logger.error(f"Arka plan döngüsünde beklenmedik hata: {loop_err}", exc_info=True)
            # Büyük hatada durumu sıfırlamak iyi olabilir, ancak şimdilik sadece bekleyelim
            time.sleep(15) # Hata sonrası daha uzun bekleme

# --- Uygulama Başlangıcı ---
def check_token_on_startup():
    """Uygulama başlarken token durumunu kontrol eder ve loglar."""
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client()
    if client: logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else: logger.warning("Başlangıçta Spotify istemcisi alınamadı. Admin panelinden yetkilendirme gerekli olabilir.")

def start_queue_player():
    """Arka plan görevini başlatır."""
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("    (Admin Kontrollü Otomatik İlerleme)        ")
    logger.info("=================================================")
    logger.info(f"Ayarlar Yüklendi: {SETTINGS_FILE}")
    logger.info(f"Raspotify Servisi: {RASPOTIFY_SERVICE_NAME}")
    logger.info(f"Raspotify Config: {RASPOTIFY_CONFIG_FILE}")

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

    # Portu dinamik olarak almayı deneyelim, yoksa 8080 kullanalım
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişebilirsiniz.")
    logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişebilirsiniz.")

    # Uygulamayı başlat (Geliştirme için debug=True, production için False)
    # Production'da Gunicorn gibi bir WSGI sunucusu kullanmanız önerilir.
    app.run(host='0.0.0.0', port=port, debug=True)
