import os
import json
import subprocess
import time
import logging
import signal
import threading

# Loglama yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Token bilgisini saklayan dosya (mevcut kodunuzdaki dosya)
TOKEN_FILE = 'spotify_token.json'

# Librespot yapılandırma dosyası
LIBRESPOT_CONFIG_DIR = os.path.expanduser('~/.config/librespot')
LIBRESPOT_CONFIG_FILE = os.path.join(LIBRESPOT_CONFIG_DIR, 'config.toml')

# Librespot'un çalıştırılabilir dosya yolu
LIBRESPOT_BINARY = '/usr/bin/librespot'

# Global değişkenler
librespot_process = None
token_refresh_thread = None
stop_refresh_thread = threading.Event()

def load_token():
    """Token bilgisini dosyadan yükle"""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Token dosyasını okuma hatası: {e}")
    return None

def create_librespot_config(token_info):
    """Librespot için config.toml dosyası oluştur"""
    if not os.path.exists(LIBRESPOT_CONFIG_DIR):
        os.makedirs(LIBRESPOT_CONFIG_DIR)
    
    # Librespot yapılandırma içeriği
    config_content = f"""[player]
autoplay = true
bitrate = 320
initial_volume = 80
volume_normalisation = false

[audio]
backend = "alsa"
device = "default"
format = "S16"
volume_controller = "alsa"

[connect]
name = "RaspberryPi Speaker"

[session]
device_id = "{token_info.get('device_id', 'raspberry_pi_speaker')}"
access_token = "{token_info.get('access_token')}"
"""

    try:
        with open(LIBRESPOT_CONFIG_FILE, 'w') as f:
            f.write(config_content)
        logger.info(f"Librespot yapılandırma dosyası oluşturuldu: {LIBRESPOT_CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Librespot yapılandırma dosyası oluşturma hatası: {e}")
        return False

def start_librespot():
    """Librespot servisini başlat"""
    global librespot_process
    
    # Eğer zaten çalışıyorsa durdur
    stop_librespot()
    
    token_info = load_token()
    if not token_info or 'access_token' not in token_info:
        logger.error("Token bilgisi bulunamadı veya geçersiz")
        return False
    
    # Librespot yapılandırma dosyasını oluştur
    if not create_librespot_config(token_info):
        return False
    
    try:
        # Librespot'u başlat
        cmd = [
            LIBRESPOT_BINARY,
            "--config-file", LIBRESPOT_CONFIG_FILE,
            "--enable-volume-normalisation",
            "--verbose"
        ]
        
        logger.info(f"Librespot başlatılıyor: {' '.join(cmd)}")
        librespot_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Çıktıları kontrol et
        if librespot_process.poll() is not None:
            out, err = librespot_process.communicate()
            logger.error(f"Librespot başlatılamadı:\nstdout: {out}\nstderr: {err}")
            return False
        
        logger.info("Librespot başarıyla başlatıldı")
        return True
    except Exception as e:
        logger.error(f"Librespot başlatma hatası: {e}")
        return False

def stop_librespot():
    """Librespot servisini durdur"""
    global librespot_process
    if librespot_process:
        try:
            logger.info("Librespot durduruluyor...")
            librespot_process.send_signal(signal.SIGTERM)
            librespot_process.wait(timeout=5)
            logger.info("Librespot durduruldu")
        except subprocess.TimeoutExpired:
            logger.warning("Librespot normal şekilde kapanmadı, zorla sonlandırılıyor")
            librespot_process.kill()
        except Exception as e:
            logger.error(f"Librespot durdurma hatası: {e}")
        finally:
            librespot_process = None

def token_refresh_loop():
    """Tokeni düzenli olarak yenile"""
    while not stop_refresh_thread.is_set():
        token_info = load_token()
        if token_info and 'access_token' in token_info:
            # Her token değiştiğinde Librespot yapılandırmasını güncelle
            if create_librespot_config(token_info):
                logger.info("Token güncellendi, Librespot yeniden başlatılıyor")
                restart_librespot()
        time.sleep(300)  # 5 dakikada bir kontrol et

