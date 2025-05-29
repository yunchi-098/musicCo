# config.py

# --- Spotify API Yapılandırması ---
# !!! BU BİLGİLERİ KENDİ SPOTIFY DEVELOPER BİLGİLERİNİZLE DEĞİŞTİRİN !!!
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'  # ÖRNEK - DEĞİŞTİR
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'  # ÖRNEK - DEĞİŞTİR
# !!! BU URI'NIN SPOTIFY DEVELOPER DASHBOARD'DAKİ REDIRECT URI İLE AYNI OLDUĞUNDAN EMİN OLUN !!!
SPOTIFY_REDIRECT_URI = 'http://100.81.225.104:8080/callback'  # ÖRNEK - DEĞİŞTİR
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private user-read-currently-playing user-read-recently-played'

# --- Dosya Yolları ve Diğer Ayarlar ---
TOKEN_FILE = 'spotify_token.json'
SETTINGS_FILE = 'settings.json'
BLUETOOTH_SCAN_DURATION = 12  # Saniye cinsinden Bluetooth tarama süresi
EX_SCRIPT_PATH = 'ex.py'  # ex.py betiğinin yolu

# Kullanıcı arayüzünde gösterilecek varsayılan türler (opsiyonel)
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie', 'turkish']

# --- Admin Ayarları ---
# Güvenlik için bu şifreyi ortam değişkenlerinden veya daha güvenli bir yapılandırma yönetim sisteminden almanız önerilir.
ADMIN_PASSWORD = "mekan123" # ÖRNEK - DEĞİŞTİRİN