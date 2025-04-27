#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
<<<<<<< HEAD
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
=======
import subprocess
import threading
import pulsectl
import dbus
import logging
from dbus.mainloop.glib import DBusGMainLoop
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from gi.repository import GLib # deneme.py'den eklendi
from functools import wraps # admin_login_required için
from datetime import timedelta # Session timeout için eklendi
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

# --- Logging Ayarları ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log", encoding='utf-8'), # Logları dosyaya yaz (UTF-8 ile)
        logging.StreamHandler() # Logları konsola da yaz
    ]
)
log = logging.getLogger(__name__)

# --- Yardımcı Fonksiyonlar ---

def get_spotifyd_pids():
    """Çalışan spotifyd süreçlerinin PID'lerini bulur."""
    try:
        output = subprocess.check_output(["pgrep", "-x", "spotifyd"], universal_newlines=True) # Tam eşleşme için -x
        return [int(pid) for pid in output.strip().split("\n") if pid.isdigit()]
    except subprocess.CalledProcessError:
        return [] # Süreç bulunamadı
    except Exception as e:
        log.error(f"Spotifyd PID'leri alınırken hata: {e}")
        return []

<<<<<<< HEAD
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
=======
def restart_spotifyd():
    """Spotifyd'yi daha güvenilir bir şekilde yeniden başlatır."""
    log.info("Spotifyd yeniden başlatılıyor...")
    pids = get_spotifyd_pids()
    if pids:
        for pid in pids:
            try:
                os.kill(pid, 15) # SIGTERM
                log.info(f"Spotifyd (PID: {pid}) sonlandırıldı (SIGTERM).")
                time.sleep(0.5) # Kısa bekleme
            except ProcessLookupError:
                 log.warning(f"Spotifyd (PID: {pid}) sonlandırılırken bulunamadı.")
            except Exception as e:
                log.error(f"Spotifyd (PID: {pid}) sonlandırılırken hata: {e}")
        time.sleep(1) # Tüm işlemlerin bitmesini bekle

    # Spotifyd'yi yeniden başlatmayı dene
    try:
        config_path = os.path.expanduser("~/.config/spotifyd/spotifyd.conf")
        command = ["spotifyd"]
        if os.path.exists(config_path):
            command.extend(["--config-path", config_path])
            log.info(f"Spotifyd belirtilen yapılandırma ile başlatılıyor: {config_path}")
        else:
            log.info("Spotifyd varsayılan ayarlarla başlatılıyor.")

        # Arka planda çalıştırmak için Popen kullan, ancak stdout/stderr'i logla (opsiyonel)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        log.info(f"Spotifyd başlatıldı (PID: {process.pid}).")
        # Başlatma sonrası kısa bir bekleme
        time.sleep(2)
        # Spotifyd'nin çalışıp çalışmadığını kontrol et (opsiyonel)
        if not get_spotifyd_pids():
             log.error("Spotifyd başlatıldı ancak PID bulunamadı. Başlatma başarısız olmuş olabilir.")
             stderr_output = process.stderr.read() if process.stderr else "Stderr okunamadı"
             log.error(f"Spotifyd stderr: {stderr_output}")
             return False
        return True
    except FileNotFoundError:
        log.error("spotifyd komutu bulunamadı. PATH ortam değişkeninizi kontrol edin veya spotifyd'yi kurun.")
        return False
    except Exception as e:
        log.error(f"Spotifyd yeniden başlatılırken hata: {e}")
        return False

# --- Bluetooth ve Sink Yöneticileri ---

# DBus ana döngüsünü global olarak ayarla (uygulama başlangıcında bir kez)
# Bu, Flask'ın multithreading/multiprocessing modelleriyle sorun yaratabilir.
# Alternatif: Her istekte DBus bağlantısını aç/kapat (daha az verimli ama daha güvenli olabilir).
# Şimdilik global ayarlamayı deneyelim.
try:
    DBusGMainLoop(set_as_default=True)
    log.info("DBus GMainLoop varsayılan olarak ayarlandı.")
except ImportError:
    log.error("python-dbus veya dbus-python kütüphanesi eksik veya GLib desteği yok.")
    # Uygulamanın devam etmesini engellemek yerine uyarı verilebilir.
except Exception as e:
    log.error(f"DBus GMainLoop ayarlanamadı: {e}")


