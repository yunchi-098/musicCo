# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Regex kütüphanesi
import subprocess
from functools import wraps
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# --- Yapılandırılabilir Ayarlar ---
# Eğer raspotify.service veya conf dosyanız farklı bir yerdeyse,
# aşağıdaki yolları buna göre düzenleyin.
RASPOTIFY_SERVICE_NAME = "raspotify.service"
RASPOTIFY_CONFIG_FILE = "~/etc/raspotify/conf"

# DAC'ınızı aplay -L çıktısında tanımlayan bir anahtar kelime.
# 'hw:CARD=DAC' gibi belirli bir isim de kullanabilirsiniz.
# 'aplay -l' komutu kart adlarını gösterir, 'aplay -L' cihaz adlarını.
DAC_IDENTIFIER = "PCM5102" # veya "DAC", "USB Audio", "snd_rpi_hifiberry_dac" vb.

# Spotify API Bilgileri - KENDİ BİLGİLERİNİZLE DEĞİŞTİRİN!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78' 
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426' 
# Cihazınızın AĞ üzerindeki IP adresini ve Flask portunu yazın
SPOTIFY_REDIRECT_URI = 'http://192.168.1.103:8080/callback' 
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private'

# Diğer Dosya Yolları
TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
# ---------------------------------

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class AudioManager:
    """ALSA ve Raspotify ile ses cihazlarını yöneten sınıf."""

    @staticmethod
    def get_output_devices():
        """Mevcut ALSA ses çıkış cihazlarını (DAC ve bluealsa) getirir."""
        devices = []
        try:
            # aplay -L çıktısını al
            result = subprocess.run(['aplay', '-L'], capture_output=True, text=True, check=True)

            alsa_device_name = None
            description = None

            # aplay -L çıktısını satır satır işle
            for line in result.stdout.splitlines():
                line = line.strip()

                # Satır bir cihaz adı mı? (boşlukla başlamıyorsa ve null değilse)
                if line and not line[0].isspace() and line != 'null' and not line.startswith('-'):
                    # Önceki cihazı kaydet (varsa)
                    if alsa_device_name and description:
                        device_type = 'other' # Varsayılan tür
                        # Türü belirle (DAC, Bluetooth veya Diğer)
                        if DAC_IDENTIFIER and DAC_IDENTIFIER.lower() in description.lower():
                             device_type = 'dac'
                        elif 'bluealsa' in alsa_device_name.lower():
                             device_type = 'bluetooth'
                        
                        devices.append({
                            'name': alsa_device_name,
                            'description': description.split(',')[0], # Genellikle ilk kısım yeterli olur
                            'type': device_type
                        })
                    # Yeni cihaz bilgilerini sıfırla
                    alsa_device_name = line
                    description = None # Açıklama bir sonraki satırda gelir

                # Cihaz adı alındıysa ve bu satır açıklama ise
                elif alsa_device_name and line and line[0].isspace():
                    if description is None: # Sadece ilk açıklama satırını al
                        description = line.strip()

            # Döngü bittikten sonra son cihazı da ekle
            if alsa_device_name and description and alsa_device_name != 'null':
                device_type = 'other'
                if DAC_IDENTIFIER and DAC_IDENTIFIER.lower() in description.lower():
                     device_type = 'dac'
                elif 'bluealsa' in alsa_device_name.lower():
                     device_type = 'bluetooth'
                devices.append({
                    'name': alsa_device_name,
                    'description': description.split(',')[0],
                    'type': device_type
                })
            
            # Bluealsa cihazlarının açıklamalarını iyileştir
            for device in devices:
                 if device['type'] == 'bluetooth':
                    try:
                        match = re.search(r'DEV=([0-9A-Fa-f:]+)', device['name'])
                        mac = match.group(1) if match else None
                        friendly_name = f"BT Cihazı ({mac})" if mac else "Bluetooth Cihazı"
                        if mac:
                             try:
                                 # bluetoothctl ile cihaz adını almayı dene
                                 info_result = subprocess.run(['bluetoothctl', 'info', mac], capture_output=True, text=True, timeout=5)
                                 if info_result.returncode == 0:
                                     name_match = re.search(r'Name:\s*(.*)', info_result.stdout)
                                     if name_match:
                                         friendly_name = f"BT: {name_match.group(1).strip()}"
                             except Exception as bt_err:
                                logging.warning(f"Bluetooth cihaz adı alınamadı ({mac}): {bt_err}")
                        device['description'] = friendly_name
                    except Exception as e:
                        logging.warning(f"Bluealsa cihaz adı ayrıştırılırken hata: {e}")
                        device['description'] = device.get('description', "Bluetooth Cihazı") # Hata olursa mevcut kalsın

            # Şu anda raspotify'ın kullandığı cihazı belirle
            current_target_device = AudioManager.get_current_librespot_device()
            for device in devices:
                device['is_default'] = (device['name'] == current_target_device)

            logging.info(f"Bulunan ALSA cihazları: {devices}")
            return devices

        except FileNotFoundError:
            logging.error("ALSA komutu 'aplay' bulunamadı. ALSA utils kurulu mu?")
            return []
        except subprocess.CalledProcessError as e:
            logging.error(f"ALSA cihazları listelenirken hata ('aplay -L'): {e.stderr}")
            return []
        except Exception as e:
            logging.error(f"Ses çıkış cihazları listelenirken genel hata: {e}", exc_info=True)
            return []

    @staticmethod
    def get_current_librespot_device():
        """Raspotify yapılandırma dosyasından mevcut LIBRESPOT_DEVICE değerini okur."""
        try:
            if not os.path.exists(RASPOTIFY_CONFIG_FILE):
                logging.warning(f"Raspotify yapılandırma dosyası bulunamadı: {RASPOTIFY_CONFIG_FILE}")
                return None

            with open(RASPOTIFY_CONFIG_FILE, 'r') as f:
                for line in f:
                    # Yorum satırı olmayan ve LIBRESPOT_DEVICE= ile başlayan satırı bul
                    if line.strip().startswith('LIBRESPOT_DEVICE=') and not line.strip().startswith('#'):
                        value = line.split('=', 1)[1].strip()
                        # Değeri tırnak içindeyse tırnakları kaldır
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        logging.debug(f"Mevcut Raspotify cihazı bulundu: {value}")
                        return value
            logging.info(f"Aktif (yorumlanmamış) LIBRESPOT_DEVICE satırı bulunamadı: {RASPOTIFY_CONFIG_FILE}")
            return None # Aktif satır bulunamazsa None döndür
        except Exception as e:
            logging.error(f"Raspotify yapılandırması ({RASPOTIFY_CONFIG_FILE}) okunurken hata: {e}", exc_info=True)
            return None

    @staticmethod
    def set_librespot_device(device_name):
        """Raspotify yapılandırma dosyasını günceller ve servisi yeniden başlatır."""
        try:
            logging.info(f"Raspotify çıkış cihazı {device_name} olarak ayarlanıyor...")

            # 1. Yapılandırma dosyasını güncelle
            if not os.path.exists(RASPOTIFY_CONFIG_FILE):
                logging.error(f"Raspotify yapılandırma dosyası bulunamadı: {RASPOTIFY_CONFIG_FILE}")
                return False, f"Yapılandırma dosyası bulunamadı: {RASPOTIFY_CONFIG_FILE}"

            # Dosya içeriğini oku
            with open(RASPOTIFY_CONFIG_FILE, 'r') as f:
                lines = f.readlines()

            new_lines = []
            found_and_updated = False
            config_line = f'LIBRESPOT_DEVICE="{device_name}"\n' # Yeni satır

            for line in lines:
                stripped_line = line.strip()
                # Mevcut aktif veya yorumlu LIBRESPOT_DEVICE satırını bul
                if stripped_line.startswith('LIBRESPOT_DEVICE=') or stripped_line.startswith('#LIBRESPOT_DEVICE='):
                    if not found_and_updated: # Sadece ilk bulduğunu güncelle/aktifleştir
                        new_lines.append(config_line)
                        found_and_updated = True
                        logging.info(f"'{line.strip()}' satırı şununla değiştirildi/aktifleştirildi: '{config_line.strip()}'")
                    else:
                         # Eğer birden fazla varsa, diğerlerini yorum satırı yap
                         if not stripped_line.startswith('#'):
                             new_lines.append(f"# {line}") # Yorumla
                             logging.warning(f"Ekstra LIBRESPOT_DEVICE satırı yorumlandı: {line.strip()}")
                         else:
                             new_lines.append(line) # Zaten yorumluysa elleme
                else:
                    new_lines.append(line) # Diğer satırları olduğu gibi ekle

            if not found_and_updated:
                logging.info(f"LIBRESPOT_DEVICE satırı dosyada bulunamadı, sona ekleniyor.")
                new_lines.append("\n# Sound Device Selection (managed by web interface)\n")
                new_lines.append(config_line)

            # Yeni içeriği dosyaya yaz (tee komutu ile sudo kullanarak)
            temp_config_content = "".join(new_lines)
            tee_cmd = ['sudo', 'tee', RASPOTIFY_CONFIG_FILE]
            logging.info(f"Komut çalıştırılıyor: echo '...' | {' '.join(tee_cmd)}")
            process = subprocess.Popen(tee_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(input=temp_config_content)

            if process.returncode != 0:
                 logging.error(f"Raspotify yapılandırma dosyası yazılamadı ({RASPOTIFY_CONFIG_FILE}): {stderr}")
                 return False, f"Yapılandırma dosyası güncellenemedi: {stderr}"

            logging.info(f"Yapılandırma dosyası başarıyla güncellendi: {RASPOTIFY_CONFIG_FILE}")

            # 2. Raspotify servisini yeniden başlat (sudo gerektirir!)
            restart_cmd = ['sudo', 'systemctl', 'restart', RASPOTIFY_SERVICE_NAME]
            logging.info(f"Komut çalıştırılıyor: {' '.join(restart_cmd)}")
            result = subprocess.run(restart_cmd, capture_output=True, text=True, timeout=15)

            if result.returncode != 0:
                logging.error(f"Raspotify servisi yeniden başlatılamadı ({RASPOTIFY_SERVICE_NAME}): {result.stderr}")
                return False, f"Raspotify servisi yeniden başlatılamadı: {result.stderr}"

            logging.info(f"Raspotify servisi başarıyla yeniden başlatıldı.")
            time.sleep(2) # Servisin başlaması için kısa bekleme
            return True, f"Raspotify çıkış cihazı {device_name} olarak ayarlandı ve servis yeniden başlatıldı."

        except Exception as e:
            logging.error(f"Raspotify cihazı ayarlanırken hata: {str(e)}", exc_info=True)
            return False, f"Beklenmedik hata: {str(e)}"

    @staticmethod
    def scan_bluetooth_devices():
        """Kullanılabilir bluetooth cihazlarını tarar."""
        try:
            # Gerekirse taramayı açıp kapatabilirsiniz, ancak genellikle 'devices' yeterlidir.
            # subprocess.run(['bluetoothctl', 'scan', 'on'], timeout=5) 
            # time.sleep(5)
            # subprocess.run(['bluetoothctl', 'scan', 'off'])

            result = subprocess.run(['bluetoothctl', 'devices'], capture_output=True, text=True, check=True)
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
            logging.info(f"Bluetooth tarama sonucu: {devices}")
            return devices
        except Exception as e:
            logging.error(f"Bluetooth cihazları taranırken hata: {e}", exc_info=True)
            return []

    @staticmethod
    def pair_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazını eşleştirir ve bağlar."""
        try:
            logging.info(f"Bluetooth cihazı {mac_address} eşleştiriliyor/bağlanıyor...")
            # Güvenilir yap
            trust_cmd = subprocess.run(['bluetoothctl', 'trust', mac_address], capture_output=True, text=True, timeout=10)
            if trust_cmd.returncode != 0:
                 logging.warning(f"Cihaz güvenilir yapılamadı (zaten olabilir): {trust_cmd.stderr}")

            # Bağlan
            connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
            if connect_cmd.returncode != 0:
                logging.warning(f"İlk bağlantı denemesi başarısız ({mac_address}), tekrar deneniyor... {connect_cmd.stderr}")
                time.sleep(3)
                connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)

            if connect_cmd.returncode != 0:
                logging.error(f"Bluetooth cihazı bağlantı hatası ({mac_address}): {connect_cmd.stderr}")
                subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=10) # Bağlantıyı kesmeyi dene
                return False

            logging.info(f"Bluetooth cihazı başarıyla bağlandı: {mac_address}")
            time.sleep(3) # Bluealsa'nın cihazı algılaması için bekle
            return True
        except Exception as e:
            logging.error(f"Bluetooth cihazı eşleştirme/bağlama sırasında hata ({mac_address}): {e}", exc_info=True)
            return False

    @staticmethod
    def disconnect_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazının bağlantısını keser."""
        try:
            logging.info(f"Bluetooth cihazı {mac_address} bağlantısı kesiliyor...")
            cmd = subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, check=True, timeout=10)
            logging.info(f"Bluetooth cihazı bağlantısı başarıyla kesildi: {mac_address}")
            time.sleep(2) # Bluealsa'nın cihazı kaldırması için bekle
            return True
        except Exception as e:
            logging.error(f"Bluetooth cihazı bağlantısını kesme sırasında hata ({mac_address}): {e}", exc_info=True)
            return False

