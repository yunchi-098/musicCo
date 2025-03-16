import os
import json
import threading
import time
import logging
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Loglama yapılandırması
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'mekanmuzikuygulamasi'  # Gerçek uygulamada güvenli bir şekilde değiştirin

# Spotify API bilgileri
SPOTIFY_CLIENT_ID = '332e5f2c9fe44d9b9ef19c49d0caeb78'
SPOTIFY_CLIENT_SECRET = 'bbb19ad9c7d04d738f61cd0bd4f47426'
SPOTIFY_REDIRECT_URI = 'http://192.168.1.103:8080/callback'
SPOTIFY_SCOPE = 'user-read-playback-state user-modify-playback-state playlist-read-private'

# Token bilgisini saklayacağımız dosya
TOKEN_FILE = 'spotify_token.json'

# İzin verilen müzik türleri
ALLOWED_GENRES = ['pop', 'rock', 'jazz', 'electronic', 'hip-hop', 'classical', 'r&b', 'indie']

# Kullanıcı ayarları dosyası
SETTINGS_FILE = 'settings.json'

# Varsayılan ayarlar
default_settings = {
    'max_queue_length': 20,
    'max_user_requests': 2,
    'active_device_id': None,
    'active_genres': ALLOWED_GENRES
}

# Global değişkenler
spotify_client = None
song_queue = []
user_requests = {}  # Kullanıcı IP adreslerine göre istek sayısı

# Ayarları yükle
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    else:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(default_settings, f)
        return default_settings

# Token bilgisini dosyadan yükle
def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Token dosyasını okuma hatası: {e}")
    return None

# Token bilgisini dosyaya kaydet
def save_token(token_info):
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_info, f)
        logger.info("Token dosyaya kaydedildi")
    except Exception as e:
        logger.error(f"Token kaydetme hatası: {e}")

settings = load_settings()

def get_spotify_auth():
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        open_browser=False,  # Tarayıcı açılmasını önle
        cache_path=None  # Spotipy'nin kendi önbelleğini kullanmıyoruz
    )

def get_spotify_client():
    global spotify_client
    
    # Eğer mevcut bir spotify_client varsa ve çalışıyorsa, onu kullan
    if spotify_client:
        try:
            # Test için basit bir işlem yap
            spotify_client.current_user()
            return spotify_client
        except:
            logger.warning("Mevcut Spotify istemcisi geçersiz. Yenileniyor...")
    
    # Token bilgisini yüklemeyi dene
    token_info = load_token()
    if not token_info:
        logger.warning("Token bilgisi bulunamadı. Lütfen yeniden yetkilendirin.")
        return None
    
    # Token'ın geçerliliğini kontrol et ve gerekirse yenile
    auth_manager = get_spotify_auth()
    try:
        if auth_manager.is_token_expired(token_info):
            logger.info("Token süresi dolmuş, yenileniyor...")
            token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            save_token(token_info)
        
        # Yeni bir Spotify istemcisi oluştur
        spotify_client = spotipy.Spotify(auth=token_info['access_token'])
        logger.info("Spotify istemcisi başarıyla oluşturuldu.")
        return spotify_client
    except Exception as e:
        logger.error(f"Token işlemi sırasında hata: {e}")
        return None

# Admin giriş kontrolü için decorator
def admin_login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            logger.warning("Yetkisiz admin paneli erişim girişimi")
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html', allowed_genres=settings['active_genres'])

@app.route('/admin')
def admin():
    # Eğer zaten giriş yapılmışsa direkt panel sayfasına yönlendir
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    if request.form.get('password') == 'mekan123':  # Basit parola kontrolü
        session['admin_logged_in'] = True
        logger.info("Admin girişi başarılı")
        return redirect(url_for('admin_panel'))
    logger.warning("Başarısız admin girişi denemesi")
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    spotify = get_spotify_client()
    devices = []
    
    # Eğer token yoksa yönlendirme yap
    if not spotify:
        logger.warning("Admin paneline erişim için Spotify yetkilendirmesi gerekli")
        return redirect(url_for('spotify_auth'))
    
    try:
        result = spotify.devices()
        devices = result.get('devices', [])
        logger.info(f"Bulunan cihazlar: {len(devices)}")
    except Exception as e:
        logger.error(f"Cihazları listelerken hata: {e}")
        # Token hatası durumunda yeniden yetkilendirme gerekebilir
        if "unauthorized" in str(e).lower():
            return redirect(url_for('spotify_auth'))
    
    return render_template(
        'admin_panel.html', 
        settings=settings,
        devices=devices,
        queue=song_queue,
        all_genres=ALLOWED_GENRES
    )