class BluetoothManager:
    """Bluetooth cihazlarını yönetmek için sınıf."""
    def __init__(self):
        self.bus = None
        self.adapter_path = None
        self.adapter = None
        self.adapter_props = None
        self.device_list_cache = [] # Cihaz listesi için basit önbellek
        self.last_scan_time = 0
        self.scan_interval = 10 # Saniye cinsinden minimum tarama aralığı
        log.debug("BluetoothManager örneği oluşturuluyor.")
        self._connect_dbus()

    def _connect_dbus(self):
        """DBus bağlantısını kurar."""
        if self.bus: # Zaten bağlıysa tekrar bağlanma
             return True
        try:
            self.bus = dbus.SystemBus()
            log.info("DBus bağlantısı kuruldu.")

            om = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = om.GetManagedObjects()
            self.adapter_path = next((path for path, interfaces in objects.items() if 'org.bluez.Adapter1' in interfaces), None)

            if not self.adapter_path:
                 log.error("Bluez adaptörü bulunamadı.")
                 self._cleanup() # Bağlantıyı düzgün kapat
                 return False

            log.info(f"Kullanılan Bluetooth Adaptörü: {self.adapter_path}")
            adapter_obj = self.bus.get_object('org.bluez', self.adapter_path)
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
            return True

        except dbus.exceptions.DBusException as e:
            log.error(f"DBus bağlantı hatası: {e}. Bluetooth servisi çalışıyor mu?")
            self._cleanup()
            return False
        except Exception as e:
             log.error(f"BluetoothManager DBus bağlantısı sırasında genel hata: {e}")
             self._cleanup()
             return False

    def _cleanup(self):
        """DBus bağlantısını ve kaynakları temizler."""
        log.debug("BluetoothManager kaynakları temizleniyor.")
        # DBus bağlantısını kapatmak genellikle gerekli değildir veya önerilmez,
        # ancak nesne referanslarını temizlemek iyi bir pratiktir.
        self.adapter = None
        self.adapter_props = None
        self.bus = None # Bağlantıyı kapatmaz, sadece referansı kaldırır
        self.adapter_path = None
        self.device_list_cache = []
        log.info("BluetoothManager kaynak referansları temizlendi.")

    def is_adapter_available(self):
        """Adaptörün kullanılabilir olup olmadığını kontrol eder."""
        # Bağlantıyı kontrol et ve gerekirse yeniden bağlanmayı dene
        if not self.bus or not self.adapter:
            log.warning("Adaptör mevcut değil, DBus'a yeniden bağlanmayı deniyor...")
            if not self._connect_dbus():
                return False # Yeniden bağlanma başarısız oldu
        # Bağlantı varsa adaptörün var olduğunu varsayabiliriz
        return self.adapter is not None

    def start_discovery(self, duration=5):
        """Bluetooth cihaz keşfini başlatır."""
        if not self.is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, tarama başlatılamıyor.")
             return []
        try:
            self.adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
            log.info("Bluetooth adaptörü açıldı (veya zaten açıktı).")

            if not self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                log.info(f"Bluetooth cihaz taraması {duration} saniye için başlatılıyor...")
                self.adapter.StartDiscovery()
            else:
                log.info("Bluetooth cihaz taraması zaten aktif.")

            # Flask içinde bloklamayan bir bekleme ideal olurdu, ancak şimdilik time.sleep
            time.sleep(duration)
            self.stop_discovery() # Süre sonunda taramayı durdur
            # Tarama sonrası güncel listeyi döndür
            return self.list_devices(force_refresh=True)

        except dbus.exceptions.DBusException as e:
            log.error(f"DBus Hatası (Bluetooth tarama): {e}")
            self._check_bluetooth_service_status()
            return []
        except Exception as e:
            log.error(f"Bluetooth tarama sırasında hata: {e}")
            return []

    def stop_discovery(self):
        """Bluetooth cihaz keşfini durdurur."""
        if not self.is_adapter_available(): return
        try:
            if self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                self.adapter.StopDiscovery()
                log.info("Bluetooth cihaz taraması durduruldu.")
        except dbus.exceptions.DBusException as e:
             log.error(f"DBus Hatası (Tarama durdurma): {e}")
        except Exception as e:
            log.error(f"Bluetooth taraması durdurulurken hata: {e}")

    def list_devices(self, force_refresh=False):
        """Bulunan ve eşleşmiş Bluetooth cihazlarını listeler (önbellek kullanarak)."""
        current_time = time.time()
        # Belirli aralıklarla veya zorlandığında listeyi yenile
        if force_refresh or not self.device_list_cache or (current_time - self.last_scan_time > self.scan_interval):
            if not self.is_adapter_available():
                log.error("Bluetooth adaptörü mevcut değil, cihazlar listelenemiyor.")
                return []
            log.info("Bluetooth cihaz listesi yenileniyor...")
            devices = []
            try:
                om = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
                objects = om.GetManagedObjects()
                for path, interfaces in objects.items():
                    if 'org.bluez.Device1' in interfaces:
                        device_props = interfaces['org.bluez.Device1']
                        address = device_props.get('Address')
                        if address:
                            name = device_props.get('Name', 'İsimsiz Cihaz')
                            is_audio_device = 'org.bluez.MediaTransport1' in interfaces or \
                                            any('Audio' in str(uuid) for uuid in device_props.get('UUIDs', [])) or \
                                            str(device_props.get('Icon', '')).startswith('audio-')
                            devices.append({
                                'path': path,
                                'name': str(name),
                                'address': str(address),
                                'connected': bool(device_props.get('Connected', False)),
                                'paired': bool(device_props.get('Paired', False)),
                                'trusted': bool(device_props.get('Trusted', False)),
                                'audio_device': is_audio_device,
                                'icon': str(device_props.get('Icon', 'bluetooth')),
                                'rssi': int(device_props.get('RSSI', -101)), # -101 bilinmeyen/geçersiz
                            })
                # RSSI ve isme göre sırala
                self.device_list_cache = sorted(devices, key=lambda d: (not d['paired'], d['rssi'] < -80, -d['rssi'], d['name']))
                self.last_scan_time = current_time
                log.info(f"{len(self.device_list_cache)} Bluetooth cihazı listelendi/güncellendi.")
            except dbus.exceptions.DBusException as e:
                log.error(f"DBus Hatası (Cihaz listeleme): {e}")
                self._check_bluetooth_service_status()
                return [] # Hata durumunda boş liste döndür, önbelleği temizleme
            except Exception as e:
                log.error(f"Bluetooth cihazları listelenirken hata: {e}")
                return []
        else:
            log.debug("Önbellekten Bluetooth cihaz listesi kullanılıyor.")
        return self.device_list_cache

    def pair_device(self, device_address):
        """Bir Bluetooth cihazıyla eşleşir."""
        if not self.is_adapter_available(): return False, "Bluetooth adaptörü mevcut değil."

        device_to_pair = self._find_device_by_address(device_address, force_refresh=True) # Eşleştirmeden önce güncel bilgi al
        if not device_to_pair: return False, f"Cihaz bulunamadı: {device_address}"
        if device_to_pair['paired']:
             log.info(f"{device_to_pair['name']} zaten eşleşmiş.")
             if not device_to_pair['trusted']: return self.trust_device(device_address) # Güvenilir yap
             return True, f"{device_to_pair['name']} zaten eşleşmiş."

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_pair['path'])
            device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
            log.info(f"{device_to_pair['name']} ile eşleştirme başlatılıyor...")
            device_interface.Pair(timeout=60) # 60 saniye timeout
            log.info("Eşleştirme isteği gönderildi. Cihazdan onay bekleniyor...")
            # Eşleşmenin tamamlanmasını beklemek için daha iyi bir yöntem sinyal dinlemek olurdu.
            # Şimdilik bekleme ve ardından kontrol.
            time.sleep(10)
            # Durumu tekrar kontrol et
            props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            if props_interface.Get('org.bluez.Device1', 'Paired'):
                log.info("Eşleştirme başarılı!")
                return self.trust_device(device_address) # Eşleşme sonrası güvenilir yap
            else:
                log.warning("Eşleştirme zaman aşımına uğradı veya başarısız oldu.")
                return False, "Eşleştirme başarısız oldu veya zaman aşımına uğradı."
        except dbus.exceptions.DBusException as e:
            log.error(f"Eşleştirme sırasında DBus hatası: {e}")
            msg = self._parse_dbus_error(e, "Eşleştirme hatası")
            if "already exists" in str(e): # Güvenilir yapmayı dene
                 log.warning("DBus 'already exists' hatası, güvenilir yapmayı deniyor...")
                 return self.trust_device(device_address)
            return False, msg
        except Exception as e:
            log.error(f"Eşleştirme sırasında genel hata: {e}")
            return False, f"Eşleştirme sırasında beklenmedik hata: {e}"

    def trust_device(self, device_address):
        """Cihazı güvenilir olarak işaretler."""
        if not self.is_adapter_available(): return False, "Bluetooth adaptörü mevcut değil."
        device_to_trust = self._find_device_by_address(device_address)
        if not device_to_trust: return False, f"Cihaz bulunamadı: {device_address}"

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_trust['path'])
            props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            props_interface.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
            log.info(f"{device_to_trust['name']} cihazı güvenilir olarak işaretlendi.")
            self._update_device_cache(device_address, {'trusted': True}) # Önbelleği güncelle
            return True, f"{device_to_trust['name']} güvenilir yapıldı."
        except dbus.exceptions.DBusException as e:
            log.error(f"Cihaz güvenilir yapılırken DBus hatası: {e}")
            return False, self._parse_dbus_error(e, "Güvenilir yapma hatası")
        except Exception as e:
            log.error(f"Cihaz güvenilir yapılırken genel hata: {e}")
            return False, f"Güvenilir yapma sırasında beklenmedik hata: {e}"

    def connect_device(self, device_address):
        """Bir Bluetooth cihazına bağlanır."""
        if not self.is_adapter_available(): return None, "Bluetooth adaptörü mevcut değil."

        # Bağlanmadan önce güncel listeyi al
        device_to_connect = self._find_device_by_address(device_address, force_refresh=True)
        if not device_to_connect: return None, f"Cihaz bulunamadı: {device_address}"
        if device_to_connect['connected']:
            log.info(f"{device_to_connect['name']} zaten bağlı.")
            # Sink kontrolü ve geçişi burada da yapılabilir (AudioSinkManager kullanarak)
            self._check_and_switch_sink(device_to_connect)
            return device_to_connect, f"{device_to_connect['name']} zaten bağlı."

        # Eşleşme ve güvenilirlik kontrolü
        if not device_to_connect['paired'] or not device_to_connect['trusted']:
            log.info(f"{device_to_connect['name']} eşleşmemiş veya güvenilir değil. Eşleştirme/güvenilir yapma deneniyor...")
            paired, msg = self.pair_device(device_address) # pair_device zaten trust'ı da dener
            if not paired:
                 # 'zaten eşleşmiş' mesajı geldiyse ve güvenilir değilse tekrar trust dene
                 if "zaten eşleşmiş" in msg and not self._is_device_trusted(device_address):
                      trusted, trust_msg = self.trust_device(device_address)
                      if not trusted: return None, f"Eşleşmiş ancak güvenilir yapılamadı: {trust_msg}"
                 else:
                      return None, f"Bağlantı öncesi eşleştirme/güvenilir yapma başarısız: {msg}"
            # Başarılıysa durumu güncellemek için kısa bekleme ve tekrar bulma
            time.sleep(1)
            device_to_connect = self._find_device_by_address(device_address, force_refresh=True)
            if not device_to_connect or not device_to_connect['paired'] or not device_to_connect['trusted']:
                 log.warning("Eşleştirme/güvenilir yapma sonrası durum güncellenmedi, yine de bağlanmayı deniyor.")


        try:
            device_obj = self.bus.get_object('org.bluez', device_to_connect['path'])
            device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
            log.info(f"{device_to_connect['name']} cihazına bağlanılıyor...")
            device_interface.Connect(timeout=30) # 30 saniye timeout
            log.info(f"{device_to_connect['name']} cihazına bağlantı isteği gönderildi.")
            # Bağlantının kurulmasını bekle (ideal yöntem sinyal dinlemek)
            time.sleep(5)
            # Durumu tekrar kontrol et
            props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            if props_interface.Get('org.bluez.Device1', 'Connected'):
                log.info(f"{device_to_connect['name']} cihazına başarıyla bağlandı!")
                self._update_device_cache(device_address, {'connected': True}) # Önbelleği güncelle
                # Ses cihazıysa sink'e geçiş yap
                self._check_and_switch_sink(device_to_connect)
                return self._find_device_by_address(device_address), f"{device_to_connect['name']} başarıyla bağlandı." # Güncel bilgiyi döndür
            else:
                log.warning(f"{device_to_connect['name']} cihazına bağlanma denendi ancak başarısız oldu.")
                return None, "Bağlantı başarısız oldu veya zaman aşımına uğradı."
        except dbus.exceptions.DBusException as e:
            log.error(f"Bağlanma sırasında DBus hatası: {e}")
            # 'Already Connected' veya benzeri bir durum varsa başarılı say
            if "Already Connected" in str(e) or "Operation Already In Progress" in str(e):
                 log.warning(f"DBus hatası ({e}), ancak cihaz zaten bağlı olabilir. Kontrol ediliyor...")
                 time.sleep(1)
                 props_interface = dbus.Interface(self.bus.get_object('org.bluez', device_to_connect['path']), 'org.freedesktop.DBus.Properties')
                 if props_interface.Get('org.bluez.Device1', 'Connected'):
                      log.info("Cihaz zaten bağlıymış.")
                      self._update_device_cache(device_address, {'connected': True})
                      self._check_and_switch_sink(device_to_connect)
                      return self._find_device_by_address(device_address), f"{device_to_connect['name']} zaten bağlı."
            return None, self._parse_dbus_error(e, "Bağlantı hatası")
        except Exception as e:
            log.error(f"Bağlanma sırasında genel hata: {e}")
            return None, f"Bağlanma sırasında beklenmedik hata: {e}"

    def disconnect_device(self, device_address):
        """Bir Bluetooth cihazının bağlantısını keser."""
        if not self.is_adapter_available(): return False, "Bluetooth adaptörü mevcut değil."
        device_to_disconnect = self._find_device_by_address(device_address)
        if not device_to_disconnect: return False, f"Cihaz bulunamadı: {device_address}"
        if not device_to_disconnect['connected']:
            log.info(f"{device_to_disconnect['name']} zaten bağlı değil.")
            return True, f"{device_to_disconnect['name']} zaten bağlı değil."

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_disconnect['path'])
            device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
            log.info(f"{device_to_disconnect['name']} cihazından bağlantı kesiliyor...")
            device_interface.Disconnect()
            log.info(f"{device_to_disconnect['name']} bağlantısı kesildi!")
            self._update_device_cache(device_address, {'connected': False}) # Önbelleği güncelle
            # Bağlantı kesildikten sonra varsayılan (ALSA) sink'e geç (eğer ses cihazıysa)
            if device_to_disconnect['audio_device']:
                 log.info("Bluetooth ses cihazı bağlantısı kesildi, ALSA'ya geçiliyor...")
                 audio_manager = AudioSinkManager()
                 switched, msg = audio_manager.switch_to_alsa()
                 if not switched: log.warning(f"ALSA'ya geçilemedi: {msg}")
            return True, f"{device_to_disconnect['name']} bağlantısı kesildi."
        except dbus.exceptions.DBusException as e:
            log.error(f"Bağlantı kesilirken DBus hatası: {e}")
            if "Not Connected" in str(e): # Zaten bağlı değilse başarılı say
                 log.warning("DBus 'Not Connected' hatası, zaten bağlı değilmiş.")
                 self._update_device_cache(device_address, {'connected': False})
                 return True, f"{device_to_disconnect['name']} zaten bağlı değil."
            return False, self._parse_dbus_error(e, "Bağlantı kesme hatası")
        except Exception as e:
            log.error(f"Bağlantı kesilirken genel hata: {e}")
            return False, f"Bağlantı kesme sırasında beklenmedik hata: {e}"

    def remove_device(self, device_address):
        """Bir Bluetooth cihazını sistemden (eşleşmeyi) kaldırır."""
        if not self.is_adapter_available(): return False, "Bluetooth adaptörü mevcut değil."
        # Kaldırmadan önce güncel listeyi al
        device_to_remove = self._find_device_by_address(device_address, force_refresh=True)
        if not device_to_remove: return False, f"Cihaz bulunamadı: {device_address}"

        try:
            # Önce bağlantıyı kes
            if device_to_remove['connected']:
                disconnected, msg = self.disconnect_device(device_address)
                if not disconnected: log.warning(f"Kaldırmadan önce bağlantı kesilemedi: {msg}")
                time.sleep(1)

            log.info(f"{device_to_remove['name']} cihazı kaldırılıyor (eşleşme siliniyor)...")
            self.adapter.RemoveDevice(device_to_remove['path'])
            log.info(f"{device_to_remove['name']} cihazı başarıyla kaldırıldı.")
            # Önbellekten kaldır
            self.device_list_cache = [d for d in self.device_list_cache if d['address'] != device_address]
            return True, f"{device_to_remove['name']} kaldırıldı."
        except dbus.exceptions.DBusException as e:
            log.error(f"Cihaz kaldırılırken DBus hatası: {e}")
            if "Does Not Exist" in str(e): # Zaten yoksa başarılı say
                 log.warning("DBus 'Does Not Exist' hatası, cihaz zaten kaldırılmış.")
                 self.device_list_cache = [d for d in self.device_list_cache if d['address'] != device_address]
                 return True, f"{device_to_remove['name']} zaten kaldırılmış."
            return False, self._parse_dbus_error(e, "Cihaz kaldırma hatası")
        except Exception as e:
            log.error(f"Cihaz kaldırılırken genel hata: {e}")
            return False, f"Cihaz kaldırma sırasında beklenmedik hata: {e}"

    def _find_device_by_address(self, device_address, force_refresh=False):
        """Verilen adrese sahip cihazı bulur (önbellekten veya yenileyerek)."""
        # Önce önbellekte ara
        if not force_refresh:
            for device in self.device_list_cache:
                if device['address'] == device_address:
                    return device
        # Önbellekte yoksa veya yenileme zorlandıysa listeyi güncelle
        updated_list = self.list_devices(force_refresh=True)
        for device in updated_list:
            if device['address'] == device_address:
                return device
        log.warning(f"Cihaz {device_address} bulunamadı.")
        return None

    def _update_device_cache(self, address, updates):
        """Önbellekteki cihaz bilgisini günceller."""
        for i, device in enumerate(self.device_list_cache):
            if device['address'] == address:
                self.device_list_cache[i].update(updates)
                log.debug(f"Önbellek güncellendi: {address} -> {updates}")
                break

    def _is_device_trusted(self, address):
        """Bir cihazın güvenilir olup olmadığını kontrol eder."""
        device = self._find_device_by_address(address)
        return device and device.get('trusted', False)

    def _check_and_switch_sink(self, device_info):
        """Cihaz ses cihazıysa ve bağlıysa sink'e geçişi kontrol eder/dener."""
        if device_info and device_info['audio_device'] and device_info['connected']:
            log.info(f"'{device_info['name']}' için ses çıkışı kontrol ediliyor...")
            audio_manager = AudioSinkManager()
            if not audio_manager.is_sink_active(device_info['name']):
                 log.info(f"'{device_info['name']}' aktif sink değil, geçiş yapılıyor...")
                 switched, msg = audio_manager.switch_to_bluetooth_sink(device_info['name'])
                 if switched:
                      log.info(f"'{device_info['name']}' ses çıkışına başarıyla geçildi.")
                      # Opsiyonel: Spotifyd yeniden başlatma
                      # restart_spotifyd()
                 else:
                      log.warning(f"'{device_info['name']}' ses çıkışına geçilemedi: {msg}")
            else:
                 log.info(f"'{device_info['name']}' zaten aktif ses çıkışı.")

    def _check_bluetooth_service_status(self):
        """Bluetooth servisinin durumunu kontrol eder ve loglar."""
        try:
            subprocess.check_call(["systemctl", "is-active", "--quiet", "bluetooth"])
        except subprocess.CalledProcessError:
            log.warning("Bluetooth servisi (bluetooth.service) çalışmıyor.")
        except FileNotFoundError:
            log.warning("systemctl komutu bulunamadı, servis durumu kontrol edilemiyor.")

    def _parse_dbus_error(self, error, context="Hata"):
        """DBus hata mesajını daha anlaşılır hale getirmeye çalışır."""
        msg = f"{context}: {error}"
        s_err = str(error).lower()
        if "authentication failed" in s_err: msg = f"{context}: Kimlik doğrulama başarısız."
        elif "authentication canceled" in s_err: msg = f"{context}: Kimlik doğrulama iptal edildi."
        elif "connection attempt failed" in s_err: msg = f"{context}: Bağlantı denemesi başarısız."
        elif "device or resource busy" in s_err: msg = f"{context}: Cihaz veya kaynak meşgul."
        elif "operation not permitted" in s_err: msg = f"{context}: İşlem izni yok."
        elif "no such file or directory" in s_err or "does not exist" in s_err: msg = f"{context}: Cihaz bulunamadı veya artık mevcut değil."
        elif "timeout" in s_err: msg = f"{context}: İşlem zaman aşımına uğradı."
        return msg