# --- Flask Uygulaması ---
app = Flask(__name__)
app.secret_key = 'mekanmuzikuygulamasi_gizli_anahtar' # Daha güvenli bir anahtar kullanın
app.jinja_env.globals['AudioManager'] = AudioManager # Template içinde kullanmak için

# Global Değişkenler
spotify_client = None
song_queue = []
user_requests = {} # Kullanıcı IP adreslerine göre istek sayısı (basit sınırlama)

# İzin verilen müzik türleri (örnek)
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie']

# Ayarları Yükle/Kaydet
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
             logger.error(f"Ayar dosyası ({SETTINGS_FILE}) bozuk, varsayılanlar kullanılıyor.")
             # Bozuksa varsayılanları oluştur
             pass 
        except Exception as e:
             logger.error(f"Ayarları yüklerken hata: {e}", exc_info=True)
    
    # Varsayılan ayarlar (dosya yoksa veya bozuksa)
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5, # Daha makul bir başlangıç değeri
        'active_device_id': None, # Spotify Connect Cihaz ID'si
        'active_genres': ALLOWED_GENRES[:5] # İlk 5 tür aktif olsun
    }
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(default_settings, f, indent=4)
        logger.info(f"Varsayılan ayarlar dosyası oluşturuldu: {SETTINGS_FILE}")
        return default_settings
    except Exception as e:
         logger.error(f"Varsayılan ayar dosyası oluşturulurken hata: {e}", exc_info=True)
         return default_settings # Hata olsa bile varsayılanı döndür