@app.route('/update-settings', methods=['POST'])
@admin_login_required
def update_settings():
    settings['max_queue_length'] = int(request.form.get('max_queue_length', 20))
    settings['max_user_requests'] = int(request.form.get('max_user_requests', 2))
    settings['active_device_id'] = request.form.get('active_device_id')
    settings['active_genres'] = [genre for genre in ALLOWED_GENRES if request.form.get(f'genre_{genre}')]
    
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)
    
    logger.info(f"Ayarlar güncellendi: {settings}")
    return redirect(url_for('admin_panel'))

@app.route('/spotify-auth')
@admin_login_required
def spotify_auth():
    try:
        auth_manager = get_spotify_auth()
        auth_url = auth_manager.get_authorize_url()
        logger.info(f"Spotify yetkilendirme URL'si: {auth_url}")
        html = f"""
        <h1>Spotify Yetkilendirme</h1>
        <p>Aşağıdaki bağlantıya tıklayarak Spotify yetkilendirme sayfasına gidin:</p>
        <a href="{auth_url}" target="_blank">Spotify'da Yetkilendir</a>
        <p>Yetkilendirme tamamlandıktan sonra callback URL'ye yönlendirileceksiniz.</p>
        """
        return html
    except Exception as e:
        logger.error(f"Spotify yetkilendirme hatası: {e}")
        return f"Hata: {str(e)}"

@app.route('/callback')
def callback():
    # Callback için admin kontrolü yapma (Spotify tarafından geldiği için)
    # Ancak, session'ı kontrol et - eğer admin giriş yapmamışsa işlem sonrası 
    # admin sayfasına yönlendir
    admin_logged_in = session.get('admin_logged_in', False)
    
    auth_manager = get_spotify_auth()
    if 'code' not in request.args:
        logger.error("Callback'te kod parametresi bulunamadı")
        return redirect(url_for('admin'))
    
    code = request.args.get('code')
    try:
        # Yetkilendirme kodu ile token al
        token_info = auth_manager.get_access_token(code)
        
        # Token doğrulaması
        spotify = spotipy.Spotify(auth=token_info['access_token'])
        try:
            user_profile = spotify.current_user()
            logger.info(f"Token doğrulandı. Kullanıcı: {user_profile.get('display_name')}")
            
            # Token'ı dosyaya kaydet
            save_token(token_info)
            
            global spotify_client
            spotify_client = spotify
            
            logger.info("Spotify yetkilendirme başarılı, token kaydedildi")
            
            # Admin giriş yapmışsa admin paneline, değilse ana sayfaya yönlendir
            if admin_logged_in:
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('index'))
        except Exception as validation_error:
            logger.error(f"Token doğrulama hatası: {validation_error}")
            return redirect(url_for('admin'))
    except Exception as e:
        logger.error(f"Token alırken hata: {e}")
        return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    global spotify_client
    spotify_client = None
    
    # Admin oturumunu sonlandır
    session.pop('admin_logged_in', None)
    session.clear()
    
    # Token dosyasını sil (opsiyonel)
    if os.path.exists(TOKEN_FILE):
        try:
            os.remove(TOKEN_FILE)
            logger.info("Token dosyası silindi")
        except Exception as e:
            logger.error(f"Token dosyası silinirken hata: {e}")
    
    return redirect(url_for('admin'))

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search_query')
    genre_filter = request.form.get('genre_filter')
    logger.info(f"Arama: '{search_query}', Tür: '{genre_filter}'")
    
    if genre_filter not in settings['active_genres']:
        logger.warning(f"İzin verilmeyen tür: {genre_filter}")
        return jsonify({'error': 'Bu müzik türü şu anda izin verilen listede değil'})
    
    user_ip = request.remote_addr
    if user_ip in user_requests and user_requests[user_ip] >= settings['max_user_requests']:
        logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip}")
        return jsonify({'error': 'Maksimum şarkı ekleme limitine ulaştınız'})
    
    spotify = get_spotify_client()
    if not spotify:
        logger.error("Arama için Spotify oturumu bulunamadı")
        return jsonify({'error': 'Spotify oturumu bulunamadı'})
    
    try:
        results = spotify.search(q=f'{search_query} genre:{genre_filter}', type='track', limit=10)
        tracks = results['tracks']['items']
        logger.info(f"Arama sonuçları: {len(tracks)} şarkı bulundu")
        search_results = []
        for track in tracks:
            search_results.append({
                'id': track['id'],
                'name': track['name'],
                'artist': track['artists'][0]['name'],
                'album': track['album']['name'],
                'image': track['album']['images'][0]['url'] if track['album']['images'] else None
            })
        return jsonify({'results': search_results})
    except Exception as e:
        logger.error(f"Spotify araması sırasında hata: {e}")
        return jsonify({'error': f'Arama hatası: {str(e)}'})