class AudioSinkManager:
    """PulseAudio ses çıkışlarını yönetmek için sınıf."""
    def __init__(self):
        log.debug("AudioSinkManager örneği oluşturuluyor.")
        # PulseAudio bağlantısını her işlem için ayrı açmak genellikle daha stabildir.

    def _get_pulse_client(self, context_name='audio-manager'):
        """PulseAudio sunucusuna bağlanır."""
        try:
            # Bağlam adını dinamik ve benzersiz yapmak çakışmaları önleyebilir
            unique_context_name = f"{context_name}-{os.getpid()}-{threading.get_ident()}"
            pulse = pulsectl.Pulse(unique_context_name)
            log.debug(f"PulseAudio'ya '{unique_context_name}' olarak bağlanıldı.")
            return pulse
        except pulsectl.PulseError as e:
            log.error(f"PulseAudio bağlantı hatası ({unique_context_name}): {e}")
            self._check_pulseaudio_status()
            return None
        except Exception as e:
            log.error(f"PulseAudio istemcisi oluşturulurken beklenmedik hata: {e}")
            return None

    def list_sinks(self):
        """Mevcut ses çıkışlarını ve varsayılanı listeler."""
        pulse = self._get_pulse_client('sink-lister')
        if not pulse: return [], None

        sinks_info = []
        default_sink_name = None
        try:
            server_info = pulse.server_info()
            if server_info:
                 default_sink_name = server_info.default_sink_name
                 log.info(f"Varsayılan PulseAudio Sink: {default_sink_name}")
            else:
                 log.warning("PulseAudio sunucu bilgisi alınamadı.")

            pa_sinks = pulse.sink_list()
            for sink in pa_sinks:
                sinks_info.append({
                    'index': sink.index,
                    'name': sink.name,
                    'description': sink.description,
                    'is_default': sink.name == default_sink_name,
                })
            log.info(f"{len(sinks_info)} adet sink listelendi.")
            return sinks_info, default_sink_name
        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (list_sinks): {e}")
             return [], None
        except Exception as e:
            log.error(f"Ses cihazları listelenirken hata oluştu: {e}")
            return [], None
        finally:
            if pulse: pulse.close() # Bağlantıyı kapat

    def switch_to_sink(self, sink_identifier):
        """Belirtilen sink'e (index veya isim/açıklama) geçiş yapar."""
        pulse = self._get_pulse_client('sink-switcher')
        if not pulse: return False, "PulseAudio bağlantısı kurulamadı."

        target_sink = None
        try:
            sinks = pulse.sink_list()
            if isinstance(sink_identifier, int):
                target_sink = next((s for s in sinks if s.index == sink_identifier), None)
                if not target_sink: return False, f"Geçersiz sink indeksi: {sink_identifier}"
            elif isinstance(sink_identifier, str):
                identifier_lower = sink_identifier.lower()
                # Önce tam isimle eşleşme ara, sonra açıklama içinde ara
                target_sink = next((s for s in sinks if identifier_lower == s.name.lower()), None)
                if not target_sink:
                     target_sink = next((s for s in sinks if identifier_lower in s.description.lower()), None)
                if not target_sink: return False, f"Sink bulunamadı: '{sink_identifier}'"
            else:
                return False, "Geçersiz sink tanımlayıcı türü."

            log.info(f"Ses çıkışı '{target_sink.description}' (Index: {target_sink.index}) cihazına yönlendiriliyor...")

            moved_inputs = 0
            for stream in pulse.sink_input_list():
                try:
                    pulse.sink_input_move(stream.index, target_sink.index)
                    log.debug(f"Sink input {stream.index} taşındı.")
                    moved_inputs += 1
                except pulsectl.PulseOperationFailed as op_err:
                     log.warning(f"Sink input {stream.index} taşınırken hata: {op_err}")

            pulse.default_set(target_sink)
            log.info(f"Ses çıkışı '{target_sink.description}' olarak ayarlandı. {moved_inputs} uygulama taşındı.")
            return True, f"Ses çıkışı '{target_sink.description}' olarak ayarlandı."
        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (switch_to_sink): {e}")
             return False, f"PulseAudio hatası: {e}"
        except Exception as e:
            log.error(f"Sink değiştirilirken hata oluştu: {e}")
            return False, f"Beklenmedik hata: {e}"
        finally:
            if pulse: pulse.close()

    def find_sink_by_device_name(self, device_name):
        """Bluetooth cihaz adına göre ilgili sink'i bulur."""
        pulse = self._get_pulse_client('bt-sink-finder')
        if not pulse: return None

        try:
            device_name_lower = device_name.lower()
            # Bluez sink isimleri genellikle 'bluez_sink.XX_XX_XX_XX_XX_XX.a2dp_sink' formatındadır.
            # Açıklamada ise cihaz adı geçer. MAC adresini de kontrol etmek daha güvenilir olabilir.
            mac_address_part = device_name_lower.replace(":", "_") # Eğer isim MAC adresi içeriyorsa

            for sink in pulse.sink_list():
                sink_name_lower = sink.name.lower()
                sink_desc_lower = sink.description.lower()
                # Açıklamada cihaz adı veya sink adında MAC adresi var mı?
                if device_name_lower in sink_desc_lower or mac_address_part in sink_name_lower:
                    log.info(f"'{device_name}' için uygun sink bulundu: {sink.description} ({sink.name})")
                    return sink # Pulse nesnesini değil, sink bilgisini döndür
            log.warning(f"'{device_name}' için uygun sink bulunamadı.")
            return None
        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (find_sink_by_device_name): {e}")
             return None
        except Exception as e:
            log.error(f"Cihaz için sink aranırken hata: {e}")
            return None
        finally:
            if pulse: pulse.close()

    def switch_to_bluetooth_sink(self, device_name):
        """Verilen Bluetooth cihazının sink'ine geçiş yapar."""
        target_sink_info = self.find_sink_by_device_name(device_name)
        if target_sink_info:
            return self.switch_to_sink(target_sink_info.index)
        return False, f"'{device_name}' için uygun Bluetooth sink bulunamadı."

    def switch_to_alsa(self):
        """Varsayılan ALSA (genellikle dahili/analog) sink'ine geçiş yapar."""
        log.info("Varsayılan ALSA sink'ine geçiş yapılıyor...")
        pulse = self._get_pulse_client('alsa-finder')
        if not pulse: return False, "PulseAudio bağlantısı kurulamadı."

        alsa_sink = None
        try:
            sinks = pulse.sink_list()
            # Öncelik sırası: 'analog-stereo' içeren, 'alsa_output' içeren, 'Built-in' içeren
            possible_sinks = [s for s in sinks if "bluez" not in s.name.lower()] # Bluetooth olmayanlar
            alsa_sink = next((s for s in possible_sinks if "analog-stereo" in s.name.lower()), None)
            if not alsa_sink:
                 alsa_sink = next((s for s in possible_sinks if "alsa_output" in s.name.lower()), None)
            if not alsa_sink:
                 alsa_sink = next((s for s in possible_sinks if "built-in" in s.description.lower()), None)
            # Hiçbiri bulunamazsa Bluetooth olmayan ilk sink'i seç
            if not alsa_sink and possible_sinks:
                 alsa_sink = possible_sinks[0]

            if alsa_sink:
                log.info(f"Hedef ALSA sink: {alsa_sink.description} (Index: {alsa_sink.index})")
                # switch_to_sink zaten bağlantıyı kapatacak, burada kapatmaya gerek yok
                pulse.close() # Bu bağlantıyı kapatabiliriz
                return self.switch_to_sink(alsa_sink.index)
            else:
                log.warning("Uygun bir ALSA veya varsayılan sink bulunamadı.")
                return False, "Uygun ALSA sink bulunamadı."

        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (switch_to_alsa): {e}")
             return False, f"PulseAudio hatası: {e}"
        except Exception as e:
            log.error(f"ALSA cihazına geçiş yapılırken hata oluştu: {e}")
            return False, f"Beklenmedik hata: {e}"
        finally:
            # Pulse bağlantısı switch_to_sink içinde kapatılmadıysa burada kapat
            if pulse and not pulse.closed: pulse.close()


    def is_sink_active(self, sink_name_or_description):
        """Verilen sink'in şu anda varsayılan olup olmadığını kontrol eder."""
        sinks, current_default_name = self.list_sinks()
        if not current_default_name or not sinks:
            return False

        identifier_lower = sink_name_or_description.lower()
        # Önce isimle tam eşleşme
        if identifier_lower == current_default_name.lower():
             return True
        # Sonra açıklama ile eşleşme
        default_sink = next((s for s in sinks if s.name == current_default_name), None)
        if default_sink and identifier_lower in default_sink.description.lower():
             return True
        # Bluetooth MAC adresi ile eşleşme (sink adında)
        mac_address_part = identifier_lower.replace(":", "_")
        if f"bluez_sink.{mac_address_part}" in current_default_name.lower():
             return True

        return False

    def _check_pulseaudio_status(self):
        """PulseAudio servisinin durumunu kontrol eder ve loglar."""
        try:
            # Kullanıcı servisi olarak kontrol et
            subprocess.check_call(["systemctl", "--user", "is-active", "--quiet", "pulseaudio.socket"])
            subprocess.check_call(["systemctl", "--user", "is-active", "--quiet", "pulseaudio.service"])
            log.info("PulseAudio servisi (kullanıcı) aktif görünüyor.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            log.warning("PulseAudio servisi (kullanıcı) çalışmıyor veya kontrol edilemiyor. (systemctl --user status pulseaudio)")

>>>>>>> 9549b5229460375add453d5a601ced84b8632854

# --- Flask Uygulaması ---

app = Flask(__name__)
<<<<<<< HEAD
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
=======
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_cok_guvensiz_anahtar_hemen_degistir')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) # Oturum süresi

# Yönetici şifresi
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'mekan123')
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

