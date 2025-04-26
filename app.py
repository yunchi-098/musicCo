#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import subprocess
import threading
import pulsectl
import dbus
import logging
from dbus.mainloop.glib import DBusGMainLoop
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from gi.repository import GLib # deneme.py'den eklendi
from functools import wraps # admin_login_required için

# --- Logging Ayarları ---
# Daha detaylı loglama için yapılandırma
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"), # Logları dosyaya yaz
        logging.StreamHandler() # Logları konsola da yaz
    ]
)
log = logging.getLogger(__name__)

# --- Yardımcı Fonksiyonlar ---

def get_spotifyd_pids():
    """Çalışan spotifyd süreçlerinin PID'lerini bulur."""
    try:
        # pgrep kullanarak spotifyd PID'lerini al
        output = subprocess.check_output(["pgrep", "spotifyd"], universal_newlines=True)
        # Çıktıyı temizle ve PID listesi döndür
        return [int(pid) for pid in output.strip().split("\n") if pid.isdigit()]
    except subprocess.CalledProcessError:
        # Süreç bulunamazsa boş liste döndür
        return []
    except Exception as e:
        log.error(f"Spotifyd PID'leri alınırken hata: {e}")
        return []

def restart_spotifyd():
    """Spotifyd'yi daha güvenilir bir şekilde yeniden başlatır."""
    log.info("Spotifyd yeniden başlatılıyor...")
    pids = get_spotifyd_pids()
    if pids:
        for pid in pids:
            try:
                # Sürece SIGTERM sinyali gönder (daha nazik kapatma)
                os.kill(pid, 15)
                log.info(f"Spotifyd (PID: {pid}) sonlandırıldı (SIGTERM).")
                # Sürecin kapanmasını bekle (timeout ile)
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass # Süreç zaten bitmiş olabilir
            except ProcessLookupError:
                 log.warning(f"Spotifyd (PID: {pid}) sonlandırılırken bulunamadı.")
            except Exception as e:
                log.error(f"Spotifyd (PID: {pid}) sonlandırılırken hata: {e}")
        # Tüm sinyaller gönderildikten sonra biraz bekle
        time.sleep(1)

    # Spotifyd'yi yeniden başlatmayı dene
    try:
        # Kullanıcının ev dizinindeki yapılandırma dosyasını kullanmayı dene
        config_path = os.path.expanduser("~/.config/spotifyd/spotifyd.conf")
        if os.path.exists(config_path):
             # Arka planda çalıştır (--no-daemon olmadan)
            process = subprocess.Popen(["spotifyd", "--config-path", config_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            log.info(f"Spotifyd belirtilen yapılandırma ile başlatıldı: {config_path} (PID: {process.pid})")
        else:
             # Varsayılan ayarlarla başlatmayı dene
            process = subprocess.Popen(["spotifyd"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            log.info(f"Spotifyd varsayılan ayarlarla başlatıldı (PID: {process.pid})")
        # Başlatma sonrası kısa bir bekleme
        time.sleep(2)
        return True
    except FileNotFoundError:
        log.error("spotifyd komutu bulunamadı. PATH ortam değişkeninizi kontrol edin veya spotifyd'yi kurun.")
        return False
    except Exception as e:
        log.error(f"Spotifyd yeniden başlatılırken hata: {e}")
        return False

# --- Bluetooth ve Sink Yöneticileri ---

class BluetoothManager:
    def __init__(self):
        self.bus = None
        self.adapter_path = None
        self.adapter = None
        self.adapter_props = None
        self.device_list = []
        self.mainloop = None # GLib MainLoop için

        try:
            # DBus ana döngüsünü ayarla
            DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop() # Ana döngüyü başlat

            # İlk uygun Bluetooth adaptörünü bul
            om = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = om.GetManagedObjects()
            self.adapter_path = next((path for path, interfaces in objects.items() if 'org.bluez.Adapter1' in interfaces), None)

            if not self.adapter_path:
                 raise Exception("Bluez adaptörü bulunamadı.")

            log.info(f"Kullanılan Bluetooth Adaptörü: {self.adapter_path}")
            adapter_obj = self.bus.get_object('org.bluez', self.adapter_path)
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')

            # Sinyalleri dinlemek için (örneğin, cihaz bağlandığında/çıkarıldığında)
            # self.bus.add_signal_receiver(self._properties_changed, dbus_interface="org.freedesktop.DBus.Properties", signal_name="PropertiesChanged", path_keyword="path", interface_keyword="interface")
            # log.info("Bluetooth özellik değişiklikleri için sinyal alıcısı eklendi.")

        except dbus.exceptions.DBusException as e:
            log.error(f"DBus başlatılırken hata: {e}. Bluetooth servisi çalışıyor mu? (sudo systemctl status bluetooth)")
            self._cleanup() # Hata durumunda kaynakları serbest bırak
        except Exception as e:
             log.error(f"BluetoothManager başlatılırken genel hata: {e}")
             self._cleanup()

    def _cleanup(self):
        """Kaynakları temizler."""
        # Sinyal alıcılarını kaldır (eğer eklenmişse)
        # try:
        #     if self.bus:
        #         self.bus.remove_signal_receiver(self._properties_changed, dbus_interface="org.freedesktop.DBus.Properties", signal_name="PropertiesChanged")
        #         log.info("Bluetooth sinyal alıcısı kaldırıldı.")
        # except Exception as e:
        #     log.warning(f"Sinyal alıcısı kaldırılırken hata: {e}")

        self.bus = None
        self.adapter = None
        self.adapter_props = None
        self.adapter_path = None
        self.device_list = []
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()
        self.mainloop = None
        log.info("BluetoothManager kaynakları temizlendi.")

    def _is_adapter_available(self):
        """Adaptörün başlatılıp başlatılamadığını kontrol eder."""
        return self.adapter is not None and self.adapter_props is not None

    # --- Sinyal İşleyici (Örnek - Şu anda aktif kullanılmıyor) ---
    # def _properties_changed(self, interface, changed_properties, invalidated_properties, path):
    #     """DBus özellik değişikliklerini işler."""
    #     if interface == 'org.bluez.Device1' and 'Connected' in changed_properties:
    #         connected = changed_properties['Connected']
    #         device_info = self.get_device_by_path(path)
    #         if device_info:
    #             status = "bağlandı" if connected else "bağlantısı kesildi"
    #             log.info(f"Sinyal alındı: Cihaz {device_info['name']} ({device_info['address']}) {status}.")
    #             # Burada otomatik sink değiştirme gibi işlemler tetiklenebilir
    #             # Dikkat: Flask request context dışında çalışır, doğrudan Flask session vs. erişilemez.
    #             # Event gönderme veya başka bir mekanizma gerekebilir.
    #             if connected:
    #                 # Bağlantı sonrası işlemleri ayrı bir thread'de yap
    #                 threading.Thread(target=self._handle_connection_event, args=(device_info,)).start()
    #             else:
    #                 # Bağlantı kesilme sonrası işlemleri ayrı bir thread'de yap
    #                 threading.Thread(target=self._handle_disconnection_event, args=(device_info,)).start()

    # def _handle_connection_event(self, device_info):
    #     """Bağlantı olayını işler (ayrı thread)."""
    #     log.info(f"{device_info['name']} için bağlantı sonrası işlemler başlatılıyor...")
    #     time.sleep(4) # Sink'in oluşması için bekle
    #     audio_manager = AudioSinkManager() # Yeni bir instance oluştur
    #     if audio_manager.switch_to_bluetooth_sink(device_info['name']):
    #         log.info(f"{device_info['name']} için ses çıkışı başarıyla değiştirildi.")
    #         # Spotifyd yeniden başlatma (opsiyonel)
    #         # restart_spotifyd()
    #     else:
    #         log.warning(f"{device_info['name']} için uygun ses çıkışı bulunamadı veya değiştirilemedi.")

    # def _handle_disconnection_event(self, device_info):
    #     """Bağlantı kesilme olayını işler (ayrı thread)."""
    #     log.info(f"{device_info['name']} için bağlantı kesilme sonrası işlemler başlatılıyor...")
    #     audio_manager = AudioSinkManager() # Yeni bir instance oluştur
    #     if audio_manager.switch_to_alsa():
    #         log.info("Varsayılan ALSA ses çıkışına geçildi.")
    #         # Spotifyd yeniden başlatma (opsiyonel)
    #         # restart_spotifyd()
    #     else:
    #         log.warning("Varsayılan ALSA ses çıkışına geçilemedi.")

    # def get_device_by_path(self, path):
    #     """Verilen path'e sahip cihazı bulur."""
    #     # Güncel listeyi almak daha güvenli olabilir
    #     current_devices = self.list_devices()
    #     for device in current_devices:
    #         if device['path'] == path:
    #             return device
    #     return None
    # --- Sinyal İşleyici Sonu ---

    def start_discovery(self, duration=5):
        """Bluetooth cihaz keşfini başlatır ve belirtilen süre sonunda durdurur."""
        if not self._is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, tarama başlatılamıyor.")
             return []
        try:
            # Adaptörü aç (zaten açıksa sorun olmaz)
            self.adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
            log.info("Bluetooth adaptörü açıldı (veya zaten açıktı).")

            if not self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                log.info(f"Bluetooth cihaz taraması {duration} saniye için başlatılıyor...")
                self.adapter.StartDiscovery()
            else:
                log.info("Bluetooth cihaz taraması zaten aktif.")

            # Belirtilen süre kadar bekle
            # GLib.timeout_add_seconds(duration, self._stop_discovery_and_list) # Asenkron bekleme
            # self.mainloop.run() # Ana döngüyü çalıştır (tarama bitene kadar bloke eder)
            # NOT: Flask request'i içinde mainloop.run() çalıştırmak sorun yaratabilir.
            # Bu yüzden senkron bekleme kullanıyoruz.
            time.sleep(duration)
            self.stop_discovery() # Süre sonunda taramayı durdur
            return self.list_devices() # Güncel listeyi döndür

        except dbus.exceptions.DBusException as e:
            log.error(f"DBus Hatası (Bluetooth tarama): {e} - Bluetooth servisi çalışıyor mu?")
            # Bluetooth servisini kontrol etmeyi dene
            try:
                subprocess.check_call(["systemctl", "is-active", "--quiet", "bluetooth"])
            except subprocess.CalledProcessError:
                log.warning("Bluetooth servisi çalışmıyor. Başlatmayı deneyin: sudo systemctl start bluetooth")
            except FileNotFoundError:
                log.warning("systemctl komutu bulunamadı. Sisteminizde farklı bir servis yöneticisi olabilir.")
            return []
        except Exception as e:
            log.error(f"Bluetooth tarama sırasında hata: {e}")
            return []

    # def _stop_discovery_and_list(self):
    #     """Taramayı durdurur, listeler ve ana döngüyü sonlandırır (callback)."""
    #     self.stop_discovery()
    #     self.list_devices()
    #     if self.mainloop and self.mainloop.is_running():
    #         self.mainloop.quit()
    #     return False # Tekrar çağrılmasını engelle

    def stop_discovery(self):
        """Bluetooth cihaz keşfini durdurur."""
        if not self._is_adapter_available():
            return
        try:
            if self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                self.adapter.StopDiscovery()
                log.info("Bluetooth cihaz taraması durduruldu.")
        except dbus.exceptions.DBusException as e:
             log.error(f"DBus Hatası (Tarama durdurma): {e}")
        except Exception as e:
            log.error(f"Bluetooth taraması durdurulurken hata: {e}")

    def list_devices(self):
        """Bulunan ve eşleşmiş Bluetooth cihazlarını listeler."""
        if not self._is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, cihazlar listelenemiyor.")
             return []
        devices = []
        try:
            om = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = om.GetManagedObjects()
            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    device_props = interfaces['org.bluez.Device1']
                    # Güvenlik: Her zaman 'Name' ve 'Address' olmayabilir
                    name = device_props.get('Name', 'İsimsiz Cihaz')
                    address = device_props.get('Address', None)
                    if address: # Adres yoksa cihazı ekleme
                        # deneme.py'deki gibi 'audio' kontrolü eklendi
                        is_audio_device = 'org.bluez.MediaTransport1' in interfaces or \
                                        any('Audio' in str(uuid) for uuid in device_props.get('UUIDs', [])) or \
                                        str(device_props.get('Icon', '')).startswith('audio-')

                        devices.append({
                            'path': path,
                            'name': str(name), # dbus.String'i str'ye çevir
                            'address': str(address), # dbus.String'i str'ye çevir
                            'connected': bool(device_props.get('Connected', False)),
                            'paired': bool(device_props.get('Paired', False)),
                            'trusted': bool(device_props.get('Trusted', False)), # Güvenilirlik durumu
                            'audio_device': is_audio_device, # Ses cihazı olup olmadığını belirt
                            'icon': str(device_props.get('Icon', 'bluetooth')), # Cihaz ikonu (varsa)
                            'rssi': int(device_props.get('RSSI', -100)), # Sinyal gücü (varsa)
                        })
            # RSSI'ye göre sırala (en güçlü sinyal en üstte) veya isme göre
            self.device_list = sorted(devices, key=lambda d: (not d['paired'], d['rssi'] < -80, -d['rssi'], d['name']))
            log.info(f"{len(self.device_list)} Bluetooth cihazı listelendi.")
            return self.device_list
        except dbus.exceptions.DBusException as e:
            log.error(f"DBus Hatası (Cihaz listeleme): {e}")
            return []
        except Exception as e:
            log.error(f"Bluetooth cihazları listelenirken hata: {e}")
            return []

    def pair_device(self, device_address):
        """Verilen adresteki cihazla eşleşir."""
        if not self._is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, eşleştirme yapılamıyor.")
             return False, "Bluetooth adaptörü mevcut değil."

        device_to_pair = self._find_device_by_address(device_address)
        if not device_to_pair:
            return False, f"Cihaz bulunamadı: {device_address}"

        if device_to_pair['paired']:
            log.info(f"{device_to_pair['name']} zaten eşleşmiş.")
            # Güvenilir değilse güvenilir yapmayı dene
            if not device_to_pair['trusted']:
                return self.trust_device(device_address)
            return True, f"{device_to_pair['name']} zaten eşleşmiş."

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_pair['path'])
            device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
            props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')

            log.info(f"{device_to_pair['name']} ile eşleştirme başlatılıyor...")
            # Agent kaydı gerekebilir (PIN kodu vs. için), şimdilik basit eşleşme
            device_interface.Pair(timeout=60) # 60 saniye timeout
            log.info("Eşleştirme isteği gönderildi. Cihazdan onay bekleniyor...")
            # Eşleşmenin tamamlanmasını beklemek için bir mekanizma eklenebilir
            # (örn. PropertiesChanged sinyalini dinlemek veya periyodik kontrol)
            time.sleep(10) # Şimdilik basit bekleme

            # Eşleşme durumunu tekrar kontrol et
            paired_status = props_interface.Get('org.bluez.Device1', 'Paired')
            if paired_status:
                log.info("Eşleştirme başarılı!")
                # Eşleşme sonrası güvenilir yap
                return self.trust_device(device_address)
            else:
                log.warning("Eşleştirme denendi ancak cihaz hala eşleşmemiş görünüyor.")
                return False, "Eşleştirme başarısız oldu veya zaman aşımına uğradı."

        except dbus.exceptions.DBusException as e:
            log.error(f"Eşleştirme sırasında DBus hatası: {e}")
            msg = f"Eşleştirme hatası: {e}"
            if "Authentication Failed" in str(e): msg = "Eşleştirme başarısız: Kimlik doğrulama hatası."
            if "Authentication Canceled" in str(e): msg = "Eşleştirme başarısız: Kimlik doğrulama iptal edildi."
            if "Connection Attempt Failed" in str(e): msg = "Eşleştirme başarısız: Bağlantı denemesi başarısız."
            if "already exists" in str(e): # Bazen bu hata eşleşmiş ama güvenilmez demek olabilir
                 log.warning("DBus 'already exists' hatası, güvenilir yapmayı deniyor...")
                 return self.trust_device(device_address)
            return False, msg
        except Exception as e:
            log.error(f"Eşleştirme sırasında genel hata: {e}")
            return False, f"Eşleştirme sırasında beklenmedik hata: {e}"

    def trust_device(self, device_address):
        """Cihazı güvenilir olarak işaretler."""
        if not self._is_adapter_available():
            return False, "Bluetooth adaptörü mevcut değil."

        device_to_trust = self._find_device_by_address(device_address)
        if not device_to_trust:
            return False, f"Cihaz bulunamadı: {device_address}"

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_trust['path'])
            props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            props_interface.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
            log.info(f"{device_to_trust['name']} cihazı güvenilir olarak işaretlendi.")
            return True, f"{device_to_trust['name']} güvenilir yapıldı."
        except dbus.exceptions.DBusException as e:
            log.error(f"Cihaz güvenilir yapılırken DBus hatası: {e}")
            return False, f"Güvenilir yapma hatası: {e}"
        except Exception as e:
            log.error(f"Cihaz güvenilir yapılırken genel hata: {e}")
            return False, f"Güvenilir yapma sırasında beklenmedik hata: {e}"

    def connect_device(self, device_address):
        """Verilen adresteki cihaza bağlanır, gerekirse eşleştirir."""
        if not self._is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, cihaza bağlanılamıyor.")
             return None, "Bluetooth adaptörü mevcut değil."

        device_to_connect = self._find_device_by_address(device_address)
        if not device_to_connect:
             # Cihaz listede yoksa kısa bir tarama yapmayı dene
             log.warning(f"Cihaz {device_address} listede yok, kısa tarama yapılıyor...")
             self.start_discovery(duration=3)
             device_to_connect = self._find_device_by_address(device_address)
             if not device_to_connect:
                 log.error(f"Bağlanılacak cihaz bulunamadı: {device_address}")
                 return None, f"Cihaz bulunamadı: {device_address}"

        if device_to_connect['connected']:
            log.info(f"{device_to_connect['name']} zaten bağlı.")
            # Bağlıysa ve ses cihazıysa sink kontrolü yap
            if device_to_connect['audio_device']:
                audio_manager = AudioSinkManager()
                if not audio_manager.is_sink_active(device_to_connect['name']):
                    log.info(f"Cihaz bağlı ama sink aktif değil, sink'e geçiliyor...")
                    audio_manager.switch_to_bluetooth_sink(device_to_connect['name'])
            return device_to_connect, f"{device_to_connect['name']} zaten bağlı."

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_connect['path'])
            device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
            props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')

            # Eşleşmemiş veya güvenilir değilse önce eşleştir/güvenilir yap
            if not device_to_connect['paired'] or not device_to_connect['trusted']:
                log.info(f"{device_to_connect['name']} eşleşmemiş veya güvenilir değil. Eşleştirme/güvenilir yapma deneniyor...")
                paired, msg = self.pair_device(device_address)
                if not paired:
                    # Eğer 'zaten eşleşmiş' mesajı geldiyse ama güvenilir değilse, güvenilir yapmayı dene
                    if "zaten eşleşmiş" in msg and not device_to_connect['trusted']:
                         trusted, trust_msg = self.trust_device(device_address)
                         if not trusted:
                              return None, f"Eşleşmiş ancak güvenilir yapılamadı: {trust_msg}"
                    else:
                        return None, f"Bağlantı öncesi eşleştirme/güvenilir yapma başarısız: {msg}"
                # Başarılı eşleşme/güvenilir yapma sonrası durumu güncelle
                time.sleep(1) # Değişikliklerin yansıması için kısa bekleme
                device_to_connect['paired'] = props_interface.Get('org.bluez.Device1', 'Paired')
                device_to_connect['trusted'] = props_interface.Get('org.bluez.Device1', 'Trusted')
                if not device_to_connect['paired'] or not device_to_connect['trusted']:
                     log.warning("Eşleştirme/güvenilir yapma sonrası durum hala güncellenmedi.")
                     # Devam etmeyi dene, belki bağlanınca düzelir

            log.info(f"{device_to_connect['name']} cihazına bağlanılıyor...")
            # Bağlantı profillerini kontrol et (opsiyonel, A2DP tercih edilebilir)
            # uuids = props_interface.Get('org.bluez.Device1', 'UUIDs')
            # log.debug(f"Cihaz UUID'leri: {uuids}")
            device_interface.Connect(timeout=30) # 30 saniye timeout
            log.info(f"{device_to_connect['name']} cihazına bağlantı isteği gönderildi.")

            # Bağlantının kurulmasını bekle (PropertiesChanged sinyali veya periyodik kontrol)
            time.sleep(5) # Şimdilik basit bekleme

            # Bağlantı durumunu tekrar kontrol et
            connected_status = props_interface.Get('org.bluez.Device1', 'Connected')
            if connected_status:
                log.info(f"{device_to_connect['name']} cihazına başarıyla bağlandı!")
                device_to_connect['connected'] = True # Yerel durumu güncelle

                # Bağlantı sonrası sink oluşması ve otomatik geçiş (eğer ses cihazıysa)
                if device_to_connect['audio_device']:
                    log.info("Ses cihazı bağlandı, sink'e otomatik geçiş deneniyor...")
                    time.sleep(3) # Sink'in PulseAudio'da görünmesi için ek bekleme
                    audio_manager = AudioSinkManager()
                    if audio_manager.switch_to_bluetooth_sink(device_to_connect['name']):
                        log.info(f"'{device_to_connect['name']}' için ses çıkışı başarıyla değiştirildi.")
                        # Spotifyd'yi yeniden başlat (opsiyonel, bazen gerekebilir)
                        # restart_spotifyd()
                    else:
                        log.warning(f"'{device_to_connect['name']}' için uygun ses çıkışı bulunamadı veya değiştirilemedi.")

                return device_to_connect, f"{device_to_connect['name']} başarıyla bağlandı."
            else:
                log.warning(f"{device_to_connect['name']} cihazına bağlanma denendi ancak hala bağlı değil.")
                return None, "Bağlantı başarısız oldu veya zaman aşımına uğradı."

        except dbus.exceptions.DBusException as e:
            log.error(f"Bağlanma sırasında DBus hatası: {e}")
            msg = f"Bağlantı hatası: {e}"
            if "Operation Already Exists" in str(e) or "Operation In Progress" in str(e):
                 msg = "Bağlantı işlemi zaten devam ediyor."
                 # Durumu tekrar kontrol et
                 time.sleep(2)
                 props_interface = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
                 if props_interface.Get('org.bluez.Device1', 'Connected'):
                      log.info("Cihaz zaten bağlıymış.")
                      device_to_connect['connected'] = True
                      return device_to_connect, f"{device_to_connect['name']} zaten bağlı."
                 else:
                      return None, msg # Hata devam ediyorsa
            if "Connection Attempt Failed" in str(e):
                 msg = "Bağlantı denemesi başarısız oldu. Cihaz açık ve kapsama alanında mı?"
            return None, msg
        except Exception as e:
            log.error(f"Bağlanma sırasında genel hata: {e}")
            return None, f"Bağlanma sırasında beklenmedik hata: {e}"

    def disconnect_device(self, device_address):
        """Verilen adresteki cihazın bağlantısını keser."""
        if not self._is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, bağlantı kesilemiyor.")
             return False, "Bluetooth adaptörü mevcut değil."

        device_to_disconnect = self._find_device_by_address(device_address)
        if not device_to_disconnect:
            return False, f"Cihaz bulunamadı: {device_address}"

        if not device_to_disconnect['connected']:
            log.info(f"{device_to_disconnect['name']} zaten bağlı değil.")
            return True, f"{device_to_disconnect['name']} zaten bağlı değil."

        try:
            device_obj = self.bus.get_object('org.bluez', device_to_disconnect['path'])
            device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')

            log.info(f"{device_to_disconnect['name']} cihazından bağlantı kesiliyor...")
            device_interface.Disconnect()
            log.info(f"{device_to_disconnect['name']} bağlantısı kesildi!")

            # Bağlantı kesildikten sonra varsayılan (ALSA) sink'e geç
            if device_to_disconnect['audio_device']:
                 log.info("Bluetooth ses cihazı bağlantısı kesildi, ALSA'ya geçiliyor...")
                 audio_manager = AudioSinkManager()
                 if audio_manager.switch_to_alsa():
                      log.info("Varsayılan ALSA ses çıkışına geçildi.")
                      # Spotifyd'yi yeniden başlat (opsiyonel)
                      # restart_spotifyd()
                 else:
                      log.warning("Varsayılan ALSA ses çıkışına geçilemedi.")

            return True, f"{device_to_disconnect['name']} bağlantısı kesildi."

        except dbus.exceptions.DBusException as e:
            log.error(f"Bağlantı kesilirken DBus hatası: {e}")
            # Eğer bağlantı zaten yoksa başarılı sayılabilir
            if "Not Connected" in str(e):
                 log.warning("DBus 'Not Connected' hatası, zaten bağlı değilmiş.")
                 return True, f"{device_to_disconnect['name']} zaten bağlı değil."
            return False, f"Bağlantı kesme hatası: {e}"
        except Exception as e:
            log.error(f"Bağlantı kesilirken genel hata: {e}")
            return False, f"Bağlantı kesme sırasında beklenmedik hata: {e}"

    def remove_device(self, device_address):
        """Cihazı sistemden (eşleşmeyi) kaldırır."""
        if not self._is_adapter_available():
             log.error("Bluetooth adaptörü mevcut değil, cihaz kaldırılamıyor.")
             return False, "Bluetooth adaptörü mevcut değil."

        device_to_remove = self._find_device_by_address(device_address)
        if not device_to_remove:
            return False, f"Cihaz bulunamadı: {device_address}"

        try:
            # Önce bağlantıyı kes (eğer bağlıysa)
            if device_to_remove['connected']:
                self.disconnect_device(device_address)
                time.sleep(1) # Bağlantının tamamen kesilmesini bekle

            log.info(f"{device_to_remove['name']} cihazı kaldırılıyor...")
            self.adapter.RemoveDevice(device_to_remove['path'])
            log.info(f"{device_to_remove['name']} cihazı başarıyla kaldırıldı.")
            # Lokal listeyi güncelle
            self.device_list = [d for d in self.device_list if d['address'] != device_address]
            return True, f"{device_to_remove['name']} kaldırıldı."

        except dbus.exceptions.DBusException as e:
            log.error(f"Cihaz kaldırılırken DBus hatası: {e}")
            # Eğer cihaz zaten yoksa başarılı sayılabilir
            if "Does Not Exist" in str(e):
                 log.warning("DBus 'Does Not Exist' hatası, cihaz zaten kaldırılmış.")
                 self.device_list = [d for d in self.device_list if d['address'] != device_address]
                 return True, f"{device_to_remove['name']} zaten kaldırılmış."
            return False, f"Cihaz kaldırma hatası: {e}"
        except Exception as e:
            log.error(f"Cihaz kaldırılırken genel hata: {e}")
            return False, f"Cihaz kaldırma sırasında beklenmedik hata: {e}"

    def _find_device_by_address(self, device_address):
        """Verilen adrese sahip cihazı mevcut listeden bulur."""
        # Güncel listeyi kullanmak daha iyi olabilir, ancak performans için önbelleğe alınmış listeyi kullanıyoruz.
        # Gerekirse: self.list_devices() # Her seferinde listeyi yenile
        for device in self.device_list:
            if device['address'] == device_address:
                return device
        # Listede yoksa, güncel listeyi çekip tekrar dene
        log.debug(f"Cihaz {device_address} önbellekte yok, güncel liste alınıyor...")
        current_devices = self.list_devices()
        for device in current_devices:
             if device['address'] == device_address:
                  return device
        log.warning(f"Cihaz {device_address} güncel listede de bulunamadı.")
        return None

class AudioSinkManager:
    def __init__(self):
        # PulseAudio bağlantısını her işlem için ayrı açmak daha güvenli olabilir
        pass

    def list_sinks(self):
        """Tüm mevcut ses çıkış cihazlarını (sink) listeler ve varsayılanı işaretler."""
        sinks_info = []
        default_sink_name = None
        try:
            with pulsectl.Pulse('sink-lister') as pulse:
                default_sink_info = pulse.server_info().default_sink_name
                log.info(f"Varsayılan PulseAudio Sink: {default_sink_info}")
                sinks = pulse.sink_list()
                if not sinks:
                    log.warning("Hiç ses çıkış cihazı (sink) bulunamadı.")
                    return [], None

                for sink in sinks:
                    sinks_info.append({
                        'index': sink.index,
                        'name': sink.name,
                        'description': sink.description,
                        'is_default': sink.name == default_sink_info,
                        # 'state': str(sink.state), # Çalışıyor, Askıda vb.
                        # 'volume': sink.volume.value_flat # Ortalama ses seviyesi (0.0 - 1.0+)
                    })
                log.info(f"{len(sinks_info)} adet sink listelendi.")
                return sinks_info, default_sink_info
        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (list_sinks): {e}")
             # PulseAudio servisini kontrol et
             try:
                 subprocess.check_call(["systemctl", "--user", "is-active", "--quiet", "pulseaudio"])
             except (subprocess.CalledProcessError, FileNotFoundError):
                 log.warning("PulseAudio servisi çalışmıyor veya bulunamadı. (systemctl --user status pulseaudio)")
             return [], None
        except Exception as e:
            log.error(f"Ses cihazları listelenirken hata oluştu: {e}")
            return [], None

    def switch_to_sink(self, sink_identifier):
        """Belirtilen sink'e (index veya isim ile) geçiş yapar."""
        target_sink = None
        try:
            with pulsectl.Pulse('sink-switcher') as pulse:
                sinks = pulse.sink_list()
                if isinstance(sink_identifier, int):
                    # Index ile bulma
                    target_sink = next((s for s in sinks if s.index == sink_identifier), None)
                    if not target_sink:
                         log.error(f"Geçersiz sink indeksi: {sink_identifier}")
                         return False, f"Geçersiz sink indeksi: {sink_identifier}"
                elif isinstance(sink_identifier, str):
                    # İsim veya açıklama ile bulma (büyük/küçük harf duyarsız)
                    identifier_lower = sink_identifier.lower()
                    target_sink = next((s for s in sinks if identifier_lower in s.name.lower() or identifier_lower in s.description.lower()), None)
                    if not target_sink:
                        log.error(f"'{sink_identifier}' isimli/açıklamalı sink bulunamadı!")
                        return False, f"Sink bulunamadı: {sink_identifier}"
                else:
                    log.error(f"Geçersiz sink tanımlayıcı türü: {type(sink_identifier)}")
                    return False, "Geçersiz sink tanımlayıcı türü."

                log.info(f"Ses çıkışı '{target_sink.description}' (Index: {target_sink.index}) cihazına yönlendiriliyor...")

                # Tüm aktif ses girişlerini (uygulamaları) yeni sink'e taşı
                moved_inputs = 0
                for stream in pulse.sink_input_list():
                    try:
                        pulse.sink_input_move(stream.index, target_sink.index)
                        log.debug(f"Sink input {stream.index} ({stream.proplist.get('application.name', 'Bilinmeyen')}) taşındı.")
                        moved_inputs += 1
                    except pulsectl.PulseOperationFailed as op_err:
                         # Bazı streamler taşınamayabilir, hatayı logla ama devam et
                         log.warning(f"Sink input {stream.index} taşınırken hata: {op_err}")

                # Varsayılan sink'i değiştir
                pulse.default_set(target_sink)

                log.info(f"Ses çıkışı '{target_sink.description}' olarak ayarlandı. {moved_inputs} uygulama taşındı.")
                return True, f"Ses çıkışı '{target_sink.description}' olarak ayarlandı."
        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (switch_to_sink): {e}")
             return False, f"PulseAudio hatası: {e}"
        except Exception as e:
            log.error(f"Sink değiştirilirken hata oluştu: {e}")
            return False, f"Beklenmedik hata: {e}"

    def find_sink_by_device_name(self, device_name):
        """Bluetooth cihaz adına göre ilgili sink'i bulur."""
        try:
            with pulsectl.Pulse('bt-sink-finder') as pulse:
                device_name_lower = device_name.lower()
                # Bluez sink isimleri genellikle 'bluez_sink.XX_XX_XX_XX_XX_XX.a2dp_sink' formatındadır.
                # Açıklamada ise cihaz adı geçer.
                for sink in pulse.sink_list():
                    if device_name_lower in sink.description.lower() or \
                       f"bluez_sink.{device_name_lower.replace(':', '_')}" in sink.name.lower():
                        log.info(f"'{device_name}' için uygun sink bulundu: {sink.description} ({sink.name})")
                        return sink
                log.warning(f"'{device_name}' için uygun sink bulunamadı.")
                return None
        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (find_sink_by_device_name): {e}")
             return None
        except Exception as e:
            log.error(f"Cihaz için sink aranırken hata: {e}")
            return None

    def switch_to_bluetooth_sink(self, device_name):
        """Verilen Bluetooth cihazının sink'ine geçiş yapar."""
        target_sink = self.find_sink_by_device_name(device_name)
        if target_sink:
            success, msg = self.switch_to_sink(target_sink.index)
            return success
        return False

    def switch_to_alsa(self):
        """ALSA (genellikle dahili/analog) sink'ine geçiş yapar."""
        log.info("Varsayılan ALSA sink'ine geçiş yapılıyor...")
        alsa_sink = None
        try:
            with pulsectl.Pulse('alsa-finder') as pulse:
                sinks = pulse.sink_list()
                # Genellikle 'alsa_output', 'analog-stereo' içeren veya 'Built-in Audio' gibi açıklamalara sahip olanı bul
                possible_sinks = [
                    s for s in sinks if
                    "alsa_output" in s.name.lower() or
                    "analog-stereo" in s.name.lower() or
                    "hdmi" not in s.name.lower() # HDMI çıkışlarını hariç tut
                ]
                # Daha spesifik arama: Açıklamada 'Built-in' veya 'Dahili' geçen
                built_in_sinks = [s for s in possible_sinks if "built-in" in s.description.lower() or "dahili" in s.description.lower()]

                if built_in_sinks:
                    alsa_sink = built_in_sinks[0] # İlk bulunan dahili olanı seç
                elif possible_sinks:
                    alsa_sink = possible_sinks[0] # Bulunamazsa ilk olası ALSA'yı seç
                else:
                    # Hiçbiri bulunamazsa ilk sink'i dene (Bluetooth olmayan)
                    non_bt_sinks = [s for s in sinks if "bluez" not in s.name.lower()]
                    if non_bt_sinks:
                         alsa_sink = non_bt_sinks[0]
                    else: # Sadece BT varsa veya hiç sink yoksa
                         log.warning("Uygun bir ALSA veya varsayılan sink bulunamadı.")
                         return False, "Uygun ALSA sink bulunamadı."

            if alsa_sink:
                log.info(f"Hedef ALSA sink: {alsa_sink.description} (Index: {alsa_sink.index})")
                return self.switch_to_sink(alsa_sink.index)
            else:
                # Bu duruma normalde gelinmemeli
                return False, "ALSA sink belirlenemedi."

        except pulsectl.PulseError as e:
             log.error(f"PulseAudio ile iletişim hatası (switch_to_alsa): {e}")
             return False, f"PulseAudio hatası: {e}"
        except Exception as e:
            log.error(f"ALSA cihazına geçiş yapılırken hata oluştu: {e}")
            return False, f"Beklenmedik hata: {e}"

    def is_sink_active(self, sink_name_or_description):
        """Verilen sink'in şu anda varsayılan olup olmadığını kontrol eder."""
        _, default_sink_name = self.list_sinks()
        if not default_sink_name:
            return False # Varsayılan sink bilgisi alınamadı

        try:
            with pulsectl.Pulse('sink-checker') as pulse:
                 # Önce isimle tam eşleşme kontrolü
                 if sink_name_or_description == default_sink_name:
                      return True
                 # Sonra açıklama ile kontrol (büyük/küçük harf duyarsız)
                 default_sink = pulse.get_sink_by_name(default_sink_name)
                 if sink_name_or_description.lower() in default_sink.description.lower():
                      return True
        except Exception as e:
            log.error(f"Aktif sink kontrol edilirken hata: {e}")
        return False


# --- Flask Uygulaması ---

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_cok_guvensiz_anahtar_hemen_degistir')

# Yönetici şifresini ortam değişkeninden veya varsayılan bir değerden al
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'mekan123') # TODO: Güvenli bir varsayılan veya yapılandırma dosyası kullanın