def save_settings(current_settings):
     try:
         with open(SETTINGS_FILE, 'w') as f:
             json.dump(current_settings, f, indent=4)
         logger.info(f"Ayarlar kaydedildi: {SETTINGS_FILE}")
     except Exception as e:
         logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)

settings = load_settings()

# Spotify Token Yükle/Kaydet
def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Token dosyasını okuma hatası: {e}")
    return None

def save_token(token_info):
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi")
    except Exception as e:
        logger.error(f"Token kaydetme hatası: {e}")


# Spotify Yetkilendirme ve İstemci Alma
def get_spotify_auth():
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        open_browser=False, # Sunucuda tarayıcı açılmasın
        cache_path=None # Kendi token yönetimimizi kullanıyoruz
    )

def get_spotify_client():
    global spotify_client
    token_info = load_token()

    if not token_info:
        logger.warning("Spotify token bulunamadı. Lütfen admin panelinden yetkilendirin.")
        return None

    auth_manager = get_spotify_auth()

    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token süresi dolmuş, yenileniyor...")
            # Refresh token yoksa veya yenileme başarısız olursa None döner
            token_info = auth_manager.refresh_access_token(token_info.get('refresh_token')) 
            if not token_info:
                 logger.error("Token yenilenemedi. Refresh token geçersiz veya eksik olabilir.")
                 if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE) # Geçersiz token'ı sil
                 return None
            save_token(token_info)
        
        # Eğer mevcut istemci varsa ve token eşleşiyorsa, onu kullan
        if spotify_client and spotify_client.auth == token_info.get('access_token'):
             return spotify_client

        # Yeni istemci oluştur
        new_spotify_client = spotipy.Spotify(auth=token_info.get('access_token'))
        
        # İstemciyi test et
        try:
            new_spotify_client.current_user() # Basit bir test isteği
            spotify_client = new_spotify_client # Global istemciyi güncelle
            logger.info("Spotify istemcisi başarıyla alındı/yenilendi.")
            return spotify_client
        except Exception as e:
             logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası: {e}")
             # Token geçersiz olabilir
             if "invalid access token" in str(e).lower() or "token expired" in str(e).lower():
                  if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
             return None

    except Exception as e:
        logger.error(f"Spotify token işlemi sırasında genel hata: {e}", exc_info=True)
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE) # Sorun varsa token'ı sil
        return None