# Uygulama başlangıcında yöneticileri oluşturmak yerine her istekte oluşturmak
# Flask'ın istek yönetimiyle daha uyumlu olabilir, ancak daha az verimli.
# Şimdilik her istekte oluşturma yöntemini kullanıyoruz.
# bt_manager = BluetoothManager() # Global instance sorun yaratabilir
# sink_manager = AudioSinkManager()

# --- Admin Giriş Koruması ---

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Bu sayfayı görüntülemek için yönetici girişi yapmalısınız.', 'warning')
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- Web Sayfaları ---

@app.route('/')
def index():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    else:
        return redirect(url_for('admin_login_page'))

@app.route('/login', methods=['GET', 'POST'])
def admin_login_page():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        password_attempt = request.form.get('password')
        if password_attempt == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session.permanent = True # Oturumu kalıcı yap
            log.info("Yönetici girişi başarılı.")
            flash('Giriş başarılı!', 'success')
            return redirect(url_for('admin_panel'))
        else:
            log.warning("Başarısız yönetici girişi denemesi.")
            flash('Yanlış şifre. Lütfen tekrar deneyin.', 'danger')
            time.sleep(1) # Basit rate limiting
            return render_template('admin.html'), 401

    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    log.info("Yönetici çıkışı yapıldı.")
    flash('Başarıyla çıkış yaptınız.', 'info')
    return redirect(url_for('admin_login_page'))

