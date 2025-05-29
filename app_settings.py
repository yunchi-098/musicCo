# app_settings.py
import os
import json
import logging
from helpers import _ensure_spotify_uri # Bir önceki adımda oluşturduğumuz helpers.py'dan
import config # Yeni oluşturduğumuz config.py'dan

logger = logging.getLogger(__name__)

def load_app_settings():
    """Ayarları dosyadan yükler, eksik filtre ayarları için varsayılanları ekler."""
    default_settings = {
        'max_queue_length': 20, 'max_user_requests': 5, 'active_device_id': None,
        'genre_filter_mode': 'blacklist', 'artist_filter_mode': 'blacklist', 'song_filter_mode': 'blacklist',
        'genre_blacklist': [], 'genre_whitelist': [],
        'artist_blacklist': [], 'artist_whitelist': [],
        'track_blacklist': [], 'track_whitelist': [],
    }
    settings_to_use = default_settings.copy()
    if os.path.exists(config.SETTINGS_FILE):
        try:
            with open(config.SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            # Eski 'song_' anahtarlarını 'track_' anahtarlarına dönüştür
            if 'song_blacklist' in loaded:
                loaded['track_blacklist'] = loaded.pop('song_blacklist', loaded.get('track_blacklist', []))
            if 'song_whitelist' in loaded:
                loaded['track_whitelist'] = loaded.pop('song_whitelist', loaded.get('track_whitelist', []))
            if 'song_filter_mode' in loaded:
                loaded['track_filter_mode'] = loaded.pop('song_filter_mode', loaded.get('track_filter_mode', 'blacklist'))

            settings_to_use.update(loaded)
            updated = False
            for key, default_value in default_settings.items():
                if key not in settings_to_use:
                    logger.info(f"'{key}' ayarı dosyada bulunamadı, varsayılan değer ({default_value}) ekleniyor.")
                    settings_to_use[key] = default_value
                    updated = True
            
            if 'active_genres' in settings_to_use: # Eski ayarı kaldır
                del settings_to_use['active_genres']
                logger.info("Eski 'active_genres' ayarı kaldırıldı.")
                updated = True

            for key in ['artist_blacklist', 'artist_whitelist', 'track_blacklist', 'track_whitelist']:
                if key in settings_to_use:
                    item_type = 'track' if 'track' in key else 'artist'
                    original_list = settings_to_use[key]
                    if original_list is None: original_list = []
                    
                    converted_list = []
                    changed_in_list = False
                    if not isinstance(original_list, list):
                         logger.warning(f"Ayarlar yüklenirken '{key}' beklenen liste formatında değil: {type(original_list)}. Boş liste ile değiştiriliyor.")
                         original_list = []
                         settings_to_use[key] = []
                         updated = True
                         changed_in_list = True
                         
                    for item in original_list:
                        uri = _ensure_spotify_uri(item, item_type)
                        if uri:
                            converted_list.append(uri)
                            if uri != item: changed_in_list = True
                        else:
                            logger.warning(f"Ayarlar yüklenirken '{key}' listesindeki geçersiz öğe atlandı: {item}")
                            changed_in_list = True
                    if changed_in_list:
                        settings_to_use[key] = sorted(list(set(converted_list)))
                        updated = True
            
            if updated:
                save_app_settings(settings_to_use) # Değişiklik varsa kaydet
            logger.info(f"Ayarlar yüklendi: {config.SETTINGS_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Ayar dosyası ({config.SETTINGS_FILE}) bozuk JSON içeriyor: {e}. Varsayılanlar kullanılacak.")
            settings_to_use = default_settings.copy()
        except Exception as e:
            logger.error(f"Ayar dosyası ({config.SETTINGS_FILE}) okunamadı: {e}. Varsayılanlar kullanılacak.")
            settings_to_use = default_settings.copy()
    else:
        logger.info(f"Ayar dosyası bulunamadı, varsayılanlar oluşturuluyor: {config.SETTINGS_FILE}")
        settings_to_use = default_settings.copy()
        save_app_settings(settings_to_use)
    return settings_to_use

def save_app_settings(current_settings):
    """Ayarları dosyaya kaydeder. Listeleri temizler, URI formatına çevirir ve sıralar."""
    try:
        settings_to_save = current_settings.copy()

        for key_part in ['genre', 'artist', 'track']:
            for list_type in ['blacklist', 'whitelist']:
                key = f"{key_part}_{list_type}"
                if key in settings_to_save:
                    current_list = settings_to_save.get(key, [])
                    if current_list is None: current_list = []
                    
                    if not isinstance(current_list, list):
                        logger.warning(f"Ayarlar kaydedilirken '{key}' beklenen liste formatında değil: {type(current_list)}. Boş liste olarak kaydedilecek.")
                        current_list = []

                    if key_part == 'genre':
                        cleaned_list = sorted(list(set([g.lower() for g in current_list if isinstance(g, str) and g.strip()])))
                    else: # artist or track
                        cleaned_uris = set()
                        item_type_for_uri = key_part
                        for item in current_list:
                            uri = _ensure_spotify_uri(item, item_type_for_uri)
                            if uri:
                                cleaned_uris.add(uri)
                            else:
                                logger.warning(f"Ayarlar kaydedilirken '{key}' listesindeki geçersiz öğe atlandı: {item}")
                        cleaned_list = sorted(list(cleaned_uris))
                    settings_to_save[key] = cleaned_list
        
        with open(config.SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Ayarlar kaydedildi: {config.SETTINGS_FILE}")
    except Exception as e:
        logger.error(f"Ayarları kaydederken hata: {e}", exc_info=True)