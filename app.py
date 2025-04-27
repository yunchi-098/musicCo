# -*- coding: utf-8 -*-
import os
import json
import threading
import time
import logging
import re # Gerekli olabilir (örn. Spotify URL parse)
import subprocess # spotifyd ve bluetoothctl için hala gerekli
from functools import wraps
# flash mesajları için import
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import traceback # Hata ayıklama için eklendi
import pulsectl # Yeni eklenen kütüphane

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

# --- Yardımcı Fonksiyon: Komut Çalıştırma (bluetoothctl ve spotifyd için) ---
def _run_command(command, timeout=10):
    """Helper function to run shell commands."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
        logger.debug(f"Command '{' '.join(command)}' succeeded. Output:\n{result.stdout[:200]}...") # Log success and partial output
        return True, result.stdout, result.stderr
    except FileNotFoundError:
        logger.error(f"Command not found: {command[0]}. Is it installed and in PATH?")
        return False, "", f"Command not found: {command[0]}"
    except subprocess.CalledProcessError as e:
        logger.error(f"Command '{' '.join(command)}' failed with return code {e.returncode}. Stderr:\n{e.stderr}")
        return False, e.stdout, e.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Command '{' '.join(command)}' timed out after {timeout} seconds.")
        return False, "", f"Command timed out after {timeout} seconds."
    except Exception as e:
        logger.error(f"Error running command '{' '.join(command)}': {e}", exc_info=True)
        return False, "", f"Unexpected error: {e}"

# --- Yeni AudioSinkManager Sınıfı (ex.py'den uyarlandı) ---
class AudioSinkManager:
    """PulseAudio/PipeWire sink'lerini pulsectl kullanarak yönetir."""

    def __init__(self, app_name='MekanMuzikYonetim'):
        self.app_name = app_name
        self._pulse = None # Bağlantıyı yönetmek için

    def _get_pulse_client(self):
        """PulseAudio/PipeWire bağlantısını alır veya oluşturur."""
        # Bu fonksiyon doğrudan route içinde çağrılacak (with bloğu ile)
        # Böylece her istekte yeni bir bağlantı kurulur ve kapatılır.
        # Veya uzun süreli bir bağlantı yönetimi yapılabilir, ancak bu daha karmaşık olabilir.
        # Şimdilik 'with' bloğunu tercih edelim.
        # Örnek: with pulsectl.Pulse(self.app_name) as pulse: ...
        # Bu nedenle bu _get_pulse_client fonksiyonu aslında gereksiz.
        pass

    def list_sinks(self):
        """Tüm mevcut ses çıkış cihazlarını (sink) listeler ve durumu döndürür."""
        sinks_info = []
        default_sink_name = None
        try:
            with pulsectl.Pulse(self.app_name + '-sink-list') as pulse:
                raw_sinks = pulse.sink_list()
                server_info = pulse.server_info()
                default_sink_name = server_info.default_sink_name

                if not raw_sinks:
                    logger.info("Hiç ses çıkış cihazı (sink) bulunamadı.")
                    return [], None # Boş liste ve varsayılan yok

                logger.debug(f"Found {len(raw_sinks)} sinks. Default: {default_sink_name}")

                for sink in raw_sinks:
                    is_default = sink.name == default_sink_name
                    # pulsectl sink objesini doğrudan JSON'a çeviremeyiz, dict oluşturalım
                    sinks_info.append({
                        'index': sink.index,
                        'name': sink.name,
                        'description': sink.description,
                        'state': str(sink.state), # Enum'ı string'e çevir
                        'mute': sink.mute,
                        'volume': round(sink.volume.value_flat * 100), # Yüzde olarak al
                        'is_default': is_default,
                        # 'properties': sink.proplist # Çok fazla veri, genellikle gereksiz
                    })
                logger.info(f"Listed {len(sinks_info)} sinks. Default sink name: {default_sink_name}")
                return sinks_info, default_sink_name # Liste ve varsayılan sink'in ADI döndürülüyor

        except pulsectl.PulseError as e:
             logger.error(f"PulseAudio/PipeWire bağlantı hatası (list_sinks): {e}", exc_info=True)
             # Belki PipeWire/PulseAudio çalışmıyordur?
             return [], None # Hata durumunda boş liste
        except Exception as e:
            logger.error(f"Ses cihazları listelenirken genel hata oluştu: {e}", exc_info=True)
            return [], None # Hata durumunda boş liste

    def switch_to_sink(self, sink_identifier):
        """Belirtilen sink'e (index veya isim ile) geçiş yapar."""
        target_sink = None
        try:
            with pulsectl.Pulse(self.app_name + '-sink-switcher') as pulse:
                sinks = pulse.sink_list()
                if not sinks:
                     logger.error("Sink değiştirilemiyor, hiç sink bulunamadı.")
                     return False, "Hiç ses çıkış cihazı bulunamadı."

                # Hedef sink'i bul
                if isinstance(sink_identifier, int) or sink_identifier.isdigit():
                    # Eğer index olarak verilmişse
                    try:
                        sink_index = int(sink_identifier)
                        target_sink = pulse.sink_info(sink_index) # Index ile doğrudan al
                        if not target_sink:
                             raise ValueError # Bulunamazsa hata ver
                    except (ValueError, pulsectl.PulseError):
                         logger.error(f"Geçersiz veya bulunamayan sink indeksi: {sink_identifier}")
                         return False, f"Geçersiz veya bulunamayan sink indeksi: {sink_identifier}"
                else:
                    # Eğer isim veya açıklama olarak verilmişse
                    found = False
                    for s in sinks:
                        # Hem isme hem açıklamaya bakalım (küçük/büyük harf duyarsız)
                        if sink_identifier.lower() in s.name.lower() or sink_identifier.lower() in s.description.lower():
                            target_sink = s # Eşleşen sink objesini al
                            found = True
                            break
                    if not found:
                        logger.error(f"'{sink_identifier}' isimli/açıklamalı sink bulunamadı!")
                        return False, f"'{sink_identifier}' isimli/açıklamalı sink bulunamadı!"

                if not target_sink: # Ekstra kontrol
                     logger.error(f"Hedef sink belirlenemedi: {sink_identifier}")
                     return False, f"Hedef sink belirlenemedi: {sink_identifier}"

                logger.info(f"Varsayılan sink '{target_sink.description}' (Index: {target_sink.index}) olarak ayarlanıyor...")

                # Varsayılan sink'i değiştir
                pulse.default_set(target_sink)

                # İsteğe bağlı: Tüm mevcut stream'leri yeni sink'e taşıma
                # Bu bazen istenmeyebilir, kullanıcı sadece yeni uygulamaların yeni sink'e gitmesini isteyebilir.
                # Şimdilik bu kısmı kapalı tutalım. Gerekirse açılabilir.
                # try:
                #    logger.info(f"Mevcut ses akışları '{target_sink.description}' hedefine taşınıyor...")
                #    for stream in pulse.sink_input_list():
                #        pulse.sink_input_move(stream.index, target_sink.index)
                #    logger.info("Akışlar taşındı.")
                # except Exception as move_err:
                #      logger.warning(f"Akışlar taşınırken hata oluştu (genellikle kritik değil): {move_err}")

                logger.info(f"Varsayılan ses çıkışı '{target_sink.description}' olarak başarıyla ayarlandı.")
                return True, f"Varsayılan ses çıkışı '{target_sink.description}' olarak ayarlandı."

        except pulsectl.PulseError as e:
             logger.error(f"PulseAudio/PipeWire bağlantı hatası (switch_to_sink): {e}", exc_info=True)
             return False, f"Ses sunucusuna bağlanılamadı: {e}"
        except Exception as e:
            logger.error(f"Sink değiştirilirken genel hata oluştu: {e}", exc_info=True)
            return False, f"Sink değiştirilirken hata: {e}"

    def find_sink_by_device_name(self, device_name):
        """Cihaz adına göre ilgili sink'i bulur (Bluetooth bağlantısı sonrası kullanılabilir)."""
        try:
            with pulsectl.Pulse(self.app_name + '-device-finder') as pulse:
                sinks = pulse.sink_list()
                if not sinks: return None
                # Cihaz adının sink adı veya açıklamasında geçip geçmediğini kontrol et
                # Bluetooth cihazları genellikle 'bluez_sink.' ile başlar
                search_term = device_name.lower()
                bluez_search_term = f"bluez_sink.{device_name.replace(':', '_').lower()}" # MAC adresinden türetilen isim

                for sink in sinks:
                    name_lower = sink.name.lower()
                    desc_lower = sink.description.lower()
                    if search_term in name_lower or \
                       search_term in desc_lower or \
                       bluez_search_term in name_lower:
                        logger.info(f"'{device_name}' için eşleşen sink bulundu: {sink.description} (Index: {sink.index})")
                        # Eşleşen sink'in dict temsilini döndürelim
                        return {
                            'index': sink.index,
                            'name': sink.name,
                            'description': sink.description,
                            'state': str(sink.state),
                            'is_default': sink.name == pulse.server_info().default_sink_name
                        }
                logger.warning(f"'{device_name}' için eşleşen sink bulunamadı.")
                return None
        except pulsectl.PulseError as e:
             logger.error(f"PulseAudio/PipeWire bağlantı hatası (find_sink_by_device_name): {e}", exc_info=True)
             return None
        except Exception as e:
            logger.error(f"Cihaz için sink aranırken genel hata: {e}", exc_info=True)
            return None