@app.route('/admin/panel')
@admin_login_required
def admin_panel():
<<<<<<< HEAD
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
=======
    # Paneli render etmeden önce backend'den bazı temel verileri gönderebiliriz.
    # Ancak çoğu veri artık API üzerinden dinamik olarak yükleniyor.
    # Spotify ile ilgili veriler (eğer entegre edilirse) burada gönderilebilir.
    # Örnek:
    # spotify_data = get_spotify_data() # Bu fonksiyonun tanımlanması gerekir
    return render_template('admin_panel.html') # spotify_authenticated=spotify_data.get('auth'), ...

# --- API Rotaları ---
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

# Her API isteği için yönetici örneklerini oluştur
# Bu, DBus/PulseAudio bağlantılarının her istekte açılıp kapanmasına neden olabilir.
# Alternatif: Uygulama bağlamı (g) veya global nesneler kullanmak (dikkatli olunmalı).
def get_bt_manager():
    return BluetoothManager()

<<<<<<< HEAD
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
=======
def get_sink_manager():
    return AudioSinkManager()
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

@app.route('/api/status')
@admin_login_required
<<<<<<< HEAD
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
=======
def api_status():
    """Genel sistem durumu ve temel bilgileri döndürür."""
    bt_manager = get_bt_manager()
    sink_manager = get_sink_manager()
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

    bt_available = bt_manager.is_adapter_available()
    sinks, default_sink = sink_manager.list_sinks()
    # is_adapter_available'dan sonra list_devices çağrılmalı
    paired_devices = bt_manager.list_devices() if bt_available else []

    # Spotify durumu (eğer entegre edilirse)
    # spotify_status = get_spotify_status()

    # Yöneticileri temizlemeye gerek yok, Flask request sonunda otomatik temizlenirler (teoride)
    # bt_manager._cleanup() # Gerekli değil

    return jsonify({
        'bluetooth_adapter_available': bt_available,
        'pulseaudio_available': bool(sinks is not None), # list_sinks None döndürmez ama kontrol edelim
        'sinks': sinks if sinks is not None else [],
        'default_sink_name': default_sink,
        'paired_bluetooth_devices': [d for d in paired_devices if d['paired']], # Sadece eşleşmişleri döndür
        # 'spotify_status': spotify_status
    })

