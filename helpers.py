# helpers.py
import re
import subprocess
import json
import logging

# Bu modül için kendi logger'ını oluştur
logger = logging.getLogger(__name__)

# --- Yardımcı Fonksiyon: Spotify URI İşleme ---
def _ensure_spotify_uri(item_id, item_type):
    """
    Verilen ID'yi (veya URL'yi) doğru Spotify URI formatına çevirir veya None döner.
    Şarkılar için her zaman 'spotify:track:' kullanır.
    """
    if not item_id or not isinstance(item_id, str): return None
    item_id = item_id.strip()

    # Şarkı tipi 'song' veya 'track' olabilir, prefix hep 'track' olmalı
    actual_item_type = 'track' if item_type in ['song', 'track'] else item_type
    prefix = f"spotify:{actual_item_type}:"

    # Zaten doğru URI formatındaysa direkt döndür
    if item_id.startswith(prefix): return item_id

    # Sadece ID ise (':' içermiyorsa) prefix ekle
    if ":" not in item_id: return f"{prefix}{item_id}"

    # URL ise ID'yi çıkarmayı dene
    if actual_item_type == 'track' and '/track/' in item_id:
        match = re.search(r'/track/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:track:{match.group(1)}" # Hep track kullan
    elif actual_item_type == 'artist' and '/artist/' in item_id:
        match = re.search(r'/artist/([a-zA-Z0-9]+)', item_id)
        if match:
            return f"spotify:artist:{match.group(1)}"

    # Diğer durumlar geçersiz kabul edilir
    logger.warning(f"Tanınmayan veya geçersiz Spotify {actual_item_type} ID/URI formatı: {item_id}")
    return None

# --- Yardımcı Fonksiyon: Komut Çalıştırma (ex.py ve spotifyd için) ---
def _run_command(command, ex_script_path, timeout=30):
    """Helper function to run shell commands and return parsed JSON or error."""
    try:
        # Komutun 'python3' ile başlayıp başlamadığını kontrol et
        if command[0] == 'python3' and len(command) > 1 and command[1] == ex_script_path:
             full_command = command
        elif command[0] == 'spotifyd' or command[0] == 'pgrep':
             full_command = command
        else:
             # Eğer ex.py komutuysa başına python3 ekle
             full_command = ['python3', ex_script_path] + command

        logger.debug(f"Running command: {' '.join(full_command)}")
        result = subprocess.run(full_command, capture_output=True, text=True, check=True, timeout=timeout, encoding='utf-8')
        logger.debug(f"Command stdout (first 500 chars): {result.stdout[:500]}")
        try:
            # JSON parse etmeyi sadece ex.py çıktısı için yap
            if full_command[0] == 'python3' and full_command[1] == ex_script_path:
                 if not result.stdout.strip():
                      logger.warning(f"Command {' '.join(full_command)} returned empty output.")
                      return {'success': False, 'error': 'Komut boş çıktı döndürdü.'}
                 return json.loads(result.stdout)
            else: # spotifyd veya pgrep gibi diğer komutlar için ham çıktıyı döndür
                 return {'success': True, 'output': result.stdout.strip()}
        except json.JSONDecodeError as json_err:
             logger.error(f"Failed to parse JSON output from command {' '.join(full_command)}: {json_err}")
             logger.error(f"Raw output was: {result.stdout}")
             return {'success': False, 'error': f"Komut çıktısı JSON formatında değil: {json_err}", 'raw_output': result.stdout}
    except FileNotFoundError:
        err_msg = f"Komut bulunamadı: {full_command[0]}. Yüklü ve PATH içinde mi?"
        if full_command[0] == 'python3' and len(full_command) > 1 and full_command[1] == ex_script_path:
             err_msg = f"Python 3 yorumlayıcısı veya '{ex_script_path}' betiği bulunamadı."
        logger.error(err_msg)
        return {'success': False, 'error': err_msg}
    except subprocess.CalledProcessError as e:
        logger.error(f"Command '{' '.join(full_command)}' failed with return code {e.returncode}. Stderr:\n{e.stderr}")
        return {'success': False, 'error': f"Komut hatası (kod {e.returncode})", 'stderr': e.stderr, 'stdout': e.stdout}
    except subprocess.TimeoutExpired:
        logger.error(f"Command '{' '.join(full_command)}' timed out after {timeout} seconds.")
        return {'success': False, 'error': f"Komut zaman aşımına uğradı ({timeout}s)."}
    except Exception as e:
        logger.error(f"Error running command '{' '.join(full_command)}': {e}", exc_info=True)
        return {'success': False, 'error': f"Beklenmedik hata: {e}"}