# Admin Giriş Decorator'ı
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Flask Rotaları ---

@app.route('/')
def index():
    # Ana sayfada izin verilen türleri göster
    return render_template('index.html', allowed_genres=settings.get('active_genres', ALLOWED_GENRES))

@app.route('/admin')
def admin():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    # Şifreyi daha güvenli bir yerden okuyun (örn: environment variable, config dosyası)
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mekan123") # Örnek: Varsayılan veya ortam değişkeni
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        logger.info("Admin girişi başarılı")
        return redirect(url_for('admin_panel'))
    logger.warning("Başarısız admin girişi denemesi")
    # TODO: Brute-force koruması ekleyin (örn: flask-limiter)
    return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    global spotify_client
    spotify_client = None
    session.clear() # Tüm session verilerini temizle
    # Token dosyasını silmek isteğe bağlıdır, tekrar yetkilendirme gerektirir
    # if os.path.exists(TOKEN_FILE):
    #     try:
    #         os.remove(TOKEN_FILE)
    #         logger.info("Token dosyası silindi")
    #     except Exception as e:
    #         logger.error(f"Token dosyası silinirken hata: {e}")
    logger.info("Admin çıkışı yapıldı.")
    return redirect(url_for('admin'))


@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    
    # ALSA Cihazları
    output_devices = AudioManager.get_output_devices()
    current_active_alsa_device = AudioManager.get_current_librespot_device()

    if spotify:
        try:
            result = spotify.devices()
            spotify_devices = result.get('devices', [])
            spotify_authenticated = True
            session['spotify_authenticated'] = True # Session'ı güncelle
            try:
                 user = spotify.current_user()
                 session['spotify_user'] = user.get('display_name')
            except: pass # Kullanıcı bilgisi alınamazsa sorun değil
        except Exception as e:
            logger.error(f"Spotify cihazları/kullanıcı bilgisi alınırken hata: {e}")
            if "unauthorized" in str(e).lower() or "token" in str(e).lower():
                spotify_authenticated = False
                session['spotify_authenticated'] = False
                session.pop('spotify_user', None)
                # Token geçersizse, token dosyasını silmeyi düşünebilirsiniz
                # if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            # Diğer hatalarda devam et, paneli göster
    else:
         spotify_authenticated = False # İstemci alınamadıysa
         session['spotify_authenticated'] = False
         session.pop('spotify_user', None)


    return render_template(
        'admin_panel.html',
        settings=settings,
        devices=spotify_devices, # Spotify Connect cihazları
        queue=song_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_device_id=settings.get('active_device_id'), # Spotify Connect aktif cihazı
        output_devices=output_devices, # ALSA çıkış cihazları
        current_active_alsa_device=current_active_alsa_device # Raspotify'ın kullandığı ALSA cihazı
    )

@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    """Spotify Connect cihaz listesini yeniler."""
    spotify = get_spotify_client()
    if not spotify:
        logger.warning("Cihazları yenilemek için Spotify yetkilendirmesi gerekli")
        # Hata mesajı göstermek daha iyi olabilir
        return redirect(url_for('admin_panel')) 

    try:
        result = spotify.devices()
        devices = result.get('devices', [])
        logger.info(f"Spotify Connect Cihazları yenilendi: {len(devices)} cihaz bulundu")
        
        # Aktif Spotify Connect cihazı hala listede mi kontrol et
        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device:
            device_exists = any(d['id'] == active_spotify_connect_device for d in devices)
            if not device_exists:
                logger.warning(f"Ayarlarda kayıtlı aktif Spotify Connect cihazı ({active_spotify_connect_device}) artık mevcut değil. Ayar temizleniyor.")
                settings['active_device_id'] = None
                save_settings(settings)
        
    except Exception as e:
        logger.error(f"Spotify Connect Cihazlarını yenilerken hata: {e}")
        if "unauthorized" in str(e).lower() or "token" in str(e).lower():
             logger.warning("Spotify yetkilendirmesi geçersiz, lütfen yeniden yetkilendirin.")
             # Kullanıcıyı bilgilendir
        # Hata olsa bile panele dön
        
    return redirect(url_for('admin_panel'))