def restart_librespot():
    """Librespot'u yeniden başlat"""
    stop_librespot()
    time.sleep(2)
    start_librespot()

def check_librespot_installed():
    """Librespot'un kurulu olup olmadığını kontrol et"""
    try:
        subprocess.run([LIBRESPOT_BINARY, "--version"], 
                      stdout=subprocess.PIPE, 
                      stderr=subprocess.PIPE, 
                      check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.error("Librespot kurulu değil!")
        return False

def install_librespot():
    """Librespot'u kur"""
    try:
        logger.info("Librespot kuruluyor...")
        
        # Gerekli paketleri kur
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "install", "-y", 
                       "build-essential", "pkg-config", "libasound2-dev", 
                       "libssl-dev", "libpulse-dev"], check=True)
        
        # Rust kurulumunu kontrol et
        try:
            subprocess.run(["cargo", "--version"], stdout=subprocess.PIPE, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.info("Rust kuruluyor...")
            subprocess.run(["curl", "--proto", "=https", "--tlsv1.2", "-sSf", 
                           "https://sh.rustup.rs", "-o", "rustup.sh"], check=True)
            subprocess.run(["chmod", "+x", "rustup.sh"], check=True)
            subprocess.run(["./rustup.sh", "-y"], check=True)
            os.environ["PATH"] = f"{os.path.expanduser('~/.cargo/bin')}:{os.environ['PATH']}"
        
        # Librespot'u kurulum için indir ve derle
        if not os.path.exists("librespot"):
            subprocess.run(["git", "clone", "https://github.com/librespot-org/librespot.git"], check=True)
        
        os.chdir("librespot")
        subprocess.run(["cargo", "build", "--release", "--no-default-features", 
                       "--features", "alsa-backend"], check=True)
        
        # Derlenmiş dosyayı doğru konuma kopyala
        subprocess.run(["sudo", "cp", "target/release/librespot", LIBRESPOT_BINARY], check=True)
        
        logger.info("Librespot başarıyla kuruldu")
        return True
    except Exception as e:
        logger.error(f"Librespot kurulum hatası: {e}")
        return False

def main():
    """Ana fonksiyon"""
    global token_refresh_thread
    
    logger.info("Raspberry Pi Spotify Speaker başlatılıyor...")
    
    # Librespot kurulu mu kontrol et
    if not check_librespot_installed():
        logger.info("Librespot kurulu değil, kurulum başlatılıyor...")
        if not install_librespot():
            logger.error("Librespot kurulumu başarısız oldu, çıkılıyor.")
            return
    
    # Token'ı kontrol et
    token_info = load_token()
    if not token_info:
        logger.error("Token bilgisi bulunamadı. Lütfen önce Spotify yetkilendirmesini yapın.")
        return
    
    # Librespot'u başlat
    if not start_librespot():
        logger.error("Librespot başlatılamadı, çıkılıyor.")
        return
    
    # Token yenileme işlemleri için arka plan görevi başlat
    stop_refresh_thread.clear()
    token_refresh_thread = threading.Thread(target=token_refresh_loop)
    token_refresh_thread.daemon = True
    token_refresh_thread.start()
    
    try:
        # Ana program döngüsü
        logger.info("Raspberry Pi Spotify Speaker çalışıyor. Durdurmak için CTRL+C tuşlarına basın.")
        while True:
            time.sleep(1)
            
            # Librespot'un hala çalışıp çalışmadığını kontrol et
            if librespot_process and librespot_process.poll() is not None:
                logger.warning("Librespot çöktü, yeniden başlatılıyor...")
                start_librespot()
                
    except KeyboardInterrupt:
        logger.info("Program durduruluyor...")
    finally:
        # Temizlik işlemleri
        stop_refresh_thread.set()
        if token_refresh_thread:
            token_refresh_thread.join(timeout=2)
        stop_librespot()
        logger.info("Program durduruldu.")

if __name__ == "__main__":
    main()