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
# Cihazınızın AĞ üzerindeki IP adresini ve Flask portunu yazın
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
                # Gerekirse dizin izinlerini ayarlayın (örneğin, sudo olmadan erişim için)
                # os.chmod(config_dir, 0o777) # Dikkatli kullanın
            except Exception as e:
                logger.error(f"Raspotify yapılandırma dizini oluşturulamadı ({config_dir}): {e}")
                return False
        return True

    @staticmethod
    def get_output_devices():
        """Mevcut ALSA ses çıkış cihazlarını (DAC ve bluealsa) getirir."""
        devices = []
        try:
            # aplay -L çıktısını al
            result = subprocess.run(['aplay', '-L'], capture_output=True, text=True, check=True, timeout=10) # Timeout eklendi

            alsa_device_name = None
            description = None

            # aplay -L çıktısını satır satır işle
            for line in result.stdout.splitlines():
                line = line.strip()

                # Satır bir cihaz adı mı? (boşlukla başlamıyorsa ve null/default değilse)
                if line and not line[0].isspace() and line != 'null' and not line.startswith('-') and line != 'default':
                    # Önceki cihazı kaydet (varsa)
                    if alsa_device_name and description:
                        device_type = 'other' # Varsayılan tür
                        if DAC_IDENTIFIER and DAC_IDENTIFIER.lower() in description.lower():
                             device_type = 'dac'
                        elif 'bluealsa' in alsa_device_name.lower():
                             device_type = 'bluetooth'

                        devices.append({
                            'name': alsa_device_name,
                            'description': description.split(',')[0].strip(), # Genellikle ilk kısım yeterli olur
                            'type': device_type
                        })
                    # Yeni cihaz bilgilerini sıfırla
                    alsa_device_name = line
                    description = None # Açıklama bir sonraki satırda gelir

                # Cihaz adı alındıysa ve bu satır açıklama ise
                elif alsa_device_name and line and line[0].isspace():
                    if description is None: # Sadece ilk açıklama satırını al
                        description = line.strip()

            # Döngü bittikten sonra son cihazı da ekle (null/default değilse)
            if alsa_device_name and description and alsa_device_name != 'null' and alsa_device_name != 'default':
                device_type = 'other'
                if DAC_IDENTIFIER and DAC_IDENTIFIER.lower() in description.lower():
                     device_type = 'dac'
                elif 'bluealsa' in alsa_device_name.lower():
                     device_type = 'bluetooth'
                devices.append({
                    'name': alsa_device_name,
                    'description': description.split(',')[0].strip(),
                    'type': device_type
                })

            # Bluealsa cihazlarının açıklamalarını iyileştir
            for device in devices:
                 if device['type'] == 'bluetooth':
                    try:
                        # Örnek bluealsa adı: bluealsa: DEV=XX:XX:XX:XX:XX:XX, PROFILE=a2dp
                        match = re.search(r'DEV=([0-9A-Fa-f:]+)', device['name'])
                        mac = match.group(1) if match else None
                        friendly_name = f"BT Cihazı ({mac})" if mac else "Bluetooth Cihazı"
                        if mac:
                             try:
                                 # bluetoothctl ile cihaz adını almayı dene
                                 info_result = subprocess.run(['bluetoothctl', 'info', mac], capture_output=True, text=True, timeout=5)
                                 if info_result.returncode == 0:
                                     name_match = re.search(r'Name:\s*(.*)', info_result.stdout)
                                     alias_match = re.search(r'Alias:\s*(.*)', info_result.stdout)
                                     # Önce Alias'ı kullan, yoksa Name'i
                                     bt_name = alias_match.group(1).strip() if alias_match else (name_match.group(1).strip() if name_match else None)
                                     if bt_name:
                                         friendly_name = f"BT: {bt_name}"
                             except Exception as bt_err:
                                logger.warning(f"Bluetooth cihaz adı alınamadı ({mac}): {bt_err}")
                        device['description'] = friendly_name
                    except Exception as e:
                        logging.warning(f"Bluealsa cihaz adı ayrıştırılırken hata: {e}")
                        device['description'] = device.get('description', "Bluetooth Cihazı") # Hata olursa mevcut kalsın

            # Şu anda raspotify'ın kullandığı cihazı belirle
            current_target_device = AudioManager.get_current_librespot_device()
            for device in devices:
                device['is_default'] = (device['name'] == current_target_device)

            logger.info(f"Bulunan ALSA cihazları: {len(devices)} adet")
            # logger.debug(f"ALSA Cihaz Listesi: {devices}") # Detaylı loglama için
            return devices

        except FileNotFoundError:
            logging.error("ALSA komutu 'aplay' bulunamadı. ALSA utils kurulu mu?")
            return []
        except subprocess.CalledProcessError as e:
            logging.error(f"ALSA cihazları listelenirken hata ('aplay -L'): {e.stderr}")
            return []
        except subprocess.TimeoutExpired:
             logging.error("ALSA cihazları listelenirken zaman aşımı ('aplay -L'). Sistem yavaş olabilir.")
             return []
        except Exception as e:
            logging.error(f"Ses çıkış cihazları listelenirken genel hata: {e}", exc_info=True)
            return []

    @staticmethod
    def get_current_librespot_device():
        """Raspotify yapılandırma dosyasından mevcut LIBRESPOT_DEVICE değerini okur."""
        # Önce dizinin varlığını kontrol et
        if not os.path.exists(os.path.dirname(RASPOTIFY_CONFIG_FILE)):
             logger.warning(f"Raspotify yapılandırma dizini mevcut değil: {os.path.dirname(RASPOTIFY_CONFIG_FILE)}")
             return None
        # Sonra dosyanın varlığını kontrol et
        if not os.path.exists(RASPOTIFY_CONFIG_FILE):
            logger.warning(f"Raspotify yapılandırma dosyası bulunamadı: {RASPOTIFY_CONFIG_FILE}")
            return None

        try:
            with open(RASPOTIFY_CONFIG_FILE, 'r') as f:
                for line in f:
                    # Yorum satırı olmayan ve LIBRESPOT_DEVICE= ile başlayan satırı bul
                    if line.strip().startswith('LIBRESPOT_DEVICE=') and not line.strip().startswith('#'):
                        value = line.split('=', 1)[1].strip()
                        # Değeri tırnak içindeyse tırnakları kaldır
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        logger.debug(f"Mevcut Raspotify cihazı bulundu: {value}")
                        return value
            logger.info(f"Aktif (yorumlanmamış) LIBRESPOT_DEVICE satırı bulunamadı: {RASPOTIFY_CONFIG_FILE}")
            return None # Aktif satır bulunamazsa None döndür
        except Exception as e:
            logger.error(f"Raspotify yapılandırması ({RASPOTIFY_CONFIG_FILE}) okunurken hata: {e}", exc_info=True)
            return None

    @staticmethod
    def set_librespot_device(device_name):
        """Raspotify yapılandırma dosyasını günceller ve servisi yeniden başlatır."""
        # Önce config dizinini kontrol et/oluştur
        if not AudioManager._ensure_config_dir_exists():
             return False, f"Yapılandırma dizini oluşturulamadı/erişilemedi: {os.path.dirname(RASPOTIFY_CONFIG_FILE)}"

        try:
            logging.info(f"Raspotify çıkış cihazı {device_name} olarak ayarlanıyor...")

            # 1. Yapılandırma dosyasını oku veya oluştur
            lines = []
            if os.path.exists(RASPOTIFY_CONFIG_FILE):
                try:
                    with open(RASPOTIFY_CONFIG_FILE, 'r') as f:
                        lines = f.readlines()
                except Exception as read_err:
                     logger.error(f"Mevcut Raspotify yapılandırma dosyası okunamadı ({RASPOTIFY_CONFIG_FILE}): {read_err}")
                     # Okunamıyorsa boş kabul edip devam etmeyi deneyebiliriz veya hata verebiliriz. Hata verelim.
                     return False, f"Mevcut yapılandırma dosyası okunamadı: {read_err}"
            else:
                 logger.info(f"Raspotify yapılandırma dosyası mevcut değil, yeni oluşturulacak: {RASPOTIFY_CONFIG_FILE}")


            new_lines = []
            found_and_updated = False
            config_line = f'LIBRESPOT_DEVICE="{device_name}"\n' # Yeni satır

            for line in lines:
                stripped_line = line.strip()
                # Mevcut aktif veya yorumlu LIBRESPOT_DEVICE satırını bul
                if stripped_line.startswith('LIBRESPOT_DEVICE=') or stripped_line.startswith('#LIBRESPOT_DEVICE='):
                    if not found_and_updated: # Sadece ilk bulduğunu güncelle/aktifleştir
                        # Eğer zaten doğruysa değiştirme
                        current_val_match = re.match(r'^#?LIBRESPOT_DEVICE=(["\']?)(.*)\1$', stripped_line)
                        if current_val_match and current_val_match.group(2) == device_name and not stripped_line.startswith('#'):
                            new_lines.append(line) # Olduğu gibi bırak
                            logger.info(f"LIBRESPOT_DEVICE zaten '{device_name}' olarak ayarlı.")
                        else:
                            new_lines.append(config_line) # Yeni değeri yaz
                            logger.info(f"'{line.strip()}' satırı şununla değiştirildi/aktifleştirildi: '{config_line.strip()}'")
                        found_and_updated = True
                    else:
                         # Eğer birden fazla varsa, diğerlerini yorum satırı yap
                         if not stripped_line.startswith('#'):
                             new_lines.append(f"# {line.strip()}\n") # Yorumla ve satır sonu ekle
                             logging.warning(f"Ekstra LIBRESPOT_DEVICE satırı yorumlandı: {line.strip()}")
                         else:
                             new_lines.append(line) # Zaten yorumluysa elleme
                else:
                    # Diğer satırları olduğu gibi ekle (boş satırları koru)
                    new_lines.append(line)

            # Eğer LIBRESPOT_DEVICE satırı hiç bulunamadıysa sona ekle
            if not found_and_updated:
                logger.info(f"LIBRESPOT_DEVICE satırı dosyada bulunamadı, sona ekleniyor.")
                # Dosyanın sonunda zaten boş satır yoksa ekle
                if lines and not lines[-1].strip() == "":
                    new_lines.append("\n")
                new_lines.append("# Sound Device Selection (managed by web interface)\n")
                new_lines.append(config_line)

            # Yeni içeriği dosyaya yaz (sudo tee kullanarak)
            temp_config_content = "".join(new_lines)
            # tee komutu dosya yolunu tam olarak almalı
            tee_cmd = ['sudo', 'tee', RASPOTIFY_CONFIG_FILE]
            logger.info(f"Komut çalıştırılıyor: echo '...' | {' '.join(tee_cmd)}")
            try:
                process = subprocess.Popen(tee_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(input=temp_config_content, timeout=10) # Timeout eklendi

                if process.returncode != 0:
                     # stderr içinde 'Permission denied' varsa daha net hata ver
                     if 'permission denied' in stderr.lower():
                          logger.error(f"Raspotify yapılandırma dosyası yazılamadı ({RASPOTIFY_CONFIG_FILE}): İzin hatası. Flask uygulamasını çalıştıran kullanıcının sudo ile tee çalıştırma izni olduğundan veya dosya/dizin izinlerinin doğru olduğundan emin olun.")
                          return False, f"Yapılandırma dosyası yazılamadı: İzin Hatası. Sudo yapılandırmasını kontrol edin."
                     else:
                          logger.error(f"Raspotify yapılandırma dosyası yazılamadı ({RASPOTIFY_CONFIG_FILE}): {stderr}")
                          return False, f"Yapılandırma dosyası güncellenemedi: {stderr}"
            except subprocess.TimeoutExpired:
                 logger.error(f"Raspotify yapılandırma dosyası yazılırken zaman aşımı (sudo tee).")
                 return False, "Yapılandırma dosyası yazılırken zaman aşımı."
            except FileNotFoundError:
                 logger.error(f"Komut bulunamadı: 'sudo'. sudo yüklü mü ve PATH içinde mi?")
                 return False, "'sudo' komutu bulunamadı."


            logging.info(f"Yapılandırma dosyası başarıyla güncellendi: {RASPOTIFY_CONFIG_FILE}")

            # 2. Raspotify servisini yeniden başlat (sudo gerektirir!)
            restart_cmd = ['sudo', 'systemctl', 'restart', RASPOTIFY_SERVICE_NAME]
            logging.info(f"Komut çalıştırılıyor: {' '.join(restart_cmd)}")
            try:
                result = subprocess.run(restart_cmd, capture_output=True, text=True, check=True, timeout=20) # Timeout artırıldı
                logging.info(f"Raspotify servisi başarıyla yeniden başlatıldı.")
                time.sleep(3) # Servisin başlaması için biraz bekle
                return True, f"Raspotify çıkış cihazı {device_name} olarak ayarlandı ve servis yeniden başlatıldı."
            except FileNotFoundError:
                 logger.error(f"Komut bulunamadı: 'systemctl'. Sistem systemd kullanıyor mu?")
                 return False, "'systemctl' komutu bulunamadı."
            except subprocess.CalledProcessError as e:
                logger.error(f"Raspotify servisi yeniden başlatılamadı ({RASPOTIFY_SERVICE_NAME}): {e.stderr}")
                # Servis yoksa veya maskelenmişse farklı hata mesajı ver
                if 'not found' in e.stderr.lower():
                     return False, f"Raspotify servisi bulunamadı: {RASPOTIFY_SERVICE_NAME}. Servis adının doğru olduğundan emin olun."
                elif 'masked' in e.stderr.lower():
                     return False, f"Raspotify servisi maskelenmiş: {RASPOTIFY_SERVICE_NAME}. 'sudo systemctl unmask {RASPOTIFY_SERVICE_NAME}' komutunu deneyin."
                else:
                     return False, f"Raspotify servisi yeniden başlatılamadı: {e.stderr}"
            except subprocess.TimeoutExpired:
                 logger.error(f"Raspotify servisi yeniden başlatılırken zaman aşımı.")
                 return False, "Raspotify servisi yeniden başlatılırken zaman aşımı."

        except Exception as e:
            logger.error(f"Raspotify cihazı ayarlanırken hata: {str(e)}", exc_info=True)
            return False, f"Beklenmedik hata: {str(e)}"

    @staticmethod
    def scan_bluetooth_devices():
        """Kullanılabilir (bilinen) bluetooth cihazlarını listeler."""
        try:
            # Sadece bilinen (daha önce eşleşmiş veya güvenilmiş) cihazları listele
            result = subprocess.run(['bluetoothctl', 'devices'], capture_output=True, text=True, check=True, timeout=10)
            devices = []
            for line in result.stdout.splitlines():
                if line.startswith("Device"):
                    parts = line.strip().split(' ', 2)
                    if len(parts) >= 3:
                        # Cihazın bağlı olup olmadığını kontrol et
                        is_connected = False
                        try:
                             info_result = subprocess.run(['bluetoothctl', 'info', parts[1]], capture_output=True, text=True, timeout=5)
                             if info_result.returncode == 0 and 'Connected: yes' in info_result.stdout:
                                 is_connected = True
                        except Exception: pass # Hata olursa bağlı değil kabul et

                        device_data = {
                            'mac_address': parts[1],
                            'name': parts[2],
                            'type': 'bluetooth',
                            'connected': is_connected
                        }
                        devices.append(device_data)
            logger.info(f"Bluetooth cihazları listelendi: {len(devices)} adet")
            return devices
        except FileNotFoundError:
             logger.error("Komut bulunamadı: 'bluetoothctl'. Bluez yüklü mü?")
             return []
        except subprocess.CalledProcessError as e:
             logger.error(f"Bluetooth cihazları listelenirken hata: {e.stderr}")
             return []
        except subprocess.TimeoutExpired:
             logger.error(f"Bluetooth cihazları listelenirken zaman aşımı.")
             return []
        except Exception as e:
            logger.error(f"Bluetooth cihazları listelenirken genel hata: {e}", exc_info=True)
            return []

    @staticmethod
    def pair_bluetooth_device(mac_address):
        """Belirtilen MAC adresine sahip bluetooth cihazını eşleştirir ve bağlar."""
        try:
            logging.info(f"Bluetooth cihazı {mac_address} eşleştiriliyor/bağlanıyor...")

            # Önce bağlantıyı kesmeyi dene (zaten bağlıysa sorun çıkarabilir)
            try:
                subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=5)
            except Exception: pass

            # Güvenilir yap
            trust_cmd = subprocess.run(['bluetoothctl', 'trust', mac_address], capture_output=True, text=True, timeout=10)
            if trust_cmd.returncode != 0:
                 logging.warning(f"Cihaz güvenilir yapılamadı (zaten olabilir veya hata): {trust_cmd.stderr}")
                 # Güvenilir yapma hatası genellikle ciddi değildir, devam etmeyi deneyebiliriz.

            # Eşleştir (Pair) - PIN gerekebilir, bu kodda handle edilmiyor!
            # pair_cmd = subprocess.run(['bluetoothctl', 'pair', mac_address], capture_output=True, text=True, timeout=15)
            # if pair_cmd.returncode != 0:
            #     logging.warning(f"Cihaz eşleştirilemedi: {pair_cmd.stderr}")
            #     # Eşleştirme başarısız olursa bağlanmayı yine de deneyebiliriz.

            # Bağlan
            connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
            if connect_cmd.returncode == 0 and 'Connection successful' in connect_cmd.stdout.lower():
                logging.info(f"Bluetooth cihazı başarıyla bağlandı: {mac_address}")
                time.sleep(3) # Bluealsa'nın cihazı algılaması için bekle
                return True
            else:
                # Başarısız olursa tekrar dene
                logging.warning(f"İlk bağlantı denemesi başarısız ({mac_address}), tekrar deneniyor... Hata: {connect_cmd.stderr}")
                time.sleep(3)
                connect_cmd = subprocess.run(['bluetoothctl', 'connect', mac_address], capture_output=True, text=True, timeout=30)
                if connect_cmd.returncode == 0 and 'Connection successful' in connect_cmd.stdout.lower():
                     logging.info(f"Bluetooth cihazı ikinci denemede başarıyla bağlandı: {mac_address}")
                     time.sleep(3)
                     return True
                else:
                     logging.error(f"Bluetooth cihazı bağlantı hatası ({mac_address}): {connect_cmd.stderr}")
                     # Başarısızsa bağlantıyı kesmeyi dene
                     subprocess.run(['bluetoothctl', 'disconnect', mac_address], capture_output=True, text=True, timeout=10)
                     return False

        except FileNotFoundError:
             logger.error("Komut bulunamadı: 'bluetoothctl'. Bluez yüklü mü?")
             return False
        except subprocess.TimeoutExpired:
             logger.error(f"Bluetooth işlemi ({mac_address}) sırasında zaman aşımı.")
             return False
        except Exception as e:
            logger.error(f"Bluetooth cihazı eşleştirme/bağlama sırasında hata ({mac_address}): {e}", exc_info=True)
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
        except FileNotFoundError:
             logger.error("Komut bulunamadı: 'bluetoothctl'. Bluez yüklü mü?")
             return False
        except subprocess.CalledProcessError as e:
             logger.error(f"Bluetooth bağlantısını kesme hatası ({mac_address}): {e.stderr}")
             # Zaten bağlı değilse hata vermemesi lazım ama yine de kontrol edelim
             if 'not connected' in e.stderr.lower():
                  logging.info(f"Cihaz ({mac_address}) zaten bağlı değil.")
                  return True # Başarılı kabul edelim
             return False
        except subprocess.TimeoutExpired:
             logger.error(f"Bluetooth bağlantısını kesme ({mac_address}) sırasında zaman aşımı.")
             return False
        except Exception as e:
            logger.error(f"Bluetooth cihazı bağlantısını kesme sırasında hata ({mac_address}): {e}", exc_info=True)
            return False