@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    global settings # Global ayarlara erişim

    try:
        settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))
        
        # Aktif Spotify Connect Cihazını Güncelle
        new_spotify_device_id = request.form.get('active_device_id')
        # Eğer formda bu alan varsa ve değeri boş değilse güncelle
        # Bu alan sadece Spotify cihaz listesindeki formdan gelir
        if 'active_device_id' in request.form:
             settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {settings['active_device_id']}")

        # Aktif Müzik Türlerini Güncelle
        settings['active_genres'] = [genre for genre in ALLOWED_GENRES if request.form.get(f'genre_{genre}')]

        save_settings(settings)
        logger.info(f"Ayarlar güncellendi: {settings}")
    except ValueError:
         logger.error("Ayarları güncellerken geçersiz sayısal değer alındı.")
         # Kullanıcıya hata mesajı gösterilebilir
    except Exception as e:
         logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True)
         # Kullanıcıya hata mesajı gösterilebilir

    return redirect(url_for('admin_panel'))

# --- Spotify Yetkilendirme Rotaları ---

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    """Kullanıcıyı Spotify yetkilendirme sayfasına yönlendirir."""
    # Aktif bir token varsa önce onu silmeyi düşünebilirsiniz ya da sormadan yönlendirin
    if os.path.exists(TOKEN_FILE):
        logger.warning("Mevcut token varken yeniden yetkilendirme başlatılıyor.")
        # os.remove(TOKEN_FILE) # İsteğe bağlı: eski token'ı sil
    
    try:
        auth_manager = get_spotify_auth()
        auth_url = auth_manager.get_authorize_url()
        logger.info("Spotify yetkilendirme URL'sine yönlendiriliyor.")
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True)
        # Kullanıcıya hata göster
        return "Spotify yetkilendirme başlatılamadı. Lütfen tekrar deneyin.", 500

@app.route('/callback')
def callback():
    """Spotify tarafından yetkilendirme sonrası geri çağrılan endpoint."""
    auth_manager = get_spotify_auth()
    if 'error' in request.args:
        error = request.args.get('error')
        logger.error(f"Spotify yetkilendirme hatası (callback): {error}")
        # Kullanıcıya hata göster
        return f"Spotify Yetkilendirme Hatası: {error}", 400
        
    if 'code' not in request.args:
        logger.error("Callback'te 'code' parametresi bulunamadı.")
        return "Geçersiz callback isteği.", 400

    code = request.args.get('code')
    try:
        # Code karşılığında token al
        token_info = auth_manager.get_access_token(code, check_cache=False) # Cache kullanma
        if not token_info:
             logger.error("Spotify'dan geçerli token alınamadı.")
             return "Token alınamadı.", 500

        # Token'ı kaydet
        save_token(token_info)
        
        # Global istemciyi sıfırla ki bir sonraki get_spotify_client çağrısı yenisini oluştursun
        global spotify_client
        spotify_client = None 
        
        logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")
        
        # Giriş yapmış admin ise panele, değilse ana sayfaya (veya başka bir sayfaya) yönlendir
        if session.get('admin_logged_in'):
            return redirect(url_for('admin_panel'))
        else:
            # Yetkilendirme sonrası kullanıcıyı bilgilendiren bir sayfa daha iyi olabilir
            return redirect(url_for('index')) 

    except Exception as e:
        logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True)
        return "Token işlenirken bir hata oluştu.", 500

@app.route('/refresh-token')
@admin_login_required
def refresh_token():
    """Spotify token'ını manuel olarak yenilemeye çalışır."""
    global spotify_client
    spotify_client = None # Mevcut istemciyi temizle

    token_info = load_token()
    if not token_info:
        logger.warning("Yenilenecek token bulunamadı. Lütfen önce yetkilendirin.")
        return redirect(url_for('spotify_auth'))

    if 'refresh_token' not in token_info:
        logger.error("Token bilgisinde 'refresh_token' eksik. Tam yetkilendirme gerekli.")
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        return redirect(url_for('spotify_auth'))

    auth_manager = get_spotify_auth()
    try:
        new_token = auth_manager.refresh_access_token(token_info['refresh_token'])
        if not new_token:
             logger.error("Token yenilenemedi. Refresh token geçersiz olabilir.")
             if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
             return redirect(url_for('spotify_auth'))

        save_token(new_token)
        logger.info("Spotify Token başarıyla yenilendi!")
        # Session'ı da güncelleyebiliriz (isteğe bağlı)
        session['spotify_authenticated'] = True 
    except Exception as e:
        logger.error(f"Token yenileme sırasında hata: {e}", exc_info=True)
        # Yenileme başarısız olursa eski token'ı silip yeniden yetkilendirme isteyelim
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        session['spotify_authenticated'] = False
        return redirect(url_for('spotify_auth'))

    return redirect(url_for('admin_panel'))