# Yöneticileri başlat
# Not: Bu nesnelerin her istekte yeniden oluşturulması yerine
# uygulama başlangıcında bir kez oluşturulması daha verimli olabilir,
# ancak DBus/PulseAudio bağlantılarının yönetimi karmaşıklaşabilir.
# Şimdilik her istekte oluşturma yöntemini koruyoruz.
# bt_manager = BluetoothManager() # Uygulama context'i dışında başlatmak sorun olabilir
# sink_manager = AudioSinkManager()

# --- Admin Giriş Koruması ---

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Bu sayfayı görüntülemek için yönetici girişi yapmalısınız.', 'warning')
            return redirect(url_for('admin_login_page')) # admin_login_page olarak değiştirildi
        return f(*args, **kwargs)
    return decorated_function

# --- Web Sayfaları ---

@app.route('/')
def index():
    # Ana sayfa doğrudan admin paneline yönlendirebilir veya
    # kullanıcılar için ayrı bir arayüz (örn. şarkı isteme) sunabilir.
    # Şimdilik admin paneline yönlendiriyoruz.
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    else:
        # Kullanıcı arayüzü varsa buraya yönlendirilebilir:
        # return redirect(url_for('request_song_page'))
        # Şimdilik giriş sayfasına yönlendir
        return redirect(url_for('admin_login_page'))