@app.route('/api/bluetooth/devices')
@admin_login_required
def api_bluetooth_devices():
    """Eşleşmiş ve mevcut Bluetooth cihazlarını listeler."""
    bt_manager = get_bt_manager()
    devices = bt_manager.list_devices(force_refresh=True) # Her zaman güncel listeyi al
    return jsonify({'devices': devices})

@app.route('/api/bluetooth/scan', methods=['POST'])
@admin_login_required
<<<<<<< HEAD
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
=======
def api_bluetooth_scan():
    """Yeni Bluetooth cihazlarını tarar."""
    scan_duration = request.json.get('duration', 5)
    bt_manager = get_bt_manager()
    log.info(f"{scan_duration} saniyelik Bluetooth taraması başlatılıyor...")
    devices = bt_manager.start_discovery(duration=scan_duration)
    log.info(f"Tarama tamamlandı, {len(devices)} cihaz bulundu/güncellendi.")
    return jsonify({'devices': devices})
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

@app.route('/api/bluetooth/pair', methods=['POST'])
@admin_login_required
<<<<<<< HEAD
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
=======
def api_bluetooth_pair():
    """Bir Bluetooth cihazıyla eşleşir."""
    address = request.json.get('address')
    if not address: return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = get_bt_manager()
    success, message = bt_manager.pair_device(address)
    return jsonify({'success': success, 'message': message})