# --- Bluetooth Yönetim Fonksiyonları (Eski AudioManager'dan alındı, _run_command kullanıyor) ---
def bt_get_paired_bluetooth_devices():
    """Sadece eşleştirilmiş Bluetooth cihazlarını listeler."""
    devices = []
    logger.debug("Attempting to list paired Bluetooth devices using 'bluetoothctl paired-devices'...")
    success_paired, stdout_paired, stderr_paired = _run_command(['bluetoothctl', 'paired-devices'], timeout=10)
    if not success_paired:
         logger.error(f"Error listing paired Bluetooth devices. Stderr: {stderr_paired}")
         return []

    paired_macs = set()
    for line in stdout_paired.splitlines():
        if line.strip().startswith("Device"):
            parts = line.strip().split(' ', 2)
            if len(parts) >= 2:
                paired_macs.add(parts[1]) # MAC adresi ikinci eleman

    logger.debug(f"Found {len(paired_macs)} paired MAC addresses: {paired_macs}")

    for mac_address in paired_macs:
        is_connected = False
        alias = mac_address # Default name
        logger.debug(f"Getting info for paired device {mac_address}...")
        success_info, stdout_info, stderr_info = _run_command(['bluetoothctl', 'info', mac_address], timeout=5)
        if success_info:
            if 'Connected: yes' in stdout_info: is_connected = True
            alias_match = re.search(r'Alias:\s*(.*)', stdout_info)
            if alias_match: alias = alias_match.group(1).strip()
            name_match = re.search(r'Name:\s*(.*)', stdout_info) # Fallback to Name if Alias fails
            if not alias_match and name_match: alias = name_match.group(1).strip()
            logger.debug(f"Info for {mac_address}: Name='{alias}', Connected={is_connected}")
        else:
             logger.warning(f"Could not get info for paired device {mac_address}. Stderr: {stderr_info}")

        devices.append({
            'mac_address': mac_address,
            'name': alias,
            'type': 'bluetooth', # Frontend'in beklemediği bir alan olabilir, kontrol et
            'connected': is_connected,
            'paired': True
        })
    logger.info(f"Listed paired Bluetooth devices: {len(devices)}")
    return devices