@app.route('/login', methods=['GET', 'POST']) # /admin yerine /login daha standart
def admin_login_page():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        password_attempt = request.form.get('password')
        if password_attempt == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session.permanent = True # Oturumun kalıcı olmasını sağla (tarayıcı kapanınca silinmez)
            app.permanent_session_lifetime = timedelta(days=7) # Oturum süresi (örn. 7 gün)
            log.info("Yönetici girişi başarılı.")
            flash('Giriş başarılı!', 'success')
            return redirect(url_for('admin_panel'))
        else:
            log.warning(f"Başarısız yönetici girişi denemesi.")
            flash('Yanlış şifre. Lütfen tekrar deneyin.', 'danger')
            # Başarısız denemeler sonrası bekleme eklenebilir (rate limiting)
            time.sleep(1)
            return render_template('admin.html'), 401 # Yetkisiz erişim kodu

    # GET isteği için giriş sayfasını göster
    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None) # Oturumdan sadece admin bilgisini sil
    log.info("Yönetici çıkışı yapıldı.")
    flash('Başarıyla çıkış yaptınız.', 'info')
    return redirect(url_for('admin_login_page'))

@app.route('/admin/panel') # Daha açıklayıcı URL
@admin_login_required
def admin_panel():
    # Panel için gerekli başlangıç verilerini burada yükleyebiliriz
    # Örneğin, mevcut sink listesi, eşleşmiş cihazlar vb.
    # Ancak bu verileri API üzerinden dinamik olarak almak daha iyi olabilir.
    return render_template('admin_panel.html') # admin_panel.html'in bu yeni API'leri kullanacak şekilde güncellenmesi gerekecek