@app.route('/add-to-queue', methods=['POST'])
def add_to_queue():
    if not request.is_json:
        logger.error("İstek JSON formatında değil")
        return jsonify({'error': 'İstek JSON formatında olmalıdır'}), 400
    
    data = request.get_json()
    logger.info(f"Kuyruk ekleme isteği alındı: {data}")
    
    if not data or 'track_id' not in data:
        logger.error("İstekte track_id bulunamadı")
        return jsonify({'error': 'Geçersiz istek, track_id gerekli'}), 400
    
    if len(song_queue) >= settings['max_queue_length']:
        logger.warning("Kuyruk maksimum kapasitede")
        return jsonify({'error': 'Şarkı kuyruğu dolu'})
    
    user_ip = request.remote_addr
    if user_ip not in user_requests:
        user_requests[user_ip] = 0
    if user_requests[user_ip] >= settings['max_user_requests']:
        logger.warning(f"Kullanıcı istek limiti aşıldı: {user_ip}")
        return jsonify({'error': 'Maksimum şarkı ekleme limitine ulaştınız'})
    
    spotify = get_spotify_client()
    if not spotify:
        logger.error("Kuyruk ekleme için Spotify oturumu bulunamadı")
        return jsonify({'error': 'Spotify oturumu bulunamadı'})
    
    try:
        track = spotify.track(data['track_id'])
        song_queue.append({
            'id': data['track_id'],
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'added_by': user_ip,
            'added_at': time.time()
        })
        user_requests[user_ip] += 1
        logger.info(f"Şarkı kuyruğa eklendi: {track['name']} - {track['artists'][0]['name']}")
        logger.info(f"Güncel kuyruk uzunluğu: {len(song_queue)}")
        return jsonify({'success': True, 'message': 'Şarkı kuyruğa eklendi'})
    except Exception as e:
        logger.error(f"Spotify şarkı bilgisi alırken hata: {e}")
        return jsonify({'error': f'Sağlanan track bilgisi alınamadı: {str(e)}'}), 500

@app.route('/queue')
def view_queue():
    return render_template('queue.html', queue=song_queue)

@app.route('/api/queue')
def api_get_queue():
    return jsonify({
        'queue': song_queue,
        'queue_length': len(song_queue),
        'max_length': settings['max_queue_length']
    })

@app.route('/clear-queue')
@admin_login_required
def clear_queue():
    global song_queue
    song_queue = []
    logger.info("Şarkı kuyruğu temizlendi")
    return redirect(url_for('admin_panel'))

@app.route('/check-auth-status')
def check_auth_status():
    is_admin = session.get('admin_logged_in', False)
    spotify = get_spotify_client()
    
    if spotify:
        try:
            user = spotify.current_user()
            return jsonify({
                'admin_logged_in': is_admin,
                'spotify_authenticated': True,
                'user': user.get('display_name')
            })
        except:
            pass
    
    return jsonify({
        'admin_logged_in': is_admin,
        'spotify_authenticated': False
    })