# --- Flask Uygulaması ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar') # Ortam değişkeninden oku veya varsayılan kullan
app.jinja_env.globals['AudioManager'] = AudioManager # Template içinde kullanmak için

# Global Değişkenler
spotify_client = None
song_queue = []
user_requests = {} # Kullanıcı IP adreslerine göre istek sayısı (basit sınırlama)
# Zaman profilleri artık ses özellikleri yerine {id, artist_id, name, artist_name} tutacak
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] }
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
current_playback_data = None 

# --- Yardımcı Fonksiyonlar (Ayarlar, Token, Auth) ---

def load_settings():
    """Ayarları JSON dosyasından yükler veya varsayılanları oluşturur."""
    default_settings = {
        'max_queue_length': 20,
        'max_user_requests': 5, # Orijinal değer
        'active_device_id': None,
        'active_genres': ALLOWED_GENRES[:5] # Orijinal varsayılan
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                # Varsayılanları koruyarak yüklenenleri güncelle
                default_settings.update(loaded)
                logger.info(f"Ayarlar yüklendi: {SETTINGS_FILE}")
                return default_settings
        except json.JSONDecodeError:
             logger.error(f"Ayar dosyası ({SETTINGS_FILE}) bozuk, varsayılanlar kullanılıyor.")
             # Bozuksa varsayılanları oluştur
             pass
        except Exception as e:
             logger.error(f"Ayarları yüklerken hata: {e}", exc_info=True)

    # Dosya yoksa veya okuma hatası varsa varsayılanları kaydet
    logger.info(f"Varsayılan ayarlar kullanılıyor/oluşturuluyor: {SETTINGS_FILE}")
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(default_settings, f, indent=4)
        logger.info(f"Varsayılan ayarlar dosyası oluşturuldu/güncellendi: {SETTINGS_FILE}")
    except Exception as e:
         logger.error(f"Varsayılan ayar dosyası oluşturulurken/yazılırken hata: {e}", exc_info=True)
    return default_settings # Hata olsa bile varsayılanı döndür

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
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Token dosyası okuma hatası ({TOKEN_FILE}): {e}")
    return None

def save_token(token_info):
    """Spotify token'ını dosyaya kaydeder."""
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi.")
    except Exception as e:
        logger.error(f"Token kaydetme hatası: {e}")

def get_spotify_auth():
    """SpotifyOAuth nesnesini oluşturur."""
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_'):
         raise ValueError("Spotify Client ID ve Secret app.py içinde ayarlanmamış!")

    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        open_browser=False,
        cache_path=None
    )