def bt_discover_bluetooth_devices(scan_duration=BLUETOOTH_SCAN_DURATION):
    """Kısa süreliğine Bluetooth taraması yapar ve bulunan tüm cihazları listeler."""
    logger.info(f"Starting Bluetooth discovery for {scan_duration} seconds...")
    scan_process = None
    discovered_devices = {} # Use dict to avoid duplicates by MAC

    try:
        logger.debug("Running 'bluetoothctl scan on'...")
        scan_process = subprocess.Popen(['bluetoothctl', 'scan', 'on'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) # Capture stderr
        time.sleep(scan_duration)
        logger.debug("Scan duration finished.")
    except Exception as e:
        logger.error(f"Failed to start Bluetooth scan: {e}")
    finally:
        if scan_process:
            logger.debug("Terminating bluetoothctl scan process...")
            try:
                scan_process.terminate()
                _, stderr_scan = scan_process.communicate(timeout=2)
                if scan_process.returncode != 0 and stderr_scan:
                     logger.warning(f"Error output during scan termination: {stderr_scan.decode(errors='ignore')}")
            except subprocess.TimeoutExpired:
                logger.warning("Scan process termination timed out, killing.")
                scan_process.kill()
            except Exception as term_err:
                 logger.error(f"Error during scan process termination: {term_err}")

        logger.debug("Running 'bluetoothctl scan off'...")
        off_success, _, off_stderr = _run_command(['bluetoothctl', 'scan', 'off'], timeout=5)
        if not off_success: logger.warning(f"Could not turn off Bluetooth scan explicitly. Stderr: {off_stderr}")

    logger.info("Bluetooth discovery finished. Fetching device list...")

    logger.debug("Running 'bluetoothctl devices'...")
    success_devs, stdout_devs, stderr_devs = _run_command(['bluetoothctl', 'devices'], timeout=10)
    if not success_devs:
        logger.error(f"Error listing discovered Bluetooth devices. Stderr: {stderr_devs}")
        return []

    logger.debug("Running 'bluetoothctl paired-devices' again to mark discovered devices...")
    success_paired, stdout_paired, stderr_paired = _run_command(['bluetoothctl', 'paired-devices'], timeout=10)
    paired_macs = set()
    if success_paired:
        for line in stdout_paired.splitlines():
            if line.strip().startswith("Device"):
                parts = line.strip().split(' ', 2)
                if len(parts) >= 2: paired_macs.add(parts[1])
    else:
        logger.warning(f"Could not get paired devices list while processing discovered devices. Stderr: {stderr_paired}")

    for line in stdout_devs.splitlines():
        if line.strip().startswith("Device"):
            parts = line.strip().split(' ', 2)
            if len(parts) >= 3:
                mac_address = parts[1]
                device_name = parts[2]
                is_paired = mac_address in paired_macs
                is_connected = False

                if is_paired:
                    logger.debug(f"Getting info for discovered paired device {mac_address}...")
                    success_info, stdout_info, stderr_info = _run_command(['bluetoothctl', 'info', mac_address], timeout=3)
                    if success_info:
                         if 'Connected: yes' in stdout_info:
                             is_connected = True
                         alias_match = re.search(r'Alias:\s*(.*)', stdout_info)
                         if alias_match: device_name = alias_match.group(1).strip()
                         logger.debug(f"Info for discovered {mac_address}: Name='{device_name}', Connected={is_connected}")
                    else:
                         logger.warning(f"Could not get info for discovered paired device {mac_address}. Stderr: {stderr_info}")

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

def bt_pair_bluetooth_device(mac_address):
    """Belirtilen MAC adresine sahip bluetooth cihazını eşleştirir ve bağlar."""
    try:
        logging.info(f"Pairing/Connecting Bluetooth device {mac_address}...")
        logging.debug(f"Attempting to disconnect {mac_address} before pairing...")
        _run_command(['bluetoothctl', 'disconnect', mac_address], timeout=5)
        time.sleep(1)

        logger.info(f"Attempting to pair with {mac_address}...")
        success_pair, _, stderr_pair = _run_command(['bluetoothctl', 'pair', mac_address], timeout=20)
        if not success_pair and "already exists" not in stderr_pair.lower():
            logger.error(f"Pairing failed for {mac_address}. Stderr: {stderr_pair}")
        else:
             logger.info(f"Pairing successful or device already paired: {mac_address}")

        logger.info(f"Attempting to trust {mac_address}...")
        success_trust, _, stderr_trust = _run_command(['bluetoothctl', 'trust', mac_address], timeout=10)
        if not success_trust:
             logging.warning(f"Could not trust device {mac_address} (might be already trusted). Stderr: {stderr_trust}")
        else: logger.info(f"Device trusted: {mac_address}")

        logger.info(f"Attempting to connect to {mac_address} (Attempt 1)...")
        success_conn1, stdout_conn1, stderr_conn1 = _run_command(['bluetoothctl', 'connect', mac_address], timeout=30)
        if success_conn1 and ('Connection successful' in stdout_conn1.lower() or 'already connected' in stderr_conn1.lower()):
            logging.info(f"Bluetooth device successfully connected: {mac_address}"); time.sleep(3); return True, f"Bluetooth cihazı '{mac_address}' başarıyla bağlandı."
        else:
            logging.warning(f"First connection attempt failed for {mac_address}. Stderr: {stderr_conn1}. Retrying...")
            time.sleep(3)
            logger.info(f"Attempting to connect to {mac_address} (Attempt 2)...")
            success_conn2, stdout_conn2, stderr_conn2 = _run_command(['bluetoothctl', 'connect', mac_address], timeout=30)
            if success_conn2 and ('Connection successful' in stdout_conn2.lower() or 'already connected' in stderr_conn2.lower()):
                 logging.info(f"Bluetooth device successfully connected on second attempt: {mac_address}"); time.sleep(3); return True, f"Bluetooth cihazı '{mac_address}' başarıyla bağlandı (2. deneme)."
            else:
                 logging.error(f"Bluetooth device connection failed on second attempt for {mac_address}. Stderr: {stderr_conn2}")
                 _run_command(['bluetoothctl', 'disconnect', mac_address], timeout=10)
                 return False, f"Bluetooth cihazı '{mac_address}' bağlanamadı. Cihazın açık ve eşleşme modunda olduğundan emin olun. Hata: {stderr_conn2}"
    except Exception as e:
        logger.error(f"Unexpected error during Bluetooth pairing/connection ({mac_address}): {e}", exc_info=True);
        return False, f"Bluetooth işlemi sırasında beklenmedik hata: {e}"

def bt_disconnect_bluetooth_device(mac_address):
    """Belirtilen MAC adresine sahip bluetooth cihazının bağlantısını keser."""
    try:
        logging.info(f"Disconnecting Bluetooth device {mac_address}...")
        success, _, stderr = _run_command(['bluetoothctl', 'disconnect', mac_address], timeout=10)
        if success:
            logging.info(f"Bluetooth device successfully disconnected: {mac_address}"); time.sleep(2); return True, f"Bluetooth cihazı '{mac_address}' bağlantısı kesildi."
        else:
            if 'not connected' in stderr.lower():
                logging.info(f"Device ({mac_address}) was already disconnected."); return True, f"Bluetooth cihazı '{mac_address}' zaten bağlı değildi."
            else:
                logger.error(f"Failed to disconnect {mac_address}. Stderr: {stderr}")
                return False, f"Bluetooth cihazı '{mac_address}' bağlantısı kesilemedi. Hata: {stderr}"
    except Exception as e:
         logger.error(f"Unexpected error during Bluetooth disconnection ({mac_address}): {e}", exc_info=True); return False, f"Bluetooth bağlantısı kesilirken beklenmedik hata: {e}"

# --- Spotifyd ve ALSA Yardımcı Fonksiyonları (ex.py'den uyarlandı) ---
def get_spotifyd_pid():
    """Çalışan spotifyd süreçlerinin PID'sini bulur."""
    try:
        # universal_newlines=True is deprecated, use text=True
        output = subprocess.check_output(["pgrep", "spotifyd"], text=True)
        pids = output.strip().split("\n")
        logger.debug(f"Found spotifyd PIDs: {pids}")
        return pids
    except subprocess.CalledProcessError:
        logger.info("No running spotifyd process found.")
        return []
    except FileNotFoundError:
        logger.error("Command 'pgrep' not found.")
        return []
    except Exception as e:
        logger.error(f"Error getting spotifyd PID: {e}", exc_info=True)
        return []

def restart_spotifyd():
    """Spotifyd servisini yeniden başlatır."""
    logger.info("Attempting to restart spotifyd...")
    pids = get_spotifyd_pid()
    killed_pids = []
    start_success = False
    messages = []

    # Terminate existing processes
    if pids:
        for pid in pids:
            try:
                pid_int = int(pid)
                os.kill(pid_int, 15)  # SIGTERM
                killed_pids.append(pid)
                logger.info(f"Sent SIGTERM to spotifyd (PID: {pid}). Waiting briefly...")
                messages.append(f"Çalışan Spotifyd (PID: {pid}) sonlandırıldı.")
                time.sleep(1)
            except ValueError:
                 logger.warning(f"Invalid PID found: {pid}")
                 messages.append(f"Geçersiz PID bulundu: {pid}")
            except ProcessLookupError:
                logger.info(f"Spotifyd (PID: {pid}) already terminated.")
            except Exception as e:
                logger.error(f"Error terminating spotifyd (PID: {pid}): {e}", exc_info=True)
                messages.append(f"Spotifyd (PID: {pid}) sonlandırılırken hata: {e}")
    else:
         messages.append("Çalışan Spotifyd süreci bulunamadı.")

    # Start new process
    spotifyd_command = None
    # Kullanıcı ve sistem config yollarını kontrol et
    spotifyd_config_path_home = os.path.expanduser("~/.config/spotifyd/spotifyd.conf")
    spotifyd_config_path_etc = "/etc/spotifyd.conf"

    if os.path.exists(spotifyd_config_path_home):
        spotifyd_command = ["spotifyd", "--config-path", spotifyd_config_path_home, "--no-daemon"]
        logger.info(f"Using spotifyd config: {spotifyd_config_path_home}")
    elif os.path.exists(spotifyd_config_path_etc):
         spotifyd_command = ["spotifyd", "--config-path", spotifyd_config_path_etc, "--no-daemon"]
         logger.info(f"Using spotifyd config: {spotifyd_config_path_etc}")
    else:
        spotifyd_command = ["spotifyd", "--no-daemon"]
        logger.info("No spotifyd config file found, attempting to start with defaults.")

    if spotifyd_command:
        try:
            subprocess.Popen(spotifyd_command)
            time.sleep(2) # Başlaması için bekle
            new_pids = get_spotifyd_pid()
            if new_pids and any(pid not in killed_pids for pid in new_pids):
                logger.info(f"Spotifyd restarted successfully. New PIDs: {new_pids}")
                messages.append("Spotifyd başarıyla yeniden başlatıldı.")
                start_success = True
            else:
                 # Başlamadıysa veya sadece eski PID'ler varsa
                 if not new_pids:
                     logger.error("Spotifyd process did not start after attempting restart.")
                     messages.append("Spotifyd başarıyla sonlandırıldı ancak yeniden başlatılamadı.")
                 else:
                      logger.warning(f"Spotifyd restart seemed to fail, only old PIDs found? PIDs: {new_pids}")
                      messages.append("Spotifyd yeniden başlatma durumu belirsiz, yeni süreç bulunamadı.")
                 start_success = False

        except FileNotFoundError:
            logger.error("Command 'spotifyd' not found. Is spotifyd installed and in PATH?")
            messages.append("Hata: 'spotifyd' komutu bulunamadı. Yüklü mü?")
            start_success = False
        except Exception as e:
            logger.error(f"Error starting spotifyd: {e}", exc_info=True)
            messages.append(f"Spotifyd başlatılırken hata: {e}")
            start_success = False
    else:
         messages.append("Spotifyd başlatılamadı (komut oluşturulamadı).")
         start_success = False

    return start_success, " ".join(messages)


def switch_to_alsa_sink(audio_manager):
    """Varsa ilk bulunan ALSA uyumlu sink'e geçiş yapar."""
    logger.info("Attempting to switch to an ALSA sink...")
    sinks, default_sink_name = audio_manager.list_sinks() # list_sinks artık tuple döndürüyor
    alsa_sinks = []

    if not sinks:
        logger.warning("No audio sinks found.")
        return False, "Hiç ses çıkış cihazı bulunamadı."

    # ALSA sink'lerini bul (isim veya açıklamada 'alsa', 'analog', 'builtin' geçenler)
    for sink in sinks:
        name_lower = sink.get('name', '').lower()
        desc_lower = sink.get('description', '').lower()
        if "alsa" in name_lower or "analog" in name_lower or "builtin" in desc_lower:
             # Bluetooth olmayanları tercih et
             if "bluez" not in name_lower:
                 alsa_sinks.append(sink)

    if not alsa_sinks:
        logger.warning("No suitable ALSA compatible sinks found.")
        return False, "Uygun ALSA ses çıkış cihazı bulunamadı."

    # Tercihen varsayılan olmayan ilk ALSA sink'ini seç
    target_sink = None
    for sink in alsa_sinks:
        if not sink.get('is_default'):
            target_sink = sink
            break
    # Hepsi varsayılan ise (veya tek ALSA varsa), ilkini seç
    if not target_sink:
        target_sink = alsa_sinks[0]

    target_sink_name = target_sink.get('name')
    target_sink_desc = target_sink.get('description')
    target_sink_index = target_sink.get('index') # Index'i de alalım

    if target_sink.get('is_default'):
        logger.info(f"ALSA sink '{target_sink_desc}' is already the default.")
        return True, f"ALSA ses çıkışı ('{target_sink_desc}') zaten varsayılan."

    logger.info(f"Found ALSA sink to switch to: {target_sink_desc} (Index: {target_sink_index})")

    # Seçilen ALSA sink'ini varsayılan yap (index ile çağıralım)
    success, message = audio_manager.switch_to_sink(target_sink_index)

    if success:
         return True, f"ALSA ses çıkışına geçildi: {message}"
    else:
         return False, f"ALSA ses çıkışına geçiş yapılamadı: {message}"

# --- Flask Uygulaması ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_guvensiz_anahtar_lutfen_degistirin')
# AudioManager yerine AudioSinkManager'ı Jinja'ya eklemeye gerek yok, API üzerinden yönetilecek.
# app.jinja_env.globals['AudioManager'] = AudioManager # KALDIRILDI
app.jinja_env.globals['BLUETOOTH_SCAN_DURATION'] = BLUETOOTH_SCAN_DURATION

# --- Global Değişkenler ---
spotify_client = None
song_queue = []
user_requests = {}
time_profiles = { 'sabah': [], 'oglen': [], 'aksam': [], 'gece': [] }
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']
auto_advance_enabled = True
audio_sink_manager = AudioSinkManager() # Yeni ses yöneticisini başlat

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
    global auto_advance_enabled, audio_sink_manager
    spotify = get_spotify_client()
    spotify_devices = []
    spotify_authenticated = False
    spotify_user = None
    currently_playing_info = None

    # PipeWire/PulseAudio sink'lerini ve varsayılanı al (yeni yönetici ile)
    # list_sinks artık (liste, varsayılan_adı) döndürüyor
    audio_sinks, default_audio_sink_name = audio_sink_manager.list_sinks()

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

    # Şablona gönderilecek verileri güncelle
    return render_template(
        'admin_panel.html',
        settings=settings,
        spotify_devices=spotify_devices,
        queue=song_queue,
        all_genres=ALLOWED_GENRES,
        spotify_authenticated=spotify_authenticated,
        spotify_user=session.get('spotify_user'),
        active_spotify_connect_device_id=settings.get('active_device_id'),
        # PipeWire yerine genel audio sink listesi ve varsayılan adı gönder
        audio_sinks=audio_sinks, # Yeni anahtar adı
        default_audio_sink_name=default_audio_sink_name, # Yeni anahtar adı
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
        if e.http_status == 401 or e.http_status == 403: flash('Spotify yetkilendirme hatası.', 'danger');
        global spotify_client;
        spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
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
        if e.http_status == 401 or e.http_status == 403: flash('Spotify yetkilendirme hatası.', 'danger');
        global spotify_client;
        spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
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
        if isinstance(e, spotipy.SpotifyException) and (e.http_status == 401 or e.http_status == 403):
            global spotify_client;
            spotify_client = None;
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
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
    if 'https://developer.spotify.com/documentation/web-api/reference/add-to-queue2' in song_input or 'open.spotify.com/track/' in song_input:
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
        song_info = spotify.track(track_id, market='TR')
        if not song_info:
            logger.warning(f"Kullanıcı ekleme: Şarkı bulunamadı ID={track_id}")
            return jsonify({'error': f"Şarkı bulunamadı (ID: {track_id})."}), 404

        artists = song_info.get('artists', [])
        artist_name = ', '.join([a.get('name') for a in artists]) if artists else '?'
        song_name = song_info.get('name', '?')
        update_time_profile(track_id, spotify)
        song_queue.append({'id': track_id, 'name': song_name, 'artist': artist_name, 'added_by': user_ip, 'added_at': time.time()})
        user_requests[user_ip] = user_requests.get(user_ip, 0) + 1
        logger.info(f"Şarkı eklendi (Kullanıcı: {user_ip}): {song_name}. Kuyruk: {len(song_queue)}")
        return jsonify({'success': True, 'message': f"'{song_name}' kuyruğa eklendi!"})

    except spotipy.SpotifyException as e:
        logger.error(f"Kullanıcı eklerken Spotify hatası (ID={track_id}): {e}")
        if e.http_status == 401 or e.http_status == 403: return jsonify({'error': 'Spotify yetkilendirme sorunu.'}), 503
        else: return jsonify({'error': f"Spotify hatası: {e.msg}"}), 500
    except Exception as e:
        logger.error(f"Kuyruğa ekleme hatası (ID: {track_id}): {e}", exc_info=True)
        return jsonify({'error': 'Şarkı eklenirken bilinmeyen bir sorun oluştu.'}), 500

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
            if e.http_status == 401 or e.http_status == 403:
                spotify_client = None;
                if os.path.exists(TOKEN_FILE):
                    os.remove(TOKEN_FILE)
        except Exception as e: logger.error(f"Çalma durumu genel hatası (Kuyruk): {e}", exc_info=True)
    return render_template('queue.html', queue=current_q, currently_playing_info=currently_playing_info)

@app.route('/api/queue')
def api_get_queue():
    return jsonify({'queue': song_queue, 'queue_length': len(song_queue), 'max_length': settings.get('max_queue_length', 20)})

# --- YENİ API Rotaları (Ses/Bluetooth) ---

@app.route('/api/audio-sinks') # URL güncellendi
@admin_login_required
def api_audio_sinks():
    """Mevcut ses sink'lerini (pulsectl) ve varsayılanı döndürür."""
    global audio_sink_manager
    sinks, default_sink_name = audio_sink_manager.list_sinks()
    # Frontend'in beklemesi muhtemel anahtarları kullanalım
    return jsonify({'sinks': sinks, 'default_sink_name': default_sink_name})

@app.route('/api/set-audio-sink', methods=['POST']) # URL ve parametre güncellendi
@admin_login_required
def api_set_audio_sink():
    """Seçilen sink'i (index veya isim) varsayılan yapar."""
    global audio_sink_manager
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json()
    sink_identifier = data.get('sink_identifier') # Frontend'den gelen index veya isim
    if sink_identifier is None: # None veya boş string kontrolü
        logger.error("API isteğinde 'sink_identifier' eksik.")
        return jsonify({'success': False, 'error': 'Sink tanımlayıcısı (index veya isim) gerekli'}), 400

    logger.info(f"API: Varsayılan ses sink ayarlama isteği: {sink_identifier}")
    success, message = audio_sink_manager.switch_to_sink(sink_identifier)

    # İşlem sonrası güncel listeleri al
    updated_sinks, new_default_sink_name = audio_sink_manager.list_sinks()
    updated_bt_devices = bt_get_paired_bluetooth_devices() # Eşleşmiş BT listesi
    status_code = 200 if success else 500
    response_data = {
        'success': success,
        'sinks': updated_sinks, # Frontend'in beklemesi muhtemel anahtar
        'default_sink_name': new_default_sink_name, # Frontend'in beklemesi muhtemel anahtar
        'bluetooth_devices': updated_bt_devices
    }
    if success: response_data['message'] = message
    else: response_data['error'] = message
    return jsonify(response_data), status_code

@app.route('/api/scan-bluetooth') # Eşleşmişleri listeler
@admin_login_required
def api_scan_bluetooth():
    """Eşleştirilmiş Bluetooth cihazlarını ve durumlarını listeler."""
    logger.info("API: Eşleştirilmiş Bluetooth cihaz listeleme isteği alındı.")
    devices = bt_get_paired_bluetooth_devices()
    return jsonify({'success': True, 'devices': devices})

@app.route('/api/discover-bluetooth') # Yeni cihazları tarar
@admin_login_required
def api_discover_bluetooth():
    """Kısa süreliğine Bluetooth taraması yapar ve bulunan tüm cihazları listeler."""
    logger.info(f"API: Yeni Bluetooth cihaz keşfi isteği alındı (Süre: {BLUETOOTH_SCAN_DURATION}s).")
    devices = bt_discover_bluetooth_devices(scan_duration=BLUETOOTH_SCAN_DURATION)
    return jsonify({'success': True, 'devices': devices})


@app.route('/api/pair-bluetooth', methods=['POST'])
@admin_login_required
def api_pair_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazını eşleştirir/bağlar."""
    global audio_sink_manager
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
    logger.info(f"API: Bluetooth cihazı eşleştirme/bağlama isteği: {mac_address}")
    success, message = bt_pair_bluetooth_device(mac_address)

    # Bağlantı başarılıysa, ilgili sink'i bul ve varsayılan yapmayı dene
    if success:
        time.sleep(3) # Sink'in görünmesi için biraz bekle
        device_info = next((d for d in bt_get_paired_bluetooth_devices() if d['mac_address'] == mac_address), None)
        if device_info:
            target_sink = audio_sink_manager.find_sink_by_device_name(device_info['name']) # Cihaz adına göre ara
            if target_sink and target_sink.get('index') is not None:
                 logger.info(f"Bluetooth cihazı için sink bulundu: {target_sink.get('description')}. Varsayılan yapılıyor...")
                 sink_success, sink_msg = audio_sink_manager.switch_to_sink(target_sink['index'])
                 if sink_success:
                     message += f" {sink_msg}"
                 else:
                      message += f" Ses çıkışı otomatik olarak ayarlanamadı: {sink_msg}"
            else:
                  message += " Eşleşen ses çıkışı bulunamadı veya otomatik ayarlanamadı."
        else:
             message += " Cihaz bilgisi alınamadı, ses çıkışı ayarlanamadı."


    # İşlem sonrası güncel listeleri al
    updated_sinks, new_default_sink_name = audio_sink_manager.list_sinks()
    updated_bt_devices = bt_get_paired_bluetooth_devices()
    status_code = 200 if success else 500

    return jsonify({
        'success': success,
        'message': message,
        'sinks': updated_sinks,
        'default_sink_name': new_default_sink_name,
        'bluetooth_devices': updated_bt_devices
    }), status_code

@app.route('/api/disconnect-bluetooth', methods=['POST'])
@admin_login_required
def api_disconnect_bluetooth():
    """Belirtilen MAC adresli Bluetooth cihazının bağlantısını keser."""
    global audio_sink_manager
    if not request.is_json: return jsonify({'success': False, 'error': 'JSON isteği gerekli'}), 400
    data = request.get_json(); mac_address = data.get('mac_address')
    if not mac_address: return jsonify({'success': False, 'error': 'MAC adresi gerekli'}), 400
    logger.info(f"API: Bluetooth cihazı bağlantısını kesme isteği: {mac_address}")
    success, message = bt_disconnect_bluetooth_device(mac_address)

    # Otomatik ALSA geçişi yok, kullanıcı manuel yapacak.

    # İşlem sonrası güncel listeleri al
    updated_sinks, new_default_sink_name = audio_sink_manager.list_sinks()
    updated_bt_devices = bt_get_paired_bluetooth_devices()
    status_code = 200 if success else 500

    return jsonify({
        'success': success,
        'message': message,
        'sinks': updated_sinks,
        'default_sink_name': new_default_sink_name,
        'bluetooth_devices': updated_bt_devices
    }), status_code

@app.route('/api/switch-to-alsa', methods=['POST'])
@admin_login_required
def api_switch_to_alsa():
    """Varsayılan ses çıkışını uygun bir ALSA cihazına değiştirir."""
    global audio_sink_manager
    logger.info("API: ALSA ses çıkışına geçiş isteği alındı.")
    success, message = switch_to_alsa_sink(audio_sink_manager) # audio_manager örneğini ver

    # İşlem sonrası güncel listeleri al
    updated_sinks, new_default_sink_name = audio_sink_manager.list_sinks()
    updated_bt_devices = bt_get_paired_bluetooth_devices()
    status_code = 200 if success else 500

    response_data = {
        'success': success,
        'sinks': updated_sinks,
        'default_sink_name': new_default_sink_name,
        'bluetooth_devices': updated_bt_devices
    }
    if success: response_data['message'] = message
    else: response_data['error'] = message
    return jsonify(response_data), status_code

@app.route('/api/restart-spotifyd', methods=['POST'])
@admin_login_required
def api_restart_spotifyd():
    """Spotifyd servisini yeniden başlatır."""
    global audio_sink_manager # Listeleri almak için gerekebilir
    logger.info("API: Spotifyd yeniden başlatma isteği alındı.")
    success, message = restart_spotifyd()
    status_code = 200 if success else 500

    # Yeniden başlatma sonrası listeleri güncellemek genellikle gerekli olmaz,
    # ancak yine de tutarlılık için gönderilebilir.
    updated_sinks, new_default_sink_name = audio_sink_manager.list_sinks()
    updated_bt_devices = bt_get_paired_bluetooth_devices()

    response_data = {
        'success': success,
        'sinks': updated_sinks,
        'default_sink_name': new_default_sink_name,
        'bluetooth_devices': updated_bt_devices
    }
    if success: response_data['message'] = message
    else: response_data['error'] = message

    return jsonify(response_data), status_code


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
                if pb_err.http_status == 401 or pb_err.http_status == 403:
                    spotify_client = None;
                if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
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
                    if start_err.http_status == 401 or start_err.http_status == 403:
                        spotify_client = None;
                        if os.path.exists(TOKEN_FILE):
                            os.remove(TOKEN_FILE)
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

    # PulseAudio/PipeWire bağlantı kontrolü (isteğe bağlı)
    try:
        with pulsectl.Pulse('startup-check') as pulse:
             server_info = pulse.server_info()
             logger.info(f"PulseAudio/PipeWire sunucusuna bağlanıldı: {server_info.server_name} v{server_info.server_version}")
    except Exception as pulse_err:
         logger.warning(f"Başlangıçta PulseAudio/PipeWire sunucusuna bağlanılamadı: {pulse_err}. Ses yönetimi özellikleri çalışmayabilir.")


    # Başlangıç kontrolleri ve arka plan görevini başlatma
    check_token_on_startup()
    start_queue_player()

    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Uygulama arayüzüne http://<SUNUCU_IP>:{port} adresinden erişilebilir.")
    logger.info(f"Admin paneline http://<SUNUCU_IP>:{port}/admin adresinden erişilebilir.")

    # debug=True otomatik yeniden yüklemeyi sağlar
    # use_reloader=False development sırasında bazen çift thread başlatma sorununu önler
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)