# --- Şarkı Arama ve Kuyruk Yönetimi Rotaları ---

@app.route('/search', methods=['POST'])
def search():
    """Kullanıcı arayüzünden gelen şarkı arama isteklerini işler."""
    search_query = request.form.get('search_query')
    genre_filter = request.form.get('genre_filter')
    logger.info(f"Arama isteği: Sorgu='{search_query}', Tür='{genre_filter}'")

    # Basit kontroller
    if not search_query:
        return jsonify({'error': 'Lütfen bir arama terimi girin.'}), 400
    if genre_filter not in settings.get('active_genres', ALLOWED_GENRES):
        logger.warning(f"Arama isteğinde izin verilmeyen tür: {genre_filter}")
        return jsonify({'error': 'Seçilen müzik türü şu anda aktif değil.'}), 400

    spotify = get_spotify_client()
    if not spotify:
        logger.error("Arama yapılamadı: Spotify istemcisi yok.")
        return jsonify({'error': 'Spotify bağlantısı şu anda mevcut değil. Lütfen daha sonra tekrar deneyin.'}), 503

    try:
        # Arama sorgusunu oluştur (tür filtresiyle)
        query = f'track:"{search_query}"'
        if genre_filter:
             query += f' genre:"{genre_filter}"'
             
        results = spotify.search(q=query, type='track', limit=10) # Limiti ayarlayabilirsiniz
        tracks = results.get('tracks', {}).get('items', [])
        logger.info(f"Arama sonucu: {len(tracks)} şarkı bulundu.")
        
        search_results = []
        for track in tracks:
            # Gerekli bilgileri al (hata kontrolüyle)
            track_id = track.get('id')
            track_name = track.get('name')
            artists = track.get('artists', [])
            artist_name = artists[0].get('name') if artists else 'Bilinmeyen Sanatçı'
            album = track.get('album', {})
            album_name = album.get('name')
            images = album.get('images', [])
            # En küçük boyutlu resmi al (varsa)
            image_url = images[-1].get('url') if images else None 
            
            if track_id and track_name: # ID ve isim varsa ekle
                search_results.append({
                    'id': track_id,
                    'name': track_name,
                    'artist': artist_name,
                    'album': album_name,
                    'image': image_url
                })
                
        return jsonify({'results': search_results})

    except Exception as e:
        logger.error(f"Spotify araması sırasında hata: {e}", exc_info=True)
        # Kullanıcıya daha genel bir hata mesajı göster
        return jsonify({'error': 'Arama sırasında bir sorun oluştu. Lütfen tekrar deneyin.'}), 500