>>>>>>> 9549b5229460375add453d5a601ced84b8632854

@app.route('/api/bluetooth/connect', methods=['POST'])
@admin_login_required
def api_bluetooth_connect():
    """Bir Bluetooth cihazına bağlanır."""
    address = request.json.get('address')
    if not address: return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = get_bt_manager()
    device_info, message = bt_manager.connect_device(address)
    return jsonify({'success': bool(device_info), 'message': message, 'device': device_info})

@app.route('/api/bluetooth/disconnect', methods=['POST'])
@admin_login_required
def api_bluetooth_disconnect():
    """Bir Bluetooth cihazının bağlantısını keser."""
    address = request.json.get('address')
    if not address: return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = get_bt_manager()
    success, message = bt_manager.disconnect_device(address)
    return jsonify({'success': success, 'message': message})

@app.route('/api/bluetooth/remove', methods=['POST'])
@admin_login_required
def api_bluetooth_remove():
    """Bir Bluetooth cihazını sistemden kaldırır."""
    address = request.json.get('address')
    if not address: return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = get_bt_manager()
    success, message = bt_manager.remove_device(address)
    return jsonify({'success': success, 'message': message})


@app.route('/api/audio/sinks')
@admin_login_required
def api_audio_sinks():
    """Mevcut ses çıkış cihazlarını (sink) listeler."""
    sink_manager = get_sink_manager()
    sinks, default_sink = sink_manager.list_sinks()
    return jsonify({'sinks': sinks if sinks is not None else [], 'default_sink_name': default_sink})

@app.route('/api/audio/switch_sink', methods=['POST'])
@admin_login_required
def api_audio_switch_sink():
    """Belirtilen ses çıkış cihazına (sink) geçer."""
    sink_identifier = request.json.get('sink_identifier')
    if sink_identifier is None: return jsonify({'success': False, 'message': 'Sink tanımlayıcı belirtilmedi.'}), 400
    if isinstance(sink_identifier, str) and sink_identifier.isdigit():
         sink_identifier = int(sink_identifier)

    sink_manager = get_sink_manager()
    success, message = sink_manager.switch_to_sink(sink_identifier)
    return jsonify({'success': success, 'message': message})

@app.route('/api/audio/switch_alsa', methods=['POST'])
@admin_login_required
def api_audio_switch_alsa():
    """Varsayılan ALSA ses çıkış cihazına geçer."""
    sink_manager = get_sink_manager()
    success, message = sink_manager.switch_to_alsa()
    return jsonify({'success': success, 'message': message})


@app.route('/api/spotifyd/restart', methods=['POST'])
@admin_login_required
def api_spotifyd_restart():
    """Spotifyd servisini yeniden başlatır."""
    log.info("API üzerinden Spotifyd yeniden başlatma isteği alındı.")
    success = restart_spotifyd()
    message = "Spotifyd başarıyla yeniden başlatıldı." if success else "Spotifyd yeniden başlatılamadı. Logları kontrol edin."
    return jsonify({'success': success, 'message': message})

# --- Spotify ile ilgili Rotalar (Eski panelden kalan, implementasyon GEREKLİ) ---
# Bu rotaların çalışması için Spotipy entegrasyonu ve ilgili fonksiyonların (get_spotify_data, vb.)
# tanımlanması gerekmektedir. Şimdilik sadece iskelet olarak duruyorlar.

@app.route('/spotify-auth') # Örnek Spotify yetkilendirme başlangıç noktası
@admin_login_required
def spotify_auth():
    # Spotipy kullanarak Spotify yetkilendirme URL'sini oluştur ve yönlendir
    # ... (Spotipy kodları buraya gelecek) ...
    flash("Spotify yetkilendirmesi henüz uygulanmadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/callback') # Spotify yetkilendirme sonrası geri dönüş URL'si
def spotify_callback():
    # Spotify'dan gelen kodu alıp token al
    # ... (Spotipy kodları buraya gelecek) ...
    flash("Spotify geri dönüş işleyici henüz uygulanmadı.", "warning")
    return redirect(url_for('admin_panel'))

@app.route('/refresh-devices', methods=['GET']) # Spotify Connect cihazlarını yenileme
@admin_login_required
def refresh_devices():
     # Spotipy kullanarak cihaz listesini yenile ve admin paneline yönlendir
     # ... (Spotipy kodları buraya gelecek) ...
     flash("Spotify cihaz yenileme henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

@app.route('/update-settings', methods=['POST']) # Ayarları ve aktif Connect cihazını güncelleme
@admin_login_required
def update_settings():
     # Formdan gelen verileri al (max_queue_length, active_spotify_connect_device_id, genre_*)
     # Ayarları kaydet (örn. settings.json'a)
     # Aktif cihazı Spotify'a bildir (Spotipy transfer_playback)
     # ... (İlgili kodlar buraya gelecek) ...
     flash("Ayarları güncelleme henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

@app.route('/add-song', methods=['POST']) # Kuyruğa şarkı ekleme
@admin_login_required
def add_song():
<<<<<<< HEAD
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
=======
     # Formdan şarkı ID/URL'sini al
     # Spotipy ile şarkıyı kuyruğa ekle (add_to_queue)
     # ... (İlgili kodlar buraya gelecek) ...
     flash("Şarkı ekleme henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

@app.route('/remove-song/<song_id>', methods=['POST']) # Kuyruktan şarkı kaldırma (ID ile değil, index ile olabilir?)
>>>>>>> 9549b5229460375add453d5a601ced84b8632854
@admin_login_required
def remove_song(song_id):
     # Kuyruktan şarkıyı kaldır (Bu Spotify API'si ile doğrudan mümkün olmayabilir, lokal kuyruk yönetimi gerekebilir)
     # ... (İlgili kodlar buraya gelecek) ...
     flash("Şarkı kaldırma henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

@app.route('/clear-queue', methods=['POST']) # Kuyruğu temizleme (Spotify API'si ile doğrudan mümkün değil)
@admin_login_required
def clear_queue():
     # Lokal kuyruk yönetimi varsa temizle
     # ... (İlgili kodlar buraya gelecek) ...
     flash("Kuyruk temizleme henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

<<<<<<< HEAD
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

=======
@app.route('/player/pause', methods=['GET']) # Çalmayı durdurma
@admin_login_required
def player_pause():
     # Spotipy ile çalmayı durdur (pause_playback)
     # ... (Spotipy kodları buraya gelecek) ...
     flash("Çalmayı durdurma henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

@app.route('/player/resume', methods=['GET']) # Çalmaya devam etme
@admin_login_required
def player_resume():
     # Spotipy ile çalmaya devam et (start_playback)
     # ... (Spotipy kodları buraya gelecek) ...
     flash("Çalmaya devam etme henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))


# --- Uygulamayı Başlat ---

if __name__ == "__main__":
    log.info("Flask uygulaması başlatılıyor...")
    # Gerekli servislerin durumunu kontrol et (opsiyonel)
    BluetoothManager()._check_bluetooth_service_status()
    AudioSinkManager()._check_pulseaudio_status()

    # Geliştirme için debug=True, production için debug=False
    # use_reloader=False, DBus/GLib ile çakışmaları önlemek için önemli olabilir.
    # threaded=True, birden fazla isteği işlemek için.
    is_debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=8080, debug=is_debug, threaded=True, use_reloader=False)

    log.info("Flask uygulaması durduruldu.")

>>>>>>> 9549b5229460375add453d5a601ced84b8632854