def get_spotify_client():
    """Geçerli bir Spotify istemci nesnesi döndürür, gerekirse token yeniler."""
    global spotify_client
    token_info = load_token()

    if not token_info:
        return None

    try:
        auth_manager = get_spotify_auth()
    except ValueError as e:
        logger.error(e)
        return None

    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token süresi dolmuş, yenileniyor...")
            refresh_token_val = token_info.get('refresh_token')
            if not refresh_token_val:
                logger.error("Refresh token bulunamadı. Yeniden yetkilendirme gerekli.")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                return None

            new_token_info = auth_manager.refresh_access_token(refresh_token_val)
            if not new_token_info:
                logger.error("Token yenilenemedi. Refresh token geçersiz olabilir.")
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                spotify_client = None
                return None
            token_info = new_token_info
            save_token(token_info)

        # Yeni bir istemci oluştur
        new_spotify_client = spotipy.Spotify(auth=token_info.get('access_token'))

        # İstemciyi test et
        try:
            new_spotify_client.current_user()
            spotify_client = new_spotify_client
            # logger.info("Spotify istemcisi başarıyla alındı/güncellendi.") # Çok sık loglamamak için kapatılabilir
            return spotify_client
        except Exception as e:
            logger.error(f"Yeni Spotify istemcisi ile doğrulama hatası: {e}")
            if "invalid access token" in str(e).lower() or "token expired" in str(e).lower() or "unauthorized" in str(e).lower():
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            spotify_client = None
            return None

    except spotipy.SpotifyException as e:
        logger.error(f"Spotify API hatası (token işlemi sırasında): {e}")
        if e.http_status == 401 or e.http_status == 403:
             if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None
        return None
    except Exception as e:
        logger.error(f"Spotify token işlemi sırasında genel hata: {e}", exc_info=True)
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        spotify_client = None
        return None