# --- API Rotaları (Admin Paneli İçin) ---

@app.route('/api/status')
@admin_login_required
def api_status():
    """Genel sistem durumu ve temel bilgileri döndürür."""
    bt_manager = BluetoothManager() # İstek başına oluştur
    sink_manager = AudioSinkManager() # İstek başına oluştur
    sinks, default_sink = sink_manager.list_sinks()
    paired_devices = [d for d in bt_manager.list_devices() if d['paired']]
    bt_manager._cleanup() # Kaynakları serbest bırak

    return jsonify({
        'bluetooth_adapter_available': bt_manager._is_adapter_available(), # bt_manager tekrar oluşturulduğu için None olabilir, düzeltilmeli
        'pulseaudio_available': bool(sinks), # Sink listesi alınabildiyse PulseAudio çalışıyor demektir
        'sinks': sinks,
        'default_sink_name': default_sink,
        'paired_bluetooth_devices': paired_devices,
        # Spotify durumu eklenebilir
    })

@app.route('/api/bluetooth/devices')
@admin_login_required
def api_bluetooth_devices():
    """Eşleşmiş ve mevcut Bluetooth cihazlarını listeler."""
    bt_manager = BluetoothManager()
    devices = bt_manager.list_devices()
    bt_manager._cleanup()
    return jsonify({'devices': devices})