@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Kullanıcı arayüzünden şarkıyı kuyruğa ekleme isteğini işler."""
    if not request.is_json:
        logger.error("Kuyruğa ekleme isteği JSON formatında değil.")
        return jsonify({'error': 'Geçersiz istek formatı.'}), 400

    data = request.get_json()
    track_id = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: track_id={track_id}")

    if not track_id:
        return jsonify({'error': 'Eksik şarkı IDsi.'}), 400

    # Kuyruk ve kullanıcı limiti kontrolleri
    if len(song_queue) >= settings.get('max_queue_length', 20):
        logger.warning("Kuyruk maksimum kapasitede.")
        return jsonify({'error': 'Şarkı kuyruğu şu anda dolu. Lütfen daha sonra deneyin.'}), 429 # Too Many Requests
    
    user_ip = request.remote_addr
    max_requests = settings.get('max_user_requests', 5)
    if user_requests.get(user_ip, 0) >= max_requests:
        logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip} ({max_requests} istek)")
        return jsonify({'error': f'Kısa süre içinde çok fazla istekte bulundunuz. Lütfen biraz bekleyin (Limit: {max_requests}).'}), 429

    spotify = get_spotify_client()
    if not spotify:
        logger.error("Kuyruğa eklenemedi: Spotify istemcisi yok.")
        return jsonify({'error': 'Spotify bağlantısı şu anda mevcut değil.'}), 503

    try:
        # Şarkı bilgilerini al (ve varlığını doğrula)
        track = spotify.track(track_id)
        if not track: # Şarkı bulunamazsa
             return jsonify({'error': 'Belirtilen şarkı bulunamadı.'}), 404

        # Kuyruğa ekle
        song_queue.append({
            'id': track['id'],
            'name': track['name'],
            'artist': track['artists'][0]['name'] if track.get('artists') else 'Bilinmeyen',
            'added_by': user_ip,
            'added_at': time.time()
        })
        
        # Kullanıcının istek sayısını artır
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        
        logger.info(f"Şarkı kuyruğa eklendi: {track['name']} - {track['artists'][0]['name']}. Kuyruk uzunluğu: {len(song_queue)}")
        return jsonify({'success': True, 'message': 'Şarkı başarıyla kuyruğa eklendi!'})

    except Exception as e:
        logger.error(f"Kuyruğa ekleme sırasında Spotify hatası: {e}", exc_info=True)
        # Genel hata mesajı
        return jsonify({'error': 'Şarkı eklenirken bir sorun oluştu.'}), 500


@app.route('/remove-song/<song_id>', methods=['POST'])
@admin_login_required
def remove_song(song_id):
    """Admin panelinden şarkıyı kuyruktan kaldırır."""
    global song_queue
    initial_length = len(song_queue)
    song_queue = [song for song in song_queue if song.get('id') != song_id]
    if len(song_queue) < initial_length:
         logger.info(f"Şarkı kuyruktan kaldırıldı (Admin): ID={song_id}")
    else:
         logger.warning(f"Kuyruktan kaldırılacak şarkı bulunamadı: ID={song_id}")
    return redirect(url_for('admin_panel'))


@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    """Admin panelinden tüm şarkı kuyruğunu temizler."""
    global song_queue, user_requests
    song_queue = []
    user_requests = {} # Kullanıcı limitlerini de sıfırla
    logger.info("Şarkı kuyruğu ve kullanıcı limitleri temizlendi (Admin).")
    return redirect(url_for('admin_panel'))

@app.route('/queue')
def view_queue():
    """Kullanıcıların mevcut şarkı kuyruğunu görmesi için sayfa."""
    # Kuyruğun bir kopyasını gönderelim ki render sırasında değişirse sorun olmasın
    current_q = list(song_queue) 
    return render_template('queue.html', queue=current_q)

@app.route('/api/queue')
def api_get_queue():
    """API üzerinden mevcut kuyruk durumunu döndürür."""
    return jsonify({
        'queue': song_queue,
        'queue_length': len(song_queue),
        'max_length': settings.get('max_queue_length', 20)
    })

# --- ALSA/Bluetooth API Rotaları ---

@app.route('/api/output-devices')
@admin_login_required
def api_output_devices():
    """Mevcut ALSA çıkış cihazlarını döndürür."""
    devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    # is_default bilgisini tekrar kontrol et (nadiren de olsa değişmiş olabilir)
    for device in devices:
        device['is_default'] = (device['name'] == current_target_device)
    return jsonify({'devices': devices})

@app.route('/api/set-output-device', methods=['POST'])
@admin_login_required
def api_set_output_device():
    """Seçilen ALSA cihazını Raspotify için ayarlar ve servisi yeniden başlatır."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    
    data = request.get_json()
    device_name = data.get('device_name')
    if not device_name:
        logger.error("API isteğinde 'device_name' eksik.")
        return jsonify({'success': False, 'error': 'Cihaz adı gerekli'}), 400

    logger.info(f"API: Çıkış cihazı ayarlama isteği: {device_name}")
    success, message = AudioManager.set_librespot_device(device_name)

    # Başarı veya hata durumunda güncel cihaz listesini alıp döndür
    updated_devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    for device in updated_devices:
        device['is_default'] = (device['name'] == current_target_device)

    if success:
        return jsonify({
            'success': True,
            'message': message,
            'devices': updated_devices
        })
    else:
        return jsonify({
            'success': False,
            'error': message,
            'devices': updated_devices # Hata olsa bile güncel listeyi gönder
        }), 500 # Sunucu hatası

@app.route('/api/scan-bluetooth')
@admin_login_required
def api_scan_bluetooth():
    """Çevredeki Bluetooth cihazlarını tarar."""
    logger.info("API: Bluetooth cihaz tarama isteği alındı.")
    devices = AudioManager.scan_bluetooth_devices()
    return jsonify({'success': True, 'devices': devices})

@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazını eşleştirir/bağlar."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400

    logger.info(f"API: Bluetooth cihazı eşleştirme/bağlama isteği: {mac_address}")
    success = AudioManager.pair_bluetooth_device(mac_address)
    
    # İşlem sonrası güncel ALSA listesini döndür
    updated_devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    for device in updated_devices:
        device['is_default'] = (device['name'] == current_target_device)

    message = f"Bluetooth cihazı bağlandı: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlanamadı."
    status_code = 200 if success else 500
    
    return jsonify({
        'success': success,
        'message': message,
        'devices': updated_devices
        }), status_code