# --- Admin Giriş Decorator'ı ---
def admin_login_required(f):
    """Admin girişi gerektiren rotalar için decorator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Zaman Profili ve Öneri Fonksiyonları (YENİ / GÜNCELLENMİŞ) ---
# Bu fonksiyonlar app_demo.py'den alındı ve buraya entegre edildi.
def get_current_time_profile():
    """Mevcut saate göre zaman dilimi adını döndürür."""
    hour = time.localtime().tm_hour
    if 6 <= hour < 12: return 'sabah'
    elif 12 <= hour < 18: return 'oglen'
    elif 18 <= hour < 24: return 'aksam'
    else: return 'gece'

# GÜNCELLENDİ: Ses özellikleri yerine temel bilgileri (ID, Artist ID) alıp kaydeder
def update_time_profile(track_id, spotify):
    """
    Eklenen şarkının temel bilgilerini alır ve ilgili zaman profiline kaydeder.
    Bu bilgiler daha sonra öneri yapmak için tohum olarak kullanılır.
    """
    if not spotify or not track_id:
        logger.warning("update_time_profile çağrıldı ancak spotify istemcisi veya track_id eksik.")
        return

    profile_name = get_current_time_profile()
    logger.debug(f"'{profile_name}' profili güncelleniyor, track_id: {track_id}")
    try:
        # Ses özellikleri yerine şarkı detaylarını al
        track_info = spotify.track(track_id, market='TR')
        if not track_info:
            logger.warning(f"Şarkı detayı alınamadı: {track_id}")
            return

        track_name = track_info.get('name', 'Bilinmeyen Şarkı')
        artists = track_info.get('artists')
        primary_artist_id = artists[0].get('id') if artists and artists[0].get('id') else None
        primary_artist_name = artists[0].get('name') if artists and artists[0].get('name') else 'Bilinmeyen Sanatçı'

        # Kaydedilecek bilgiyi oluştur
        profile_entry = {
            'id': track_id,
            'artist_id': primary_artist_id,
            'name': track_name,
            'artist_name': primary_artist_name # Sadece loglama/görüntüleme için
        }

        # Zaman profiline ekle ve limiti uygula (son 5 tohum bilgisi)
        time_profiles[profile_name].append(profile_entry)
        if len(time_profiles[profile_name]) > 5: # Son 5 bilgiyi tutalım
            time_profiles[profile_name] = time_profiles[profile_name][-5:]

        logger.info(f"'{profile_name}' profiline şarkı bilgisi eklendi: '{track_name}' (Artist ID: {primary_artist_id})")
        # logger.debug(f"'{profile_name}' profili güncel durumu: {time_profiles[profile_name]}")

    except spotipy.SpotifyException as e:
         # Track bilgisi alırken hata olursa logla
         logger.warning(f"'{profile_name}' profiline eklenirken şarkı bilgisi alınamadı (ID: {track_id}): {e}")
    except Exception as e:
        logger.error(f"'{profile_name}' profiline eklenirken genel hata (ID: {track_id}): {e}", exc_info=True)


# GÜNCELLENDİ: Ses özellikleri yerine tohum ID'leri (son şarkı/sanatçı) kullanarak öneri ister
def suggest_song_for_time(spotify):
    """
    Mevcut zaman profiline göre kaydedilmiş son şarkı/sanatçı ID'lerini kullanarak
    Spotify'dan şarkı önerisi ister.
    """
    if not spotify:
        logger.warning("suggest_song_for_time çağrıldı ancak spotify istemcisi eksik.")
        return None

    profile_name = get_current_time_profile()
    profile_data = time_profiles.get(profile_name, [])

    if not profile_data:
        # logger.info(f"'{profile_name}' profili öneri için boş.") # Çok sık loglamamak için kapatılabilir
        return None

    # Tohumları oluşturalım (profildeki son girdiden)
    seed_tracks = []
    seed_artists = []
    last_entry = profile_data[-1] # Profildeki son şarkı bilgisi

    # Geçerli ID'leri tohum listelerine ekle
    if last_entry.get('id'):
        seed_tracks.append(last_entry['id'])
    if last_entry.get('artist_id'):
        seed_artists.append(last_entry['artist_id'])

    # En az bir tohum olmalı.
    if not seed_tracks and not seed_artists:
        logger.warning(f"'{profile_name}' profilindeki son girdide öneri için geçerli tohum (şarkı/sanatçı ID) bulunamadı: {last_entry}")
        return None

    try:
        # target_* parametreleri olmadan recommendations çağır
        logger.info(f"'{profile_name}' için öneri isteniyor: seed_tracks={seed_tracks}, seed_artists={seed_artists}")
        recs = spotify.recommendations(
            seed_tracks=seed_tracks,
            seed_artists=seed_artists,
            # seed_genres=None, # İsteğe bağlı olarak aktif türler eklenebilir: settings.get('active_genres', [])
            limit=5, # Birkaç öneri alıp ilk uygun olanı seçelim
            market='TR'
        )

        if recs and recs.get('tracks'):
            # Önerilerden kuyrukta olmayan ilk şarkıyı seç
            for suggested_track in recs['tracks']:
                 is_in_queue = any(song.get('id') == suggested_track['id'] for song in song_queue)
                 if not is_in_queue:
                    track_name = suggested_track.get('name', 'Bilinmeyen Öneri')
                    track_id = suggested_track.get('id')
                    logger.info(f"'{profile_name}' için öneri bulundu: '{track_name}' ({track_id})")
                    # Öneri objesine 'artist' anahtarını ekleyelim (kuyrukta göstermek için)
                    artists = suggested_track.get('artists', [])
                    suggested_track['artist'] = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'
                    return suggested_track # Kuyrukta olmayan ilk öneriyi döndür

            logger.info(f"'{profile_name}' için öneriler alındı ama hepsi zaten kuyrukta.")
            return None
        else:
             logger.info(f"'{profile_name}' için Spotify'dan tohumlara dayalı öneri alınamadı.")
             return None

    except spotipy.SpotifyException as e:
         logger.warning(f"'{profile_name}' için öneri alınırken Spotify API hatası: {e}")
         if e.http_status == 401 or e.http_status == 403:
              global spotify_client
              spotify_client = None
              if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
         return None
    except Exception as e:
        logger.error(f"'{profile_name}' için öneri alınırken genel hata: {e}", exc_info=True)
        return None


# --- Flask Rotaları ---

@app.route('/')
def index():
    # Templates klasöründe index.html olmalı
    return render_template('index.html', allowed_genres=settings.get('active_genres', ALLOWED_GENRES))

@app.route('/admin')
def admin():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    # Templates klasöründe admin.html olmalı
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
    logger.info("Admin çıkışı yapıldı.")
    return redirect(url_for('admin'))


@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None # <<< YENİ: Başlangıçta None olarak ayarla

    # ALSA Cihazları (Orijinal koddan)
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
                 spotify_user = user.get('display_name')
                 session['spotify_user'] = spotify_user
            except Exception as user_err:
                logger.warning(f"Spotify kullanıcı bilgisi alınamadı: {user_err}")
                session.pop('spotify_user', None)

            # <<< START: Şu an çalan şarkıyı al >>>
            try:
                playback = spotify.current_playback(additional_types='track,episode', market='TR')
                if playback and playback.get('is_playing') and playback.get('item'):
                    item = playback['item']
                    track_name = item.get('name')
                    artists = item.get('artists', [])
                    artist_name = ', '.join([a.get('name') for a in artists if a.get('name')])
                    images = item.get('album', {}).get('images', [])
                    # Genellikle ilk resim en büyüğüdür, admin panelinde büyük kullanabiliriz
                    image_url = images[0].get('url') if images else None

                    currently_playing_info = {
                        'name': track_name,
                        'artist': artist_name,
                        'image_url': image_url
                    }
                    logger.debug(f"Şu An Çalıyor (Admin Panel): {track_name} - {artist_name}")
            except spotipy.SpotifyException as pb_err:
                 logger.warning(f"Admin paneli için çalma durumu alınamadı: {pb_err}")
                 # Token hatasıysa istemciyi sıfırla (zaten aşağıdaki ana try/except bloğu bunu yapabilir)
                 if pb_err.http_status == 401 or pb_err.http_status == 403:
                     global spotify_client
                     spotify_client = None
                     if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            except Exception as pb_err_general:
                logger.error(f"Admin paneli için çalma durumu alınırken genel hata: {pb_err_general}", exc_info=True)
            # <<< END: Şu an çalan şarkıyı al >>>


        except Exception as e:
            # ... (mevcut hata işleme kodunuz) ...
            logger.error(f"Spotify API hatası (Admin Panel Genel): {e}")
            # ... (mevcut hata işleme kodunuz - auth sıfırlama vb.) ...
            spotify_authenticated = False # Hata durumunda false yapalım
            session['spotify_authenticated'] = False
            session.pop('spotify_user', None)
            if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            # Global istemciyi burada da sıfırlamak iyi olabilir
            #global spotify_client
            spotify_client = None

    else:
         spotify_authenticated = False # İstemci alınamadıysa
         session['spotify_authenticated'] = False
         session.pop('spotify_user', None)


    # Orijinal admin_panel.html'i kullan ve yeni değişkeni ekle
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
        currently_playing_info=currently_playing_info # <<< YENİ: Template'e gönder
    )

@app.route('/refresh-devices')
@admin_login_required
def refresh_devices():
    """Spotify Connect cihaz listesini yeniler."""
    spotify = get_spotify_client()
    if not spotify:
        logger.warning("Cihazları yenilemek için Spotify yetkilendirmesi gerekli")
        # Flash message eklenebilir
        return redirect(url_for('admin_panel'))

    try:
        result = spotify.devices()
        devices = result.get('devices', [])
        logger.info(f"Spotify Connect Cihazları yenilendi: {len(devices)} cihaz bulundu")

        active_spotify_connect_device = settings.get('active_device_id')
        if active_spotify_connect_device:
            device_exists = any(d['id'] == active_spotify_connect_device for d in devices)
            if not device_exists:
                logger.warning(f"Ayarlarda kayıtlı aktif Spotify Connect cihazı ({active_spotify_connect_device}) artık mevcut değil. Ayar temizleniyor.")
                settings['active_device_id'] = None
                save_settings(settings)

    except Exception as e:
        logger.error(f"Spotify Connect Cihazlarını yenilerken hata: {e}")
        if "unauthorized" in str(e).lower() or "token" in str(e).lower() or isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
             logger.warning("Spotify yetkilendirmesi geçersiz, lütfen yeniden yetkilendirin.")
             # Flash message eklenebilir
             global spotify_client
             spotify_client = None
             if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)

    return redirect(url_for('admin_panel'))


@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    global settings # Global ayarlara erişim

    try:
        settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
        settings['max_user_requests'] = int(request.form.get('max_user_requests', 5))

        # Aktif Spotify Connect Cihazını Güncelle
        if 'active_device_id' in request.form:
             new_spotify_device_id = request.form.get('active_device_id')
             settings['active_device_id'] = new_spotify_device_id if new_spotify_device_id else None
             logger.info(f"Aktif Spotify Connect cihazı ayarlandı: {settings['active_device_id']}")

        # Aktif Müzik Türlerini Güncelle
        settings['active_genres'] = [genre for genre in ALLOWED_GENRES if request.form.get(f'genre_{genre}')]

        save_settings(settings)
        logger.info(f"Ayarlar güncellendi: {settings}")
    except ValueError:
         logger.error("Ayarları güncellerken geçersiz sayısal değer alındı.")
         # Kullanıcıya hata mesajı gösterilebilir (flash)
    except Exception as e:
         logger.error(f"Ayarları güncellerken hata: {e}", exc_info=True)
         # Kullanıcıya hata mesajı gösterilebilir (flash)

    return redirect(url_for('admin_panel'))

# --- Spotify Yetkilendirme Rotaları ---

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    """Kullanıcıyı Spotify yetkilendirme sayfasına yönlendirir."""
    if os.path.exists(TOKEN_FILE):
        logger.warning("Mevcut token varken yeniden yetkilendirme başlatılıyor.")
        # os.remove(TOKEN_FILE) # İsteğe bağlı: eski token'ı sil

    try:
        auth_manager = get_spotify_auth()
        auth_url = auth_manager.get_authorize_url()
        logger.info("Spotify yetkilendirme URL'sine yönlendiriliyor.")
        return redirect(auth_url)
    except ValueError as e:
        logger.error(f"Spotify yetkilendirme hatası: {e}")
        return f"Spotify Yetkilendirme Hatası: {e}", 500
    except Exception as e:
        logger.error(f"Spotify yetkilendirme URL'si alınırken hata: {e}", exc_info=True)
        # Kullanıcıya hata göster
        return "Spotify yetkilendirme başlatılamadı. Lütfen tekrar deneyin.", 500

@app.route('/callback')
def callback():
    """Spotify tarafından yetkilendirme sonrası geri çağrılan endpoint."""
    try:
        auth_manager = get_spotify_auth()
    except ValueError as e:
         logger.error(f"Callback hatası: {e}")
         return f"Callback Hatası: {e}", 500

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
        token_info = auth_manager.get_access_token(code, check_cache=False) # Cache kullanma
        if not token_info:
             logger.error("Spotify'dan geçerli token alınamadı.")
             return "Token alınamadı.", 500

        save_token(token_info)

        global spotify_client
        spotify_client = None # Force client refresh

        logger.info("Spotify yetkilendirme başarılı, token kaydedildi.")

        # Giriş yapmış admin ise panele, değilse ana sayfaya yönlendir
        if session.get('admin_logged_in'):
            return redirect(url_for('admin_panel'))
        else:
            # Yetkilendirme sonrası kullanıcıyı bilgilendiren bir sayfa daha iyi olabilir
            return redirect(url_for('index'))

    except Exception as e:
        logger.error(f"Spotify token alırken/kaydederken hata: {e}", exc_info=True)
        return "Token işlenirken bir hata oluştu.", 500

# --- Şarkı Arama ve Kuyruk Yönetimi Rotaları ---

@app.route('/search', methods=['POST'])
def search():
    """Kullanıcı arayüzünden gelen şarkı arama isteklerini işler."""
    search_query = request.form.get('search_query')
    # genre_filter = request.form.get('genre_filter') # Tür filtresi arama sorgusundan kaldırıldı
    logger.info(f"Arama isteği: Sorgu='{search_query}'")

    if not search_query:
        return jsonify({'error': 'Lütfen bir arama terimi girin.'}), 400
    # Aktif tür kontrolü kaldırıldı, çünkü arama sorgusunda kullanılmıyor artık.

    spotify = get_spotify_client()
    if not spotify:
        logger.error("Arama yapılamadı: Spotify istemcisi yok.")
        return jsonify({'error': 'Spotify bağlantısı şu anda mevcut değil. Lütfen daha sonra tekrar deneyin.'}), 503

    try:
        # Sadece sorgu ile arama yap, market=TR ekleyerek yerel sonuçları önceliklendir
        results = spotify.search(q=search_query, type='track', limit=10, market='TR')
        tracks = results.get('tracks', {}).get('items', [])
        logger.info(f"Arama sonucu: {len(tracks)} şarkı bulundu.")

        search_results = []
        for track in tracks:
            track_id = track.get('id')
            track_name = track.get('name')
            artists = track.get('artists', [])
            artist_name = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'
            album = track.get('album', {})
            album_name = album.get('name')
            images = album.get('images', [])
            image_url = images[-1].get('url') if images else None

            if track_id and track_name:
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
        return jsonify({'error': 'Arama sırasında bir sorun oluştu. Lütfen tekrar deneyin.'}), 500

@app.route('/add-song', methods=['POST'])
@admin_login_required
def add_song():
    """Admin panelinden ID veya URL ile şarkıyı kuyruğa ekler."""
    song_input = request.form.get('song_id', '').strip()
    if not song_input:
        # Flash message
        return redirect(url_for('admin_panel'))

    # Spotify URL'sinden ID çıkarma
    song_id = song_input
    if 'open.spotify.com/track/' in song_input:
        try:
            song_id = song_input.split('/track/')[1].split('?')[0]
        except IndexError:
            logger.warning(f"Geçersiz Spotify URL formatı: {song_input}")
            # Flash message
            return redirect(url_for('admin_panel'))

    if len(song_queue) >= settings.get('max_queue_length', 20):
        logger.warning(f"Kuyruk dolu, admin şarkı ekleyemedi: {song_id}")
        # Flash message
        return redirect(url_for('admin_panel'))

    spotify = get_spotify_client()
    if not spotify:
        logger.warning("Admin şarkı ekleme: Spotify yetkilendirmesi gerekli")
        # Flash message
        return redirect(url_for('spotify_auth'))

    try:
        song_info = spotify.track(song_id, market='TR')
        if not song_info:
             logger.warning(f"Admin şarkı ekleme: Şarkı bulunamadı ID={song_id}")
             # Flash message
             return redirect(url_for('admin_panel'))

        song_name = song_info.get('name', 'Bilinmeyen Şarkı')
        artists = song_info.get('artists')
        artist_name = ', '.join([a.get('name') for a in artists if a.get('name')]) if artists else 'Bilinmeyen Sanatçı'

        song_queue.append({
            'id': song_id,
            'name': song_name,
            'artist': artist_name,
            'added_by': 'admin',
            'added_at': time.time()
        })
        logger.info(f"Şarkı kuyruğa eklendi (Admin): {song_id} - {song_name}")
        # Admin ekleyince de profili GÜNCELLE (yeni fonksiyonu çağır)
        update_time_profile(song_id, spotify)

    except spotipy.SpotifyException as e:
        logger.error(f"Admin şarkı eklerken Spotify hatası (ID={song_id}): {e}")
        if e.http_status == 401 or e.http_status == 403:
            # Flash message
            return redirect(url_for('spotify_auth'))
        # Flash message (diğer hatalar için)
    except Exception as e:
        logger.error(f"Admin şarkı eklerken genel hata (ID={song_id}): {e}", exc_info=True)
        # Flash message

    return redirect(url_for('admin_panel'))

@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    """Kullanıcı arayüzünden şarkıyı kuyruğa ekleme isteğini işler."""
    if not request.is_json:
        return jsonify({'error': 'Geçersiz istek formatı.'}), 400

    data = request.get_json()
    track_id = data.get('track_id')
    logger.info(f"Kuyruğa ekleme isteği: track_id={track_id}")

    if not track_id:
        return jsonify({'error': 'Eksik şarkı IDsi.'}), 400

    if len(song_queue) >= settings.get('max_queue_length', 20):
        logger.warning("Kuyruk maksimum kapasitede.")
        return jsonify({'error': 'Şarkı kuyruğu şu anda dolu. Lütfen daha sonra deneyin.'}), 429

    user_ip = request.remote_addr
    max_requests = settings.get('max_user_requests', 5) # Ayarlardan gelen değeri kullan
    if user_requests.get(user_ip, 0) >= max_requests:
        logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip} ({max_requests} istek)")
        return jsonify({'error': f'Kısa süre içinde çok fazla istekte bulundunuz (Limit: {max_requests}).'}), 429

    spotify = get_spotify_client()
    if not spotify:
        logger.error("Kuyruğa eklenemedi: Spotify istemcisi yok.")
        return jsonify({'error': 'Spotify bağlantısı şu anda mevcut değil.'}), 503

    try:
        # Önce profili güncelle (track bilgisini almak için)
        update_time_profile(track_id, spotify)

        # Profildeki son eklenen şarkı bilgisini alarak kuyruğa ekleyelim
        profile_name = get_current_time_profile()
        # Profilin varlığını ve son elemanın ID'sinin eşleştiğini kontrol et
        if profile_name in time_profiles and time_profiles[profile_name] and time_profiles[profile_name][-1].get('id') == track_id:
            added_track_info = time_profiles[profile_name][-1]
            song_queue.append({
                'id': added_track_info['id'],
                'name': added_track_info['name'],
                'artist': added_track_info['artist_name'], # update_time_profile'dan gelen
                'added_by': user_ip,
                'added_at': time.time()
            })

            user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
            logger.info(f"Şarkı kuyruğa eklendi: {added_track_info['name']} - {added_track_info['artist_name']}. Kuyruk uzunluğu: {len(song_queue)}")
            return jsonify({'success': True, 'message': 'Şarkı başarıyla kuyruğa eklendi!'})
        else:
             # update_time_profile başarısız olduysa veya ID eşleşmiyorsa
             logger.error(f"Şarkı bilgisi profilden alınamadığı için kuyruğa eklenemedi: {track_id}")
             # Kullanıcıya daha genel bir hata verelim
             return jsonify({'error': 'Şarkı eklenirken bir sorun oluştu (profil güncellenemedi).'}), 500

    except Exception as e:
        logger.error(f"Kuyruğa ekleme sırasında hata (ID: {track_id}): {e}", exc_info=True)
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


# app.py içindeki view_queue fonksiyonu

# app.py içindeki view_queue fonksiyonu (DOĞRU HALİ)

@app.route('/queue')
def view_queue():
    global spotify_client # <<< DOĞRU YER BURASI (fonksiyonun ilk satırı)
    """Kullanıcıların mevcut şarkı kuyruğunu görmesi için sayfa."""
    current_q = list(song_queue)
    currently_playing_info = None # Initialize
    spotify = get_spotify_client()

    # --- START: Add current playback fetch ---
    if spotify:
        try:
            playback = spotify.current_playback(additional_types='track,episode', market='TR')
            if playback and playback.get('is_playing') and playback.get('item'):
                 # ... (Şarkı bilgilerini alma kodları - olduğu gibi kalabilir) ...
                item = playback['item']
                track_name = item.get('name')
                artists = item.get('artists', [])
                artist_name = ', '.join([a.get('name') for a in artists if a.get('name')])
                images = item.get('album', {}).get('images', [])
                image_url = images[-1].get('url') if images else None

                currently_playing_info = {
                    'name': track_name,
                    'artist': artist_name,
                    'image_url': image_url
                }
                logger.debug(f"Şu An Çalıyor (Kuyruk Sayfası): {currently_playing_info['name']} - {currently_playing_info['artist']}")
        except spotipy.SpotifyException as e:
            logger.warning(f"Çalma durumu alınırken hata (Kuyruk Sayfası): {e}")
            if e.http_status == 401 or e.http_status == 403:
                 # global spotify_client # <<< BURADAN SİLİNDİ/TAŞINDI
                 spotify_client = None # Artık global bildirimi yukarıda olduğu için bu satır sorun çıkarmaz
                 if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        except Exception as e:
            logger.error(f"Çalma durumu alınırken genel hata (Kuyruk Sayfası): {e}", exc_info=True)
    # --- END: Add current playback fetch ---

    return render_template(
        'queue.html',
        queue=current_q,
        currently_playing_info=currently_playing_info
    )

@app.route('/api/queue')
def api_get_queue():
    """API üzerinden mevcut kuyruk durumunu döndürür."""
    return jsonify({
        'queue': song_queue,
        'queue_length': len(song_queue),
        'max_length': settings.get('max_queue_length', 20)
    })

# --- ALSA/Bluetooth API Rotaları (Orijinal koddan) ---

@app.route('/api/output-devices')
@admin_login_required
def api_output_devices():
    """Mevcut ALSA çıkış cihazlarını döndürür."""
    devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    # is_default bilgisini tekrar kontrol et
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
            'devices': updated_devices # Güncel listeyi de gönderelim
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
    """Çevredeki (bilinen) Bluetooth cihazlarını listeler."""
    logger.info("API: Bluetooth cihaz listeleme isteği alındı.")
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

    # İşlem sonrası güncel ALSA listesini döndür (BT cihazı listede görünebilir)
    updated_alsa_devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    for device in updated_alsa_devices:
        device['is_default'] = (device['name'] == current_target_device)

    # Güncel BT listesini de döndür (bağlantı durumunu göstermek için)
    updated_bt_devices = AudioManager.scan_bluetooth_devices()

    message = f"Bluetooth cihazı bağlandı: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlanamadı."
    status_code = 200 if success else 500

    return jsonify({
        'success': success,
        'message': message,
        'alsa_devices': updated_alsa_devices, # ALSA listesini de gönderelim
        'bluetooth_devices': updated_bt_devices # Güncel BT durumunu da gönderelim
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

    # İşlem sonrası güncel ALSA listesini döndür (BT cihazı listeden kaybolabilir)
    updated_alsa_devices = AudioManager.get_output_devices()
    current_target_device = AudioManager.get_current_librespot_device()
    for device in updated_alsa_devices:
        device['is_default'] = (device['name'] == current_target_device)

    # Güncel BT listesini de döndür
    updated_bt_devices = AudioManager.scan_bluetooth_devices()

    message = f"Bluetooth cihazı bağlantısı kesildi: {mac_address}" if success else f"Bluetooth cihazı ({mac_address}) bağlantısı kesilemedi."
    status_code = 200 if success else 500

    return jsonify({
        'success': success,
        'message': message,
        'alsa_devices': updated_alsa_devices,
        'bluetooth_devices': updated_bt_devices
        }), status_code


# --- Arka Plan Şarkı Çalma İş Parçacığı ---
# Bu fonksiyon app_demo.py'deki güncellenmiş mantığı kullanır.
def background_queue_player():
    """
    Arka planda şarkı kuyruğunu kontrol eder, çalar ve kuyruk boşsa
    yeni öneri mekanizmasını kullanarak şarkı eklemeye çalışır.
    """
    global spotify_client # Global istemciye erişim
    global song_queue # Kuyruğa erişim
    global user_requests # İstek limitlerini azaltmak için

    logger.info("Arka plan şarkı çalma/öneri görevi başlatılıyor...")
    last_played_song_id = None # Son çalınan ID (tekrar çalmayı önlemek için)
    last_suggested_song_id = None # Son önerilen ID (kuyruğa ekleme tekrarını önlemek için)

    while True:
        try:
            # Her döngüde güncel istemciyi ve ayarları al
            spotify = get_spotify_client()
            # Ayarları her döngüde tekrar okumak yerine global 'settings' kullanabiliriz
            # Ancak dosya dışarıdan değişirse diye okumak daha güvenli olabilir. Şimdilik global kullanalım.
            active_spotify_connect_device_id = settings.get('active_device_id')

            # Spotify bağlantısı veya aktif cihaz yoksa bekle
            if not spotify or not active_spotify_connect_device_id:
                time.sleep(10)
                continue

            # --- Çalma Durumunu Kontrol Et ---
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

            is_playing = current_playback and current_playback.get('is_playing', False)
            current_track_info = current_playback.get('item') if current_playback else None
            current_track_id = current_track_info.get('id') if current_track_info else None

            # --- Kuyruk ve Öneri Mantığı ---

            # 1. Çalma yok ve kuyrukta şarkı VARSA -> Sıradakini çal
            if not is_playing and song_queue:
                next_song = song_queue.pop(0)
                if next_song.get('id') == last_played_song_id:
                    logger.debug(f"Şarkı zaten son çalınandı, atlanıyor: {next_song.get('name')}")
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

                except spotipy.SpotifyException as start_err:
                    logger.error(f"Arka plan: Şarkı çalma başlatılamadı ({next_song.get('id')}): {start_err}")
                    song_queue.insert(0, next_song)
                    if start_err.http_status == 401 or start_err.http_status == 403:
                         spotify_client = None
                         if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                    # 404 (Device not found) durumunda aktif cihazı temizle?
                    elif start_err.http_status == 404 and 'device_id' in str(start_err).lower():
                         logger.warning(f"Aktif Spotify Connect cihazı ({active_spotify_connect_device_id}) bulunamadı. Ayar temizleniyor.")
                         settings['active_device_id'] = None
                         save_settings(settings) # Ayarı kaydet
                    time.sleep(5)
                except Exception as start_err:
                     logger.error(f"Arka plan: Şarkı çalma başlatılırken genel hata ({next_song.get('id')}): {start_err}", exc_info=True)
                     song_queue.insert(0, next_song)
                     time.sleep(10)

            # 2. Çalma yok ve kuyruk BOŞSA -> Öneri yapmayı dene
            elif not is_playing and not song_queue:
                suggested = suggest_song_for_time(spotify) # YENİ öneri fonksiyonunu çağır
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
                else:
                     pass # Öneri yoksa veya tekrar ediyorsa bekle

            # 3. Çalma VARSA -> Son çalınan ID'yi güncelle (eğer değiştiyse)
            elif is_playing:
                 if current_track_id and current_track_id != last_played_song_id:
                    last_played_song_id = current_track_id
                    last_suggested_song_id = None

            # Normal bekleme süresi
            time.sleep(5) # Kontrol sıklığı (5sn)

        except Exception as loop_err:
            logger.error(f"Arka plan döngüsünde beklenmedik hata: {loop_err}", exc_info=True)
            logger.error(traceback.format_exc())
            time.sleep(15) # Büyük hatalarda daha uzun bekle


def start_queue_player():
    """Arka plan görevini başlatır."""
    thread = threading.Thread(target=background_queue_player, name="QueuePlayerThread", daemon=True)
    thread.start()
    logger.info("Arka plan şarkı çalma/öneri görevi başlatıldı.")

# --- Uygulama Başlangıcı ---
def check_token_on_startup():
    """Uygulama başlarken token durumunu kontrol eder ve loglar."""
    logger.info("Başlangıçta Spotify token kontrol ediliyor...")
    client = get_spotify_client()
    if client:
         logger.info("Başlangıçta Spotify istemcisi başarıyla alındı.")
    else:
         logger.warning("Başlangıçta Spotify istemcisi alınamadı. Admin panelinden yetkilendirme gerekli olabilir.")

if __name__ == '__main__':
    logger.info("=================================================")
    logger.info("       Mekan Müzik Uygulaması Başlatılıyor       ")
    logger.info("      (Güncellenmiş Öneri Mantığı)             ")
    logger.info("=================================================")
    # Ayarlar zaten global olarak yüklendi, burada tekrar yüklemeye gerek yok.
    # settings = load_settings() # <-- BU SATIR KALDIRILDI (NameError'a neden oluyordu)
    logger.info(f"Ayarlar Yüklendi: {SETTINGS_FILE}")
    logger.info(f"Raspotify Servisi: {RASPOTIFY_SERVICE_NAME}")
    logger.info(f"Raspotify Config: {RASPOTIFY_CONFIG_FILE}")

    # API Bilgileri kontrolü
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID.startswith('SENİN_') or \
       not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET.startswith('SENİN_') or \
       not SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI.startswith('http://YOUR_'):
        logger.error("LÜTFEN app.py dosyasında Spotify API bilgilerinizi (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) doğru şekilde ayarlayın!")
        # Uygulamayı çalıştırmadan çıkmak daha iyi olabilir
        # exit(1)
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

    # Uygulamayı başlat
    # Production ortamında debug=False kullanın!
    # SSL kullanmak için: app.run(ssl_context='adhoc', host='0.0.0.0', port=port, debug=False)
    # (pip install pyopenssl gerektirir)
    app.run(host='0.0.0.0', port=port, debug=True) # debug=True geliştirme için