@app.route('/api/bluetooth/scan', methods=['POST'])
@admin_login_required
def api_bluetooth_scan():
    """Yeni Bluetooth cihazlarını tarar."""
    scan_duration = request.json.get('duration', 5) # İsteğe bağlı süre
    bt_manager = BluetoothManager()
    log.info(f"{scan_duration} saniyelik Bluetooth taraması başlatılıyor...")
    devices = bt_manager.start_discovery(duration=scan_duration)
    # Tarama sonrası listeyi döndür (start_discovery zaten döndürüyor)
    bt_manager._cleanup()
    log.info(f"Tarama tamamlandı, {len(devices)} cihaz bulundu/güncellendi.")
    return jsonify({'devices': devices})

@app.route('/api/bluetooth/pair', methods=['POST'])
@admin_login_required
def api_bluetooth_pair():
    """Bir Bluetooth cihazıyla eşleşir."""
    address = request.json.get('address')
    if not address:
        return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = BluetoothManager()
    success, message = bt_manager.pair_device(address)
    bt_manager._cleanup()
    return jsonify({'success': success, 'message': message})

@app.route('/api/bluetooth/connect', methods=['POST'])
@admin_login_required
def api_bluetooth_connect():
    """Bir Bluetooth cihazına bağlanır (gerekirse eşleştirir ve sink'e geçer)."""
    address = request.json.get('address')
    if not address:
        return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = BluetoothManager()
    device_info, message = bt_manager.connect_device(address)
    bt_manager._cleanup() # Bağlantı sonrası cleanup
    return jsonify({'success': bool(device_info), 'message': message, 'device': device_info})

