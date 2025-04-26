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
from datetime import timedelta # Session timeout için eklendi

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


# --- Flask Uygulaması ---

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'varsayilan_cok_guvensiz_anahtar_hemen_degistir')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) # Oturum süresi

# Yönetici şifresi
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'mekan123')

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
    # Paneli render etmeden önce backend'den bazı temel verileri gönderebiliriz.
    # Ancak çoğu veri artık API üzerinden dinamik olarak yükleniyor.
    # Spotify ile ilgili veriler (eğer entegre edilirse) burada gönderilebilir.
    # Örnek:
    # spotify_data = get_spotify_data() # Bu fonksiyonun tanımlanması gerekir
    return render_template('admin_panel.html') # spotify_authenticated=spotify_data.get('auth'), ...

# --- API Rotaları ---

# Her API isteği için yönetici örneklerini oluştur
# Bu, DBus/PulseAudio bağlantılarının her istekte açılıp kapanmasına neden olabilir.
# Alternatif: Uygulama bağlamı (g) veya global nesneler kullanmak (dikkatli olunmalı).
def get_bt_manager():
    return BluetoothManager()

def get_sink_manager():
    return AudioSinkManager()

@app.route('/api/status')
@admin_login_required
def api_status():
    """Genel sistem durumu ve temel bilgileri döndürür."""
    bt_manager = get_bt_manager()
    sink_manager = get_sink_manager()

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
def api_bluetooth_scan():
    """Yeni Bluetooth cihazlarını tarar."""
    scan_duration = request.json.get('duration', 5)
    bt_manager = get_bt_manager()
    log.info(f"{scan_duration} saniyelik Bluetooth taraması başlatılıyor...")
    devices = bt_manager.start_discovery(duration=scan_duration)
    log.info(f"Tarama tamamlandı, {len(devices)} cihaz bulundu/güncellendi.")
    return jsonify({'devices': devices})

@app.route('/api/bluetooth/pair', methods=['POST'])
@admin_login_required
def api_bluetooth_pair():
    """Bir Bluetooth cihazıyla eşleşir."""
    address = request.json.get('address')
    if not address: return jsonify({'success': False, 'message': 'Cihaz adresi belirtilmedi.'}), 400
    bt_manager = get_bt_manager()
    success, message = bt_manager.pair_device(address)
    return jsonify({'success': success, 'message': message})

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
     # Formdan şarkı ID/URL'sini al
     # Spotipy ile şarkıyı kuyruğa ekle (add_to_queue)
     # ... (İlgili kodlar buraya gelecek) ...
     flash("Şarkı ekleme henüz uygulanmadı.", "warning")
     return redirect(url_for('admin_panel'))

@app.route('/remove-song/<song_id>', methods=['POST']) # Kuyruktan şarkı kaldırma (ID ile değil, index ile olabilir?)
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