@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazının bağlantısını keser."""
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400

    logger.info(f"API: Bluetooth cihazı bağlantısını kesme isteği: {mac_address}")
    success = AudioManager.disconnect_bluetooth_device(mac_address)

    # İşlem sonrası güncel ALSA listesini döndür
    updated_devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    for device in updated_devices:
        device['is_default'] = (device['name'] == current_target_device)

    message = f"Bluetooth cihazı bağlantısı kesildi: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlantısı kesilemedi."
    status_code = 200 if success else 500

    return jsonify({
        'success': success,
        'message': message,
        'devices': updated_devices
        }), status_code


# --- Arka Plan Şarkı Çalma İş Parçacığı ---
def background_queue_player():
    """Arka planda şarkı kuyruğunu kontrol eder ve çalar."""
    global spotify_client # Global istemciye erişim
    global song_queue # Kuyruğa erişim
    global user_requests # İstek limitlerini azaltmak için

    logger.info("Arka plan şarkı çalma görevi başlatılıyor...")
    last_song_id = None # Son çalınan şarkıyı takip et

    while True:
        try:
            spotify = get_spotify_client() # Her döngüde güncel istemciyi al
            active_spotify_connect_device_id = settings.get('active_device_id')

            if not spotify:
                #logger.warning("Arka plan: Spotify istemcisi yok, 10sn bekleniyor.")
                time.sleep(10)
                continue

            if not active_spotify_connect_device_id:
                #logger.debug("Arka plan: Aktif Spotify Connect cihazı seçilmemiş.")
                time.sleep(5)
                continue

            # Çalma durumunu kontrol et
            current_playback = None
            try:
                # Sadece gerekli bilgileri isteyelim (daha az API yükü)
                current_playback = spotify.current_playback(additional_types='track,episode')
            except Exception as pb_err:
                 # Hata genellikle token süresinin dolması veya cihazın offline olmasıdır
                 logger.error(f"Arka plan: Playback durumu kontrol hatası: {pb_err}")
                 # Token hatasıysa istemciyi sıfırla, bir sonraki döngüde yenilensin
                 if "token" in str(pb_err).lower():
                      spotify_client = None
                 time.sleep(10) # Hata durumunda daha uzun bekle
                 continue

            is_playing = current_playback and current_playback.get('is_playing')
            current_track_id = current_playback.get('item', {}).get('id') if current_playback and current_playback.get('item') else None

            # Eğer bir şey çalmıyorsa ve kuyrukta şarkı varsa
            if not is_playing and song_queue:
                next_song = song_queue.pop(0) # Kuyruktan ilk şarkıyı al
                logger.info(f"Arka plan: Kuyruktan çalınacak: {next_song['name']} ({next_song['id']})")
                try:
                    spotify.start_playback(
                        device_id=active_spotify_connect_device_id,
                        uris=[f"spotify:track:{next_song['id']}"]
                    )
                    logger.info(f"===> Şarkı çalmaya başlandı: {next_song['name']}")
                    last_song_id = next_song['id'] # Son çalınan olarak işaretle
                    
                    # Şarkıyı ekleyen kullanıcının limitini azalt
                    user_ip = next_song.get('added_by')
                    if user_ip in user_requests:
                        user_requests[user_ip] = max(0, user_requests[user_ip] - 1)
                        logger.debug(f"Kullanıcı {user_ip} istek limiti azaltıldı: {user_requests[user_ip]}")

                except Exception as start_err:
                    logger.error(f"Arka plan: Şarkı çalma başlatılamadı ({next_song['id']}): {start_err}")
                    # Çalınamayan şarkıyı tekrar kuyruğun başına ekle (tekrar denensin)
                    song_queue.insert(0, next_song) 
                    time.sleep(5) # Hata durumunda bekle
                
            # Eğer bir şey çalıyorsa ve bu şarkı az önce başlattığımız şarkı değilse
            # ve kuyrukta şarkı varsa (ve şarkı bitmek üzereyse - isteğe bağlı)
            elif is_playing and current_track_id != last_song_id and song_queue:
                 # Bu durum, dışarıdan başka bir şarkı başlatıldığında oluşabilir.
                 # İsteğe bağlı olarak kuyruğu temizleyebilir veya sıradakini hazırlayabilirsiniz.
                 pass # Şimdilik bir şey yapma

            # Eğer bir şey çalmıyorsa ve kuyruk boşsa bekle
            elif not is_playing and not song_queue:
                 #logger.debug("Arka plan: Kuyruk boş ve çalma yok.")
                 pass

            # Normal bekleme süresi
            time.sleep(3) # Kontrol sıklığı

        except Exception as loop_err:
            logger.error(f"Arka plan döngüsünde beklenmedik hata: {loop_err}", exc_info=True)
            time.sleep(15) # Büyük hatalarda daha uzun bekle


def start_queue_player():
    """Arka plan görevini başlatır."""
    thread = threading.Thread(target=background_queue_player, daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma görevi başlatıldı.")

# --- Uygulama Başlangıcı ---
def check_token_on_startup():
    """Uygulama başlarken token durumunu kontrol eder ve gerekirse yeniler."""
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    get_spotify_client() # Bu fonksiyon token'ı kontrol eder, yeniler ve global istemciyi ayarlar


if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("=================================================")
    logger.info(f"Ayarlar Yüklendi: {SETTINGS_FILE}")
    logger.info(f"Raspotify Servisi: {RASPOTIFY_SERVICE_NAME}")
    logger.info(f"Raspotify Config: {RASPOTIFY_CONFIG_FILE}")
    
    # Spotify ID/Secret kontrolü
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID == 'YOUR_SPOTIFY_CLIENT_ID' or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET == 'YOUR_SPOTIFY_CLIENT_SECRET' or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI == 'http://YOUR_DEVICE_IP:8080/callback':
        logger.error("LÜTFEN app.py dosyasında Spotify API bilgilerinizi (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) ayarlayın!")
        # Uygulamayı çalıştırmadan çıkmak daha iyi olabilir
        # exit(1)

    check_token_on_startup()
    start_queue_player()

    # Uygulamayı başlat
    # Production ortamında debug=False kullanın!
    # SSL kullanmak için: app.run(ssl_context='adhoc', host='0.0.0.0', port=8080, debug=False)
    # (pip install pyopenssl gerektirir)
    app.run(host='0.0.0.0', port=8080, debug=True)