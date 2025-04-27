#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import pulsectl
import sys
import os
import time
import dbus
from dbus.mainloop.glib import DBusGMainLoop
# GLib importu dbus için gerekli olsa da doğrudan kullanılmıyorsa kaldırılabilir.
# from gi.repository import GLib
import json # JSON çıktısı için
import argparse # Komut satırı argümanları için
import logging # Loglama için

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('ex_script')

# --- BluetoothManager Sınıfı (DBus Kullanımı - Hata Yönetimi Eklendi) ---
class BluetoothManager:
    def __init__(self):
        self.bus = None
        self.adapter = None
        self.adapter_props = None
        try:
            # DBus ana döngüsünü ayarla (bazı ortamlar için gerekli olabilir)
            # DBusGMainLoop(set_as_default=True) # Genellikle gerekli değil, sorun olursa açılabilir
            self.bus = dbus.SystemBus()
            # Varsayılan adaptörü bulmaya çalış (genellikle hci0)
            # Daha dinamik bir yol izlenebilir ama şimdilik hci0 varsayalım
            adapter_path = '/org/bluez/hci0'
            self.adapter_obj = self.bus.get_object('org.bluez', adapter_path)
            self.adapter = dbus.Interface(self.adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(self.adapter_obj, 'org.freedesktop.DBus.Properties')
            logger.info("BluetoothManager başarıyla başlatıldı.")
        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus başlatma hatası: {e}. Bluetooth servisi çalışıyor mu veya adaptör yolu doğru mu?")
            # Uygulamanın çökmesini engellemek için None olarak bırak
            self.bus = None
            self.adapter = None
            self.adapter_props = None
        except Exception as e:
            logger.error(f"BluetoothManager başlatılırken beklenmedik hata: {e}", exc_info=True)
            self.bus = None
            self.adapter = None
            self.adapter_props = None

    def _get_managed_objects(self):
        """Bluez objelerini alır."""
        if not self.bus:
            logger.error("DBus bağlantısı yok.")
            return {}
        try:
            om = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            return om.GetManagedObjects()
        except dbus.exceptions.DBusException as e:
            logger.error(f"Bluez objeleri alınırken DBus hatası: {e}")
            return {}
        except Exception as e:
            logger.error(f"Bluez objeleri alınırken hata: {e}", exc_info=True)
            return {}

    def list_devices(self, discovery_duration=5):
        """Bluetooth cihazlarını keşfeder ve listeler."""
        if not self.adapter or not self.adapter_props:
            logger.error("Bluetooth adaptörü düzgün başlatılamadı.")
            return {'success': False, 'error': 'Bluetooth adaptörü bulunamadı veya başlatılamadı.', 'devices': []}

        devices = []
        try:
            # Keşfi başlat (zaten açıksa hata vermez)
            logger.info(f"{discovery_duration} saniye boyunca Bluetooth cihazları taranıyor...")
            try:
                self.adapter.StartDiscovery(timeout=dbus.UInt32(discovery_duration + 1, variant_level=1)) # Timeout ekleyelim
                time.sleep(discovery_duration)
            except dbus.exceptions.DBusException as e:
                 # Already discovering ise sorun yok
                 if "Already discovering" not in str(e):
                     logger.warning(f"Keşif başlatılamadı (belki zaten aktifti?): {e}")
            finally:
                 # Keşfi durdurmayı dene
                 try:
                     if self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                          self.adapter.StopDiscovery()
                          logger.info("Cihaz keşfi durduruldu.")
                 except dbus.exceptions.DBusException as e:
                      logger.warning(f"Keşif durdurulurken hata: {e}")


            logger.info("Cihaz listesi alınıyor...")
            objects = self._get_managed_objects()
            if not objects:
                 return {'success': False, 'error': 'Bluez objeleri alınamadı.', 'devices': []}

            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    device_props = interfaces['org.bluez.Device1']
                    # Temel bilgileri alalım
                    name = str(device_props.get('Name', device_props.get('Alias', 'Bilinmeyen Cihaz')))
                    address = str(device_props.get('Address', 'Adres Yok'))
                    connected = bool(device_props.get('Connected', False))
                    paired = bool(device_props.get('Paired', False))
                    # Ses profili desteğini kontrol et (daha güvenilir olabilir)
                    uuids = device_props.get('UUIDs', [])
                    is_audio_device = any('a2dp' in str(uuid).lower() or 'hfp' in str(uuid).lower() or 'avrcp' in str(uuid).lower() for uuid in uuids)

                    device_info = {
                        'path': str(path), # DBus yolu (bağlanma/çıkarma için lazım)
                        'name': name,
                        'mac_address': address, # app.py'nin beklediği anahtar
                        'connected': connected,
                        'paired': paired,
                        'is_audio': is_audio_device, # Ses cihazı olup olmadığı
                        'type': 'bluetooth' # app.py uyumluluğu
                    }
                    devices.append(device_info)

            logger.info(f"{len(devices)} Bluetooth cihazı bulundu/listelendi.")
            return {'success': True, 'devices': devices}

        except dbus.exceptions.DBusException as e:
            logger.error(f"Cihazlar listelenirken DBus hatası: {e}")
            return {'success': False, 'error': f'DBus hatası: {e}', 'devices': []}
        except Exception as e:
            logger.error(f"Cihazlar listelenirken hata: {e}", exc_info=True)
            return {'success': False, 'error': f'Beklenmedik hata: {e}', 'devices': []}
        finally:
             # Her ihtimale karşı keşfi tekrar durdurmayı dene
             try:
                 if self.adapter and self.adapter_props and self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                      self.adapter.StopDiscovery()
             except: pass # Hataları yoksay

    def _get_device_interface(self, device_path):
        """Verilen yoldaki cihaz arayüzünü alır."""
        if not self.bus: return None
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            return dbus.Interface(device_obj, 'org.bluez.Device1')
        except dbus.exceptions.DBusException as e:
            logger.error(f"Cihaz arayüzü alınırken DBus hatası ({device_path}): {e}")
            return None
        except Exception as e:
            logger.error(f"Cihaz arayüzü alınırken hata ({device_path}): {e}", exc_info=True)
            return None

    def connect_device(self, device_path):
        """Verilen DBus yolundaki cihaza bağlanır."""
        if not self.adapter:
             return {'success': False, 'error': 'Bluetooth adaptörü bulunamadı.'}

        device_interface = self._get_device_interface(device_path)
        if not device_interface:
            return {'success': False, 'error': f'Cihaz arayüzü alınamadı ({device_path}).'}

        try:
            props_iface = dbus.Interface(device_interface, 'org.freedesktop.DBus.Properties')
            device_name = str(props_iface.Get('org.bluez.Device1', 'Name'))
            is_connected = bool(props_iface.Get('org.bluez.Device1', 'Connected'))
            is_paired = bool(props_iface.Get('org.bluez.Device1', 'Paired'))

            if is_connected:
                logger.info(f"'{device_name}' zaten bağlı.")
                return {'success': True, 'message': f"'{device_name}' zaten bağlı."}

            if not is_paired:
                logger.info(f"'{device_name}' eşleşmemiş, eşleştiriliyor...")
                try:
                    device_interface.Pair(timeout=dbus.UInt32(20, variant_level=1)) # Eşleşme için timeout
                    logger.info(f"'{device_name}' başarıyla eşleştirildi.")
                    # Eşleşme sonrası güvenmeyi dene (bazı cihazlar için gerekli)
                    try:
                        props_iface.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
                        logger.info(f"'{device_name}' güvenilir olarak işaretlendi.")
                    except Exception as trust_err:
                         logger.warning(f"'{device_name}' güvenilir olarak işaretlenemedi: {trust_err}")
                except dbus.exceptions.DBusException as e:
                    # Already Exists veya Authentication Failed gibi hatalar olabilir
                    logger.error(f"'{device_name}' eşleştirilemedi: {e}")
                    # Eşleşme başarısız olsa bile bağlanmayı deneyebiliriz
                    # return {'success': False, 'error': f"Eşleştirme hatası: {e}"}

            logger.info(f"'{device_name}' cihazına bağlanılıyor...")
            # Bağlanma işlemi zaman alabilir, timeout ekleyelim
            device_interface.Connect(timeout=dbus.UInt32(30, variant_level=1))
            # Bağlantının kurulduğunu doğrulamak için kısa bir süre bekle
            time.sleep(3)
            # Tekrar kontrol et
            if bool(props_iface.Get('org.bluez.Device1', 'Connected')):
                 logger.info(f"'{device_name}' cihazına başarıyla bağlanıldı.")
                 return {'success': True, 'message': f"'{device_name}' cihazına başarıyla bağlanıldı."}
            else:
                 logger.error(f"'{device_name}' cihazına bağlanılamadı (timeout veya başka bir sorun).")
                 return {'success': False, 'error': f"'{device_name}' cihazına bağlanılamadı."}


        except dbus.exceptions.DBusException as e:
            logger.error(f"Cihaza bağlanırken DBus hatası ({device_path}): {e}")
            # Hata mesajını analiz etmeye çalışalım
            error_str = str(e).lower()
            if "already connected" in error_str:
                 logger.info(f"'{device_name}' zaten bağlı (DBus hatası).")
                 return {'success': True, 'message': f"'{device_name}' zaten bağlı."}
            elif "connection attempt failed" in error_str or "failed" in error_str:
                 return {'success': False, 'error': f"Bağlantı denemesi başarısız: {e}"}
            else:
                 return {'success': False, 'error': f"DBus hatası: {e}"}
        except Exception as e:
            logger.error(f"Cihaza bağlanırken hata ({device_path}): {e}", exc_info=True)
            return {'success': False, 'error': f"Beklenmedik hata: {e}"}

    def disconnect_device(self, device_path):
        """Verilen DBus yolundaki cihazın bağlantısını keser."""
        if not self.adapter:
             return {'success': False, 'error': 'Bluetooth adaptörü bulunamadı.'}

        device_interface = self._get_device_interface(device_path)
        if not device_interface:
            return {'success': False, 'error': f'Cihaz arayüzü alınamadı ({device_path}).'}

        try:
            props_iface = dbus.Interface(device_interface, 'org.freedesktop.DBus.Properties')
            device_name = str(props_iface.Get('org.bluez.Device1', 'Name'))
            is_connected = bool(props_iface.Get('org.bluez.Device1', 'Connected'))

            if not is_connected:
                logger.info(f"'{device_name}' zaten bağlı değil.")
                return {'success': True, 'message': f"'{device_name}' zaten bağlı değil."}

            logger.info(f"'{device_name}' cihazından bağlantı kesiliyor...")
            device_interface.Disconnect(timeout=dbus.UInt32(10, variant_level=1))
            time.sleep(1) # Bağlantının kesilmesi için bekle
            logger.info(f"'{device_name}' bağlantısı kesildi.")
            return {'success': True, 'message': f"'{device_name}' bağlantısı kesildi."}

        except dbus.exceptions.DBusException as e:
            logger.error(f"Bağlantı kesilirken DBus hatası ({device_path}): {e}")
            # Hata mesajını analiz et
            error_str = str(e).lower()
            if "not connected" in error_str:
                 logger.info(f"'{device_name}' zaten bağlı değil (DBus hatası).")
                 return {'success': True, 'message': f"'{device_name}' zaten bağlı değil."}
            else:
                 return {'success': False, 'error': f"DBus hatası: {e}"}
        except Exception as e:
            logger.error(f"Bağlantı kesilirken hata ({device_path}): {e}", exc_info=True)
            return {'success': False, 'error': f"Beklenmedik hata: {e}"}

# --- AudioSinkManager Sınıfı (Pulsectl Kullanımı) ---
class AudioSinkManager:
    def __init__(self, app_name='ex_script_audio'):
        self.app_name = app_name

    def list_sinks(self):
        """Tüm mevcut ses çıkış cihazlarını (sink) listeler."""
        sinks_info = []
        default_sink_name = None
        try:
            # Bağlantı adını daha spesifik yapalım
            with pulsectl.Pulse(self.app_name + '-list') as pulse:
                raw_sinks = pulse.sink_list()
                server_info = pulse.server_info()
                default_sink_name = server_info.default_sink_name

                if not raw_sinks:
                    logger.info("Hiç ses çıkış cihazı (sink) bulunamadı.")
                    return {'success': True, 'sinks': [], 'default_sink_name': None}

                for sink in raw_sinks:
                    is_default = sink.name == default_sink_name
                    sinks_info.append({
                        'index': sink.index,
                        'name': sink.name,
                        'description': sink.description,
                        'state': str(sink.state),
                        'mute': sink.mute,
                        'volume': round(sink.volume.value_flat * 100),
                        'is_default': is_default,
                    })
                logger.info(f"{len(sinks_info)} sink listelendi. Varsayılan: {default_sink_name}")
                return {'success': True, 'sinks': sinks_info, 'default_sink_name': default_sink_name}

        except pulsectl.PulseError as e:
             logger.error(f"PulseAudio/PipeWire bağlantı hatası (list_sinks): {e}")
             return {'success': False, 'error': f"Ses sunucusu hatası: {e}", 'sinks': [], 'default_sink_name': None}
        except Exception as e:
            logger.error(f"Ses cihazları listelenirken genel hata: {e}", exc_info=True)
            return {'success': False, 'error': f"Bilinmeyen hata: {e}", 'sinks': [], 'default_sink_name': None}

    def switch_to_sink(self, sink_identifier):
        """Belirtilen sink'e (index veya isim/açıklama ile) geçiş yapar."""
        target_sink = None
        try:
            with pulsectl.Pulse(self.app_name + '-switch') as pulse:
                sinks = pulse.sink_list()
                if not sinks:
                     logger.error("Sink değiştirilemiyor, hiç sink bulunamadı.")
                     return {'success': False, 'error': "Hiç ses çıkış cihazı bulunamadı."}

                # Hedef sink'i bul
                if isinstance(sink_identifier, int) or sink_identifier.isdigit():
                    try:
                        sink_index = int(sink_identifier)
                        target_sink = pulse.sink_info(sink_index)
                        if not target_sink: raise ValueError("Sink index ile bulunamadı")
                    except (ValueError, pulsectl.PulseError) as e:
                         logger.error(f"Geçersiz veya bulunamayan sink indeksi: {sink_identifier} - Hata: {e}")
                         return {'success': False, 'error': f"Geçersiz veya bulunamayan sink indeksi: {sink_identifier}"}
                else:
                    # İsim veya açıklama ile ara (küçük/büyük harf duyarsız)
                    search_term = str(sink_identifier).lower()
                    found = False
                    for s in sinks:
                        if search_term in s.name.lower() or search_term in s.description.lower():
                            target_sink = s
                            found = True
                            break
                    if not found:
                        logger.error(f"'{sink_identifier}' isimli/açıklamalı sink bulunamadı!")
                        return {'success': False, 'error': f"'{sink_identifier}' isimli/açıklamalı sink bulunamadı!"}

                if not target_sink:
                     logger.error(f"Hedef sink belirlenemedi: {sink_identifier}")
                     return {'success': False, 'error': f"Hedef sink belirlenemedi: {sink_identifier}"}

                logger.info(f"Varsayılan sink '{target_sink.description}' (Index: {target_sink.index}) olarak ayarlanıyor...")
                pulse.default_set(target_sink)
                logger.info(f"Varsayılan ses çıkışı '{target_sink.description}' olarak başarıyla ayarlandı.")
                return {'success': True, 'message': f"Varsayılan ses çıkışı '{target_sink.description}' olarak ayarlandı."}

        except pulsectl.PulseError as e:
             logger.error(f"PulseAudio/PipeWire bağlantı hatası (switch_to_sink): {e}")
             return {'success': False, 'error': f"Ses sunucusuna bağlanılamadı: {e}"}
        except Exception as e:
            logger.error(f"Sink değiştirilirken genel hata: {e}", exc_info=True)
            return {'success': False, 'error': f"Sink değiştirilirken hata: {e}"}

    def find_sink_by_device_name(self, device_name):
        """Cihaz adına göre ilgili sink'i bulur ve bilgilerini döndürür."""
        try:
            with pulsectl.Pulse(self.app_name + '-find') as pulse:
                sinks = pulse.sink_list()
                if not sinks: return {'success': True, 'found': False, 'sink': None} # Sink yoksa hata değil

                search_term = device_name.lower()
                # Bluetooth cihazları için olası isim formatı
                bluez_search_term = f"bluez_sink.{device_name.replace(':', '_').lower()}"

                for sink in sinks:
                    name_lower = sink.name.lower()
                    desc_lower = sink.description.lower()
                    if search_term in name_lower or search_term in desc_lower or bluez_search_term in name_lower:
                        logger.info(f"'{device_name}' için eşleşen sink bulundu: {sink.description}")
                        sink_info = {
                            'index': sink.index,
                            'name': sink.name,
                            'description': sink.description,
                            'state': str(sink.state),
                            'is_default': sink.name == pulse.server_info().default_sink_name
                        }
                        return {'success': True, 'found': True, 'sink': sink_info}

                logger.warning(f"'{device_name}' için eşleşen sink bulunamadı.")
                return {'success': True, 'found': False, 'sink': None}
        except pulsectl.PulseError as e:
             logger.error(f"PulseAudio/PipeWire bağlantı hatası (find_sink): {e}")
             return {'success': False, 'error': f"Ses sunucusu hatası: {e}", 'found': False, 'sink': None}
        except Exception as e:
            logger.error(f"Cihaz için sink aranırken genel hata: {e}", exc_info=True)
            return {'success': False, 'error': f"Bilinmeyen hata: {e}", 'found': False, 'sink': None}

# --- Spotifyd Fonksiyonları ---
def get_spotifyd_pid():
    """Çalışan spotifyd süreçlerinin PID'sini bulur."""
    try:
        output = subprocess.check_output(["pgrep", "spotifyd"], text=True)
        pids = output.strip().split("\n")
        return {'success': True, 'pids': pids}
    except subprocess.CalledProcessError:
        return {'success': True, 'pids': []} # Çalışmıyorsa hata değil
    except FileNotFoundError:
        return {'success': False, 'error': "'pgrep' komutu bulunamadı."}
    except Exception as e:
        return {'success': False, 'error': f"PID alınırken hata: {e}"}

def restart_spotifyd():
    """Spotifyd servisini yeniden başlatır."""
    logger.info("Spotifyd yeniden başlatılıyor...")
    pid_result = get_spotifyd_pid()
    if not pid_result['success']:
        return pid_result # PID alma hatasını döndür

    pids = pid_result['pids']
    killed_pids = []
    messages = []
    start_success = False

    # Mevcut süreçleri sonlandır
    if pids:
        for pid in pids:
            try:
                os.kill(int(pid), 15) # SIGTERM
                killed_pids.append(pid)
                messages.append(f"PID {pid} sonlandırıldı.")
                time.sleep(0.5) # Kısa bekleme
            except ValueError:
                 messages.append(f"Geçersiz PID atlandı: {pid}")
            except ProcessLookupError:
                 messages.append(f"PID {pid} zaten sonlanmış.")
            except Exception as e:
                messages.append(f"PID {pid} sonlandırılamadı: {e}")
    else:
        messages.append("Çalışan Spotifyd süreci bulunamadı.")

    # Yeni süreci başlat
    spotifyd_command = ["spotifyd", "--no-daemon"] # Varsayılan, config olmadan
    # Config dosyası varsa ekleyelim (opsiyonel)
    config_home = os.path.expanduser("~/.config/spotifyd/spotifyd.conf")
    config_etc = "/etc/spotifyd.conf"
    if os.path.exists(config_home):
        spotifyd_command = ["spotifyd", "--config-path", config_home, "--no-daemon"]
        logger.info(f"Spotifyd config kullanılıyor: {config_home}")
    elif os.path.exists(config_etc):
        spotifyd_command = ["spotifyd", "--config-path", config_etc, "--no-daemon"]
        logger.info(f"Spotifyd config kullanılıyor: {config_etc}")

    try:
        subprocess.Popen(spotifyd_command)
        time.sleep(2) # Başlaması için bekle
        new_pid_result = get_spotifyd_pid()
        if new_pid_result['success'] and new_pid_result['pids'] and any(pid not in killed_pids for pid in new_pid_result['pids']):
            messages.append("Spotifyd başarıyla yeniden başlatıldı.")
            start_success = True
        else:
            messages.append("Spotifyd sonlandırıldı ancak yeniden başlatılamadı veya yeni süreç bulunamadı.")
            start_success = False
    except FileNotFoundError:
        messages.append("Hata: 'spotifyd' komutu bulunamadı. Yüklü mü?")
        start_success = False
    except Exception as e:
        messages.append(f"Spotifyd başlatılırken hata: {e}")
        start_success = False

    return {'success': start_success, 'message': " ".join(messages)}

# --- ALSA Geçiş Fonksiyonu ---
def switch_alsa():
    """ALSA uyumlu bir sink'e geçiş yapar."""
    audio_manager = AudioSinkManager()
    list_result = audio_manager.list_sinks()
    if not list_result['success']:
        return list_result # Sink listeleme hatasını döndür

    sinks = list_result['sinks']
    if not sinks:
        return {'success': False, 'error': "Hiç ses çıkış cihazı bulunamadı."}

    alsa_sinks = []
    for sink in sinks:
        name_lower = sink.get('name', '').lower()
        desc_lower = sink.get('description', '').lower()
        # 'alsa', 'analog', 'builtin' içeren ve 'bluez' içermeyenleri bul
        if ("alsa" in name_lower or "analog" in name_lower or "builtin" in desc_lower) and "bluez" not in name_lower:
             alsa_sinks.append(sink)

    if not alsa_sinks:
        return {'success': False, 'error': "Uygun ALSA ses çıkış cihazı bulunamadı."}

    # Tercihen varsayılan olmayan ilk ALSA'yı seç
    target_sink = None
    for sink in alsa_sinks:
        if not sink.get('is_default'):
            target_sink = sink
            break
    if not target_sink:
        target_sink = alsa_sinks[0] # Hepsi varsayılan ise ilkini al

    if target_sink.get('is_default'):
        return {'success': True, 'message': f"ALSA ses çıkışı ('{target_sink.get('description')}') zaten varsayılan."}

    # Seçilen ALSA sink'ine index ile geçiş yap
    switch_result = audio_manager.switch_to_sink(target_sink.get('index'))
    # Başarı mesajını biraz daha bilgilendirici yapalım
    if switch_result['success']:
         switch_result['message'] = f"ALSA ses çıkışına geçildi: {switch_result['message']}"
    else:
         switch_result['error'] = f"ALSA ses çıkışına geçiş yapılamadı: {switch_result.get('error', 'Bilinmeyen hata')}"

    return switch_result


# --- Ana Çalıştırma Bloğu ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ses ve Bluetooth Yönetim Betiği")
    parser.add_argument('command', help="Çalıştırılacak komut", choices=[
        'list_sinks', 'discover_bluetooth', 'pair_bluetooth',
        'disconnect_bluetooth', 'switch_to_alsa', 'set_audio_sink',
        'restart_spotifyd'
    ])
    # Komutlara özel argümanlar
    parser.add_argument('--identifier', help="set_audio_sink için sink index'i veya adı/açıklaması")
    parser.add_argument('--path', help="pair_bluetooth ve disconnect_bluetooth için cihaz DBus yolu")
    parser.add_argument('--duration', type=int, default=5, help="discover_bluetooth için tarama süresi (saniye)")

    args = parser.parse_args()

    result = {'success': False, 'error': 'Geçersiz komut veya argüman'} # Varsayılan hata

    # Komutları işle
    if args.command == 'list_sinks':
        manager = AudioSinkManager()
        result = manager.list_sinks()
    elif args.command == 'discover_bluetooth':
        manager = BluetoothManager()
        result = manager.list_devices(discovery_duration=args.duration)
    elif args.command == 'pair_bluetooth':
        if args.path:
            manager = BluetoothManager()
            result = manager.connect_device(args.path)
        else:
            result = {'success': False, 'error': '--path argümanı gerekli'}
    elif args.command == 'disconnect_bluetooth':
        if args.path:
            manager = BluetoothManager()
            result = manager.disconnect_device(args.path)
        else:
            result = {'success': False, 'error': '--path argümanı gerekli'}
    elif args.command == 'switch_to_alsa':
        result = switch_alsa()
    elif args.command == 'set_audio_sink':
        if args.identifier:
            manager = AudioSinkManager()
            result = manager.switch_to_sink(args.identifier)
        else:
            result = {'success': False, 'error': '--identifier argümanı gerekli'}
    elif args.command == 'restart_spotifyd':
        result = restart_spotifyd()

    # Sonucu JSON olarak yazdır
    print(json.dumps(result, indent=2)) # indent=2 okunaklılık için
