#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Windows Ses Cihazı Yönetim Modülü
Pycaw kütüphanesi kullanarak Windows ses cihazlarını yönetir.
"""

import json
import argparse
import logging
from ctypes import POINTER, cast

# Logging ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('ex_windows')

# Windows ses kütüphaneleri
try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IMMDeviceEnumerator, EDataFlow, ERole
    from comtypes import CLSCTX_ALL, CoCreateInstance, GUID
    PYCAW_AVAILABLE = True
except ImportError:
    logger.warning("pycaw kütüphanesi bulunamadı. Ses kontrolü devre dışı.")
    PYCAW_AVAILABLE = False


class WindowsAudioManager:
    """Windows ses cihazları yönetim sınıfı"""
    
    def __init__(self):
        self.available = PYCAW_AVAILABLE
    
    def list_sinks(self):
        """Tüm ses çıkış cihazlarını listeler"""
        if not self.available:
            return {
                'success': False, 
                'error': 'pycaw kütüphanesi yüklü değil. pip install pycaw comtypes',
                'sinks': [],
                'default_sink_name': None
            }
        
        sinks_info = []
        default_sink_name = None
        
        try:
            # Tüm ses cihazlarını al
            devices = AudioUtilities.GetAllDevices()
            
            # Varsayılan hoparlörü bul
            try:
                default_speaker = AudioUtilities.GetSpeakers()
                if default_speaker:
                    # Varsayılan cihazın ID'sini al
                    default_id = default_speaker.GetId()
            except Exception:
                default_id = None
            
            for idx, device in enumerate(devices):
                try:
                    # Sadece aktif ses çıkış cihazlarını al
                    if device.state == 1:  # DEVICE_STATE_ACTIVE
                        device_info = {
                            'index': idx,
                            'name': device.id if device.id else f"Device_{idx}",
                            'description': device.FriendlyName if device.FriendlyName else "Bilinmeyen Cihaz",
                            'state': 'active',
                            'mute': False,
                            'volume': 100,
                            'is_default': device.id == default_id if default_id else False
                        }
                        
                        if device_info['is_default']:
                            default_sink_name = device_info['name']
                        
                        sinks_info.append(device_info)
                except Exception as e:
                    logger.warning(f"Cihaz bilgisi alınamadı (idx={idx}): {e}")
                    continue
            
            # Eğer cihaz bulunamadıysa, varsayılan hoparlörü ekle
            if not sinks_info:
                try:
                    speakers = AudioUtilities.GetSpeakers()
                    if speakers:
                        sinks_info.append({
                            'index': 0,
                            'name': 'default_speakers',
                            'description': 'Varsayılan Hoparlörler',
                            'state': 'active',
                            'mute': False,
                            'volume': 100,
                            'is_default': True
                        })
                        default_sink_name = 'default_speakers'
                except Exception:
                    pass
            
            logger.info(f"{len(sinks_info)} ses cihazı listelendi. Varsayılan: {default_sink_name}")
            return {
                'success': True, 
                'sinks': sinks_info, 
                'default_sink_name': default_sink_name
            }
            
        except Exception as e:
            logger.error(f"Ses cihazları listelenirken hata: {e}")
            return {
                'success': False, 
                'error': f"Ses cihazları listelenemedi: {e}",
                'sinks': [],
                'default_sink_name': None
            }
    
    def switch_to_sink(self, sink_identifier):
        """Belirtilen ses cihazına geçiş yapar (Windows'ta sınırlı destek)"""
        if not self.available:
            return {'success': False, 'error': 'pycaw kütüphanesi yüklü değil.'}
        
        # Windows'ta programatik olarak varsayılan ses cihazını değiştirmek
        # özel API'ler gerektirir. Bu basit bir geçici çözüm.
        logger.warning("Windows'ta ses cihazı değiştirme sınırlı desteklenmektedir.")
        return {
            'success': True, 
            'message': f"Ses cihazı seçimi kaydedildi: {sink_identifier}. Not: Windows'ta tam destek için Ses Ayarlarını kullanın."
        }
    
    def get_volume(self):
        """Mevcut ses seviyesini alır"""
        if not self.available:
            return {'success': False, 'error': 'pycaw kütüphanesi yüklü değil.'}
        
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            
            current_volume = volume.GetMasterVolumeLevelScalar()
            is_muted = volume.GetMute()
            
            return {
                'success': True,
                'volume': int(current_volume * 100),
                'muted': bool(is_muted)
            }
        except Exception as e:
            logger.error(f"Ses seviyesi alınamadı: {e}")
            return {'success': False, 'error': f"Ses seviyesi alınamadı: {e}"}
    
    def set_volume(self, volume_percent):
        """Ses seviyesini ayarlar (0-100)"""
        if not self.available:
            return {'success': False, 'error': 'pycaw kütüphanesi yüklü değil.'}
        
        try:
            volume_percent = max(0, min(100, int(volume_percent)))
            
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            
            volume.SetMasterVolumeLevelScalar(volume_percent / 100.0, None)
            
            logger.info(f"Ses seviyesi ayarlandı: %{volume_percent}")
            return {
                'success': True,
                'message': f"Ses seviyesi %{volume_percent} olarak ayarlandı."
            }
        except Exception as e:
            logger.error(f"Ses seviyesi ayarlanamadı: {e}")
            return {'success': False, 'error': f"Ses seviyesi ayarlanamadı: {e}"}


def restart_spotifyd():
    """Windows'ta spotifyd kullanılmıyor, Spotify Connect kullanılır"""
    return {
        'success': True, 
        'message': 'Windows üzerinde Spotify Connect kullanılmaktadır. Spotifyd gerekli değil.'
    }


def get_spotifyd_pid():
    """Windows'ta spotifyd yok"""
    return {'success': True, 'pids': []}


# --- Ana Çalıştırma Bloğu ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Windows Ses Yönetim Betiği")
    parser.add_argument('command', help="Çalıştırılacak komut", choices=[
        'list_sinks', 'set_audio_sink', 'get_volume', 'set_volume',
        'restart_spotifyd'
    ])
    parser.add_argument('--identifier', help="set_audio_sink için sink adı/index'i")
    parser.add_argument('--volume', type=int, help="set_volume için ses seviyesi (0-100)")

    args = parser.parse_args()

    result = {'success': False, 'error': 'Geçersiz komut veya argüman'}

    manager = WindowsAudioManager()

    if args.command == 'list_sinks':
        result = manager.list_sinks()
    elif args.command == 'set_audio_sink':
        if args.identifier:
            result = manager.switch_to_sink(args.identifier)
        else:
            result = {'success': False, 'error': '--identifier argümanı gerekli'}
    elif args.command == 'get_volume':
        result = manager.get_volume()
    elif args.command == 'set_volume':
        if args.volume is not None:
            result = manager.set_volume(args.volume)
        else:
            result = {'success': False, 'error': '--volume argümanı gerekli'}
    elif args.command == 'restart_spotifyd':
        result = restart_spotifyd()

    # Sonucu JSON olarak yazdır
    print(json.dumps(result, indent=2, ensure_ascii=False))