def play_queue():
    global spotify_client
    
    while True:
        # Spotify istemcisini düzenli olarak kontrol et ve gerekirse yenile
        spotify = get_spotify_client()
        
        if not spotify:
            logger.warning("Spotify istemcisi bulunamadı, çalma yapılamıyor")
            time.sleep(10)  # Daha uzun bir bekleme süresi
            continue
        
        if song_queue and settings['active_device_id']:
            try:
                current_playback = spotify.current_playback()
            except Exception as e:
                logger.error(f"Playback durumu kontrol hatası: {e}")
                # Token yenilemeyi zorla
                spotify_client = None
                time.sleep(5)
                continue

            if current_playback is None or not current_playback.get('is_playing'):
                # Eğer çalan bir şarkı yoksa, sıradaki şarkıyı başlat
                if song_queue:  # Kuyruk hala dolu mu kontrol et
                    next_song = song_queue.pop(0)
                    try:
                        spotify.start_playback(
                            device_id=settings['active_device_id'],
                            uris=[f"spotify:track:{next_song['id']}"]
                        )
                        logger.info(f"Şarkı çalıyor: {next_song['name']} - {next_song['artist']}")
                        # İlgili kullanıcının istek sayısını azalt
                        user_ip = next_song['added_by']
                        if user_ip in user_requests:
                            user_requests[user_ip] = max(0, user_requests[user_ip] - 1)
                    except Exception as e:
                        logger.error(f"Şarkı çalma hatası: {e}")
                        # Hata türüne göre işlem yap
                        if "not active" in str(e).lower():
                            logger.warning("Cihaz aktif değil. Cihaz durumunu kontrol edin.")
                            # Cihazlar listesini güncelle?
                        else:
                            # Şarkıyı tekrar kuyruğa ekle
                            song_queue.insert(0, next_song)
            else:
                # Mevcut şarkının ilerlemesini kontrol et
                progress = current_playback.get('progress_ms', 0)
                duration = current_playback.get('item', {}).get('duration_ms', 0)
                remaining = duration - progress
                if remaining < 5000 and song_queue:  # Son 5 saniye ve kuyrukta şarkı var
                    logger.info("Şarkı bitmeye yakın, sıradaki şarkı hazırlanıyor")
        else:
            if not settings['active_device_id']:
                logger.warning("Aktif cihaz seçilmemiş, çalma yapılamıyor")
            elif not song_queue:
                logger.debug("Şarkı kuyruğu boş")
        
        time.sleep(3)  # Biraz daha sık kontrol et

def start_queue_player():
    thread = threading.Thread(target=play_queue)
    thread.daemon = True
    thread.start()
    logger.info("Arka plan şarkı çalma görevi başlatıldı")

# Uygulama başlatıldığında token kontrolü
def check_token_on_startup():
    token_info = load_token()
    if token_info:
        auth_manager = get_spotify_auth()
        try:
            # Token geçerli mi kontrol et
            if auth_manager.is_token_expired(token_info):
                logger.info("Başlangıçta bulunan token süresi dolmuş, yenileniyor...")
                new_token = auth_manager.refresh_access_token(token_info['refresh_token'])
                save_token(new_token)
                logger.info("Token başarıyla yenilendi")
                
                # Global Spotify istemcisini başlat
                global spotify_client
                spotify_client = spotipy.Spotify(auth=new_token['access_token'])
                logger.info("Spotify istemcisi başlatıldı")
            else:
                # Token hala geçerli
                spotify_client = spotipy.Spotify(auth=token_info['access_token'])
                logger.info("Mevcut token ile Spotify istemcisi başlatıldı")
                
            # Token doğrulama testi
            spotify_client.current_user()
            logger.info("Token doğrulandı")
            return True
        except Exception as e:
            logger.error(f"Başlangıç token kontrolünde hata: {e}")
    else:
        logger.warning("Başlangıçta token bulunamadı")
    return False

if __name__ == '__main__':
    logger.info("------- Uygulama başlatılıyor -------")
    logger.info(f"Yüklenen ayarlar: {settings}")
    
    # Başlangıçta token kontrolü yap
    check_token_on_startup()
    
    # Kuyruk oynatıcısını başlat
    start_queue_player()
    
    # Flask uygulamasını başlat
    app.run(host='0.0.0.0', port=8080, debug=True)