@app.route('/api/bluetooth/disconnect', methods=['POST'])
@admin_login_required
def api_bluetooth_disconnect():
    """Bir Bluetooth cihazının bağlantısını keser (ve ALSA'ya geçer)."""
    address = request.json.get('address')
    if not address:
        return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = BluetoothManager()
    success, message = bt_manager.disconnect_device(address)
    bt_manager._cleanup()
    return jsonify({'success': success, 'message': message})

@app.route('/api/bluetooth/remove', methods=['POST'])
@admin_login_required
def api_bluetooth_remove():
    """Bir Bluetooth cihazını sistemden kaldırır."""
    address = request.json.get('address')
    if not address:
        return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = BluetoothManager()
    success, message = bt_manager.remove_device(address)
    bt_manager._cleanup()
    return jsonify({'success': success, 'message': message})


@app.route('/api/audio/sinks')
@admin_login_required
def api_audio_sinks():
    """Mevcut ses çıkış cihazlarını (sink) listeler."""
    sink_manager = AudioSinkManager()
    sinks, default_sink = sink_manager.list_sinks()
    return jsonify({'sinks': sinks, 'default_sink_name': default_sink})

@app.route('/api/audio/switch_sink', methods=['POST'])
@admin_login_required
def api_audio_switch_sink():
    """Belirtilen ses çıkış cihazına (sink) geçer."""
    sink_identifier = request.json.get('sink_identifier') # index (int) veya name/description (str) olabilir
    if sink_identifier is None:
        return jsonify({'success': False, 'message': 'Sink tanımlayıcı belirtilmedi.'}), 400

    # Gelen verinin türüne göre int'e çevirme (eğer sayısal bir string ise)
    if isinstance(sink_identifier, str) and sink_identifier.isdigit():
         sink_identifier = int(sink_identifier)

    sink_manager = AudioSinkManager()
    success, message = sink_manager.switch_to_sink(sink_identifier)
    return jsonify({'success': success, 'message': message})

@app.route('/api/audio/switch_alsa', methods=['POST'])
@admin_login_required
def api_audio_switch_alsa():
    """Varsayılan ALSA ses çıkış cihazına geçer."""
    sink_manager = AudioSinkManager()
    success, message = sink_manager.switch_to_alsa()
    # ALSA'ya geçiş sonrası spotifyd yeniden başlatılabilir
    # if success:
    #     restart_spotifyd()
    return jsonify({'success': success, 'message': message})


@app.route('/api/spotifyd/restart', methods=['POST'])
@admin_login_required
def api_spotifyd_restart():
    """Spotifyd servisini yeniden başlatır."""
    log.info("API üzerinden Spotifyd yeniden başlatma isteği alındı.")
    success = restart_spotifyd()
    message = "Spotifyd başarıyla yeniden başlatıldı." if success else "Spotifyd yeniden başlatılamadı. Logları kontrol edin."
    return jsonify({'success': success, 'message': message})

# --- Uygulamayı Başlat ---

if __name__ == "__main__":
    log.info("Flask uygulaması başlatılıyor...")
    # Gerekli kontroller (opsiyonel)
    try:
        subprocess.check_call(["systemctl", "--user", "is-active", "--quiet", "pulseaudio.socket"])
        log.info("PulseAudio soketi aktif.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.warning("PulseAudio soketi aktif değil veya kontrol edilemedi. Ses sorunları yaşanabilir.")

    try:
        subprocess.check_call(["systemctl", "is-active", "--quiet", "bluetooth.service"])
        log.info("Bluetooth servisi aktif.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.warning("Bluetooth servisi aktif değil veya kontrol edilemedi. Bluetooth özellikleri çalışmayabilir.")

    # Uygulamayı çalıştır
    # debug=True geliştirme sırasında kullanışlıdır, production'da False yapın.
    # use_reloader=False, debug=True ile birlikte çakışmaları önleyebilir.
    # threaded=True, birden fazla isteği aynı anda işlemek için (DBus/GLib ile dikkatli kullanılmalı)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True, use_reloader=False)

    # Uygulama kapanırken kaynakları temizle (bu kısım normalde çalışmaz, sinyal yakalama gerekir)
    # try:
    #     # Eğer global bt_manager tanımlıysa
    #     if 'bt_manager' in globals() and bt_manager:
    #          bt_manager._cleanup()
    # except NameError:
    #      pass # Tanımlı değilse geç
    # log.info("Flask uygulaması durduruldu.")

