<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mekan Müzik Yönetim Paneli</title>
    <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" integrity="sha512-9usAa10IRO0HhonpyAIVpjrylPvoDwiPUiKdWk5t3PyolY1cOd4DSE0Ga+ri4AuTroPR5aQvXU9xC6qOPnzFeg==" crossorigin="anonymous" referrerpolicy="no-referrer" />
    
    <!-- Leaflet.js Harita Kütüphanesi -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
     integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
     crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
     integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
     crossorigin=""></script>

    <!-- YENİ: Leaflet-Geosearch Arama Eklentisi -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet-geosearch@3.11.0/dist/geosearch.css" />
    <script src="https://unpkg.com/leaflet-geosearch@3.11.0/dist/geosearch.umd.js"></script>

    <style>
        :root {
            --spotify-green: #1DB954;
            --primary-blue: #007bff;
            --bs-body-bg: #f4f7f6;
            --card-bg: #ffffff;
            --card-border-color: #dee2e6;
            --text-muted-color: #6c757d;
        }

        body {
            background-color: var(--bs-body-bg);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        }

        /* --- Ana Başlık ve Düzen --- */
        .main-header {
            padding-bottom: 1rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--card-border-color);
        }
        .main-header h1 {
            color: #343a40;
            font-weight: 700;
        }

        /* --- Kart Stilleri --- */
        .card {
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 0.75rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            transition: all 0.3s ease-in-out;
            height: 100%;
        }
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
        }
        .card-header {
            background-color: transparent;
            border-bottom: 1px solid rgba(0,0,0,0.08);
            font-weight: 600;
            padding: 1rem 1.25rem;
            color: #495057;
        }
        .card-footer {
            background-color: #fcfcfc;
            border-top: 1px solid rgba(0,0,0,0.06);
        }
        .card-body-scrollable {
            max-height: 350px;
            overflow-y: auto;
        }

        /* --- Cihaz Vurgu Stilleri --- */
        .device-list-item {
            padding: 0.75rem;
            border: 2px solid transparent;
            border-radius: 0.5rem;
            margin-bottom: 0.5rem;
            transition: all 0.2s ease;
            background-color: #f8f9fa;
        }
        .active-spotify-device { border-left: 5px solid var(--spotify-green) !important; background-color: #e6f7f0; }
        .connected-bluetooth-device { border-left: 5px solid var(--primary-blue) !important; background-color: #e7f3ff; }
        .default-audio-sink { border-left: 5px solid #6f42c1 !important; background-color: #f3eefe; }
        .running-audio-sink:not(.default-audio-sink) { border-left: 5px solid #ffc107 !important; background-color: #fff9e6; }

        /* --- Özel Bölümler --- */
        .section-title {
            font-weight: 600;
            color: #343a40;
            margin-bottom: 1.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--spotify-green);
            display: inline-block;
        }
        
        /* --- Şu an Çalıyor Kartı --- */
        .currently-playing-img {
            width: 80px; height: 80px; object-fit: cover;
            border-radius: 0.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .currently-playing-placeholder {
            width: 80px; height: 80px; background-color: #e9ecef;
            display: flex; align-items: center; justify-content: center;
            border-radius: 0.5rem; color: var(--text-muted-color);
            font-size: 2rem; font-weight: bold;
        }
        .quick-block-btn { font-size: 0.75em; padding: 0.2rem 0.4rem; margin-left: 5px; }

        /* --- Filtre Yönetimi --- */
        .filter-list {
            list-style: none; padding: 0; max-height: 200px; overflow-y: auto;
            border: 1px solid #eee; padding: 10px; border-radius: 5px; margin-bottom: 10px; background-color: #fdfdfd;
        }
        .filter-list li {
            display: flex; justify-content: space-between; align-items: center;
            padding: 8px 10px; border-bottom: 1px solid #f0f0f0;
            font-size: 0.9rem;
        }
        .filter-list li:last-child { border-bottom: none; }
        .filter-list span { flex-grow: 1; margin-right: 10px; word-break: break-all; }
        .filter-list .item-name { font-weight: 500; color: #333; }
        .filter-list .item-id { font-size: 0.8em; color: var(--text-muted-color); display: block; }

        /* --- Çalma Listesi Kartları --- */
        .playlist-card {
            cursor: pointer;
            border: 3px solid transparent;
            transition: all 0.2s ease-in-out;
            position: relative;
            overflow: hidden;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .playlist-card:hover {
            transform: translateY(-5px) scale(1.03);
            box-shadow: 0 8px 20px rgba(0,0,0,0.15);
        }
        .playlist-card.selected {
            border-color: var(--spotify-green);
            box-shadow: 0 0 20px rgba(29, 185, 84, 0.6);
        }
        .playlist-card-img-container {
            position: relative;
            padding-top: 100%; /* 1:1 Aspect Ratio */
            background-color: #333;
        }
        .playlist-card-img {
            position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover;
            transition: transform 0.3s ease;
        }
        .playlist-card:hover .playlist-card-img { transform: scale(1.1); }
        .playlist-card .card-body {
            position: absolute; bottom: 0; left: 0; right: 0;
            background: linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0) 100%);
            color: white; padding: 0.75rem;
        }
        .playlist-card .card-title {
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 0.25rem; font-weight: bold;
        }
        .playlist-card .card-text { font-size: 0.8rem; opacity: 0.9; }
        .selected-checkmark {
            position: absolute; top: 10px; right: 10px; font-size: 2rem; color: var(--spotify-green);
            background-color: rgba(255, 255, 255, 0.95); border-radius: 50%;
            width: 40px; height: 40px; display: none;
            justify-content: center; align-items: center; text-shadow: 0 0 5px black;
        }
        .playlist-card.selected .selected-checkmark { display: flex; }
        
        /* Harita Stili */
        #map { 
            height: 400px;
            width: 100%; 
            border-radius: 0.5rem; 
            border: 1px solid #ddd; 
            margin-bottom: 1rem; 
            cursor: grab;
        }
        /* YENİ: Arama çubuğu stili */
        .geosearch.geosearch-bar {
            border: 1px solid #ced4da !important;
            box-shadow: 0 0 0 0.2rem rgba(0,123,255,.25) !important;
        }
        .leaflet-geosearch-bar .results {
            z-index: 1001; /* Arama sonuçlarının harita üzerinde görünmesi için */
        }


        /* --- Diğer Yardımcı Stiller --- */
        .btn svg, .btn i { margin-right: 0.35em; }
        .btn-loading .spinner-border { width: 1em; height: 1em; border-width: .15em; }
        .search-results-filter { max-height: 150px; overflow-y: auto; border: 1px solid #eee; margin-top: 10px; }
        .search-results-filter .list-group-item { cursor: pointer; }
        .search-results-filter .list-group-item:hover { background-color: #f0f0f0; }
        .table-hover tbody tr:hover { background-color: rgba(0,0,0,0.03); }

    </style>
</head>
<body>
    <div class="container-fluid py-4 px-lg-5">
        
        <!-- Tüm sayfa içeriği (mevcut haliyle kalacak) -->
        <div class="main-header d-flex justify-content-between align-items-center">
            <h1 class="h2">Mekan Müzik Yönetim Paneli</h1>
            <div>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-danger">
                    <i class="fas fa-sign-out-alt"></i> Çıkış Yap
                </a>
            </div>
        </div>

        <div id="flash-messages">
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ category or 'info' }} alert-dismissible fade show" role="alert">
                    {{ message }}
                    <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>
                  </div>
                {% endfor %}
              {% endif %}
            {% endwith %}
        </div>

        {% if not spotify_authenticated %}
        <div class="alert alert-warning alert-dismissible fade show" role="alert">
            <i class="fas fa-exclamation-triangle"></i> <strong>Spotify bağlantısı yok!</strong> Lütfen Spotify hesabınızı bağlayın.
            <a href="{{ url_for('spotify_auth') }}" class="btn btn-sm btn-success ml-2">Şimdi Yetkilendir</a>
            <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>
        </div>
        {% else %}
        <div class="alert alert-success alert-dismissible fade show" role="alert">
            <i class="fab fa-spotify"></i> Spotify bağlı: <strong>{{ spotify_user or 'Bilinmeyen Kullanıcı' }}</strong>
            <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>
        </div>
        {% endif %}

        <!-- ANLIK DURUM BÖLÜMÜ -->
        <div class="row mb-4">
            <div class="col-lg-6 mb-4">
                <div class="card">
                    <div class="card-header"><i class="fas fa-music mr-2 text-success"></i>Şu An Çalıyor</div>
                    <div class="card-body" id="currently-playing-admin">
                        {% if currently_playing_info %}
                            <div class="d-flex align-items-center mb-3">
                                {% if currently_playing_info.image_url %}
                                <img src="{{ currently_playing_info.image_url }}" alt="Albüm Kapağı" class="mr-3 currently-playing-img">
                                {% else %}
                                <div class="mr-3 currently-playing-placeholder">?</div>
                                {% endif %}
                                <div style="min-width: 0;">
                                    <strong class="d-block text-truncate h5 mb-1">{{ currently_playing_info.name }}</strong>
                                    <small class="text-muted d-block text-truncate">{{ currently_playing_info.artist }}</small>
                                    <div class="mt-2">
                                        {% if currently_playing_info.id %}
                                        <button class="btn btn-danger btn-sm quick-block-btn" title="Bu Şarkıyı Kara Listeye Ekle" onclick="quickBlockItem(this, 'track', '{{ currently_playing_info.id }}')"><i class="fas fa-ban"></i> Şarkı</button>
                                        {% endif %}
                                        {% if currently_playing_info.artist_ids %}{% for artist_id in currently_playing_info.artist_ids %}{% if loop.first %}
                                        <button class="btn btn-danger btn-sm quick-block-btn" title="Sanatçıyı Kara Listeye Ekle" onclick="quickBlockItem(this, 'artist', '{{ artist_id }}')"><i class="fas fa-user-slash"></i> Sanatçı</button>
                                        {% endif %}{% endfor %}{% endif %}
                                    </div>
                                </div>
                            </div>
                            <div class="mt-auto">
                                {% if currently_playing_info.is_playing %}
                                <form action="{{ url_for('player_pause') }}" method="GET" class="d-block">
                                    <button type="submit" class="btn btn-warning btn-block"><i class="fas fa-pause"></i> Durdur & Otomatik Geçişi Kapat</button>
                                </form>
                                {% else %}
                                <form action="{{ url_for('player_resume') }}" method="GET" class="d-block">
                                    <button type="submit" class="btn btn-success btn-block"><i class="fas fa-play"></i> Devam Et & Otomatik Geçişi Aç</button>
                                </form>
                                {% endif %}
                            </div>
                        {% else %}
                            <div class="text-center py-4">
                                <i class="fas fa-info-circle fa-2x text-muted mb-2"></i>
                                <p class="text-muted mb-0">Şu anda aktif bir şarkı çalınmıyor.</p>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>
            <div class="col-lg-6 mb-4">
                <div class="card">
                    <div class="card-header"><i class="fas fa-tasks mr-2 text-info"></i>Şarkı Kuyruğu ({{ queue|length }}/{{ settings.max_queue_length }})</div>
                    <div class="card-body card-body-scrollable pr-1">
                        {% if queue %}
                        <ul class="list-group list-group-flush">
                            {% for song in queue %}
                            <li class="list-group-item d-flex justify-content-between align-items-center px-0 py-2">
                                <div style="min-width: 0;">
                                    <strong class="d-block text-truncate">{{ song.name }}</strong>
                                    <small class="text-muted d-block text-truncate">{{ song.artist }}</small>
                                    <div class="mt-1">
                                        {% if song.id %}<button class="btn btn-danger btn-sm quick-block-btn" title="Bu Şarkıyı Kara Listeye Ekle" onclick="quickBlockItem(this, 'track', '{{ song.id }}')"><i class="fas fa-ban"></i> Şarkı</button>{% endif %}
                                        {% if song.artist_ids %}{% for artist_id in song.artist_ids %}{% if loop.first %}<button class="btn btn-danger btn-sm quick-block-btn" title="Sanatçıyı Kara Listeye Ekle" onclick="quickBlockItem(this, 'artist', '{{ artist_id }}')"><i class="fas fa-user-slash"></i> Sanatçı</button>{% endif %}{% endfor %}{% endif %}
                                    </div>
                                </div>
                                <form method="POST" action="{{ url_for('remove_song', song_id_str=song.id) }}" class="ml-2">
                                    <button type="submit" class="btn btn-sm btn-outline-danger" title="Kuyruktan Kaldır"><i class="fas fa-times"></i></button>
                                </form>
                            </li>
                            {% endfor %}
                        </ul>
                        {% else %}
                        <div class="text-center py-5"><p class="text-muted">Kuyruk boş.</p></div>
                        {% endif %}
                    </div>
                    <div class="card-footer">
                        <form method="POST" action="{{ url_for('add_song') }}" class="input-group mb-2">
                            <input type="text" name="song_id" class="form-control" placeholder="Spotify Şarkı ID veya URL" required>
                            <div class="input-group-append"><button type="submit" class="btn btn-success"><i class="fas fa-plus"></i> Ekle</button></div>
                        </form>
                        <a href="{{ url_for('clear_queue') }}" class="btn btn-sm btn-danger btn-block"><i class="fas fa-trash-alt"></i> Kuyruğu Temizle</a>
                    </div>
                </div>
            </div>
        </div>

        <!-- CİHAZ YÖNETİMİ BÖLÜMÜ -->
        <h3 class="section-title">Cihaz ve Ses Çıkış Yönetimi</h3>
        <div class="row mb-4">
            <div class="col-lg-4 col-md-6 mb-4">
                <div class="card">
                    <div class="card-header"><i class="fab fa-spotify mr-2" style="color: var(--spotify-green);"></i>Spotify Connect Cihazları</div>
                    <div class="card-body card-body-scrollable" id="spotify-devices-list">
                         {% if spotify_devices %}
                            <div class="list-group list-group-flush">
                                {% for device in spotify_devices %}
                                <div class="device-list-item {% if device.id == active_spotify_connect_device_id %}active-spotify-device{% endif %}">
                                    <div class="d-flex justify-content-between align-items-center">
                                        <div style="min-width: 0;">
                                            <strong class="d-block text-truncate">{{ device.name }}</strong>
                                            <small class="text-muted">{{ device.type|upper }} {% if device.is_restricted %}(Kısıtlı){% endif %} {% if device.volume_percent is not none %}- Ses: {{device.volume_percent}}%{% endif %}</small>
                                        </div>
                                        <form method="POST" action="{{ url_for('update_settings') }}" class="ml-2">
                                            <input type="hidden" name="active_spotify_connect_device_id" value="{{ device.id }}">
                                            <button type="submit" class="btn btn-sm {% if device.id == active_spotify_connect_device_id %}btn-success disabled{% else %}btn-outline-primary{% endif %}" {% if device.id == active_spotify_connect_device_id %}aria-disabled="true"{% endif %} style="white-space: nowrap;">
                                                {% if device.id == active_spotify_connect_device_id %}Aktif{% else %}Seç{% endif %}
                                            </button>
                                        </form>
                                    </div>
                                </div>
                                {% endfor %}
                            </div>
                        {% else %}
                            <p class="text-muted text-center p-4">Aktif Spotify Connect cihazı bulunamadı.</p>
                        {% endif %}
                    </div>
                    <div class="card-footer text-center">
                        <a href="{{ url_for('refresh_devices') }}" class="btn btn-sm btn-primary"><i class="fas fa-sync-alt"></i> Connect Cihazlarını Yenile</a>
                    </div>
                </div>
            </div>
            <div class="col-lg-4 col-md-6 mb-4">
                <div class="card">
                    <div class="card-header"><i class="fas fa-volume-up mr-2 text-dark"></i>Ses Çıkışları (Hedef Seçimi)</div>
                    <div class="card-body card-body-scrollable" id="audio-sinks-list"><p class="text-muted p-3 text-center">Yükleniyor...</p></div>
                    <div class="card-footer text-center">
                        <button onclick="refreshAudioSinkList()" class="btn btn-sm btn-dark"><i class="fas fa-sync-alt"></i> Listeyi Yenile</button>
                        <small class="text-muted mt-2 d-block">Seçilen cihaz sistemin varsayılan ses çıkışı olur.</small>
                    </div>
                </div>
            </div>
             <div class="col-lg-4 col-md-6 mb-4">
                <div class="card">
                    <div class="card-header"><i class="fab fa-bluetooth-b mr-2 text-primary"></i>Bluetooth Cihazları</div>
                    <div class="card-body card-body-scrollable" id="bluetooth-list"><p class="text-muted p-3 text-center">Yükleniyor...</p></div>
                    <div class="card-footer text-center">
                        <button onclick="discoverBluetoothDevices()" id="discover-btn" class="btn btn-sm btn-warning mb-2">
                            <i class="fas fa-broadcast-tower"></i> Yeni Cihazları Tara (<span id="scan-duration-text">{{ BLUETOOTH_SCAN_DURATION | default(12) }}</span>sn)
                        </button>
                        <small class="text-muted mt-2 d-block">Yeni cihazları görmek için önce tarayın.</small>
                    </div>
                </div>
            </div>
        </div>

        <!-- ENTEGRE EDİLMİŞ AYARLAR BÖLÜMÜ -->
        <h3 class="section-title">Filtreler, Konum ve Genel Ayarlar</h3>
        <form method="POST" action="{{ url_for('update_settings') }}">
            <div class="row mb-4">
                <!-- Konum Ayarları Kartı -->
                <div class="col-lg-8 mb-4">
                    <div class="card h-100">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <span><i class="fas fa-map-marked-alt mr-2 text-info"></i>Konum Ayarları ve Arama</span>
                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="goToMyLocation()"><i class="fas fa-location-arrow"></i> Mevcut Konumuma Git</button>
                        </div>
                        <div class="card-body">
                            <p class="text-muted small">Adres arayın, haritaya tıklayın veya işaretçiyi sürükleyerek mekanın konumunu ayarlayın.</p>
                            <div id="map"></div>
                            <div class="row">
                                <div class="col-md-4 form-group">
                                    <label for="cafe_latitude">Enlem (Latitude)</label>
                                    <input type="number" step="any" id="cafe_latitude" name="cafe_latitude" value="{{ settings.cafe_latitude }}" class="form-control" required readonly>
                                </div>
                                <div class="col-md-4 form-group">
                                    <label for="cafe_longitude">Boylam (Longitude)</label>
                                    <input type="number" step="any" id="cafe_longitude" name="cafe_longitude" value="{{ settings.cafe_longitude }}" class="form-control" required readonly>
                                </div>
                                <div class="col-md-4 form-group">
                                    <label for="max_distance_meters">Maksimum Uzaklık (metre)</label>
                                    <input type="number" id="max_distance_meters" name="max_distance_meters" value="{{ settings.max_distance_meters }}" class="form-control" min="10" required>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <!-- Genel Ayarlar ve Filtre Modları Kartı -->
                <div class="col-lg-4 mb-4">
                     <div class="card h-100">
                         <div class="card-header"><i class="fas fa-cogs mr-2 text-warning"></i>Genel Ayarlar ve Filtreler</div>
                         <div class="card-body d-flex flex-column">
                             <div class="form-group">
                                 <label for="max_queue_length">Maks. Kuyruk Uzunluğu</label>
                                 <input type="number" id="max_queue_length" name="max_queue_length" value="{{ settings.max_queue_length }}" class="form-control" min="1" required>
                             </div>
                             <div class="form-group">
                                 <label for="max_user_requests">Kullanıcı Başına Maks. İstek</label>
                                 <input type="number" id="max_user_requests" name="max_user_requests" value="{{ settings.max_user_requests }}" class="form-control" min="1" required>
                             </div>
                             <hr>
                             <label class="d-block"><strong>Tür Filtresi:</strong></label>
                             <div class="custom-control custom-radio custom-control-inline">
                                 <input type="radio" id="genre_mode_blacklist" name="genre_filter_mode" value="blacklist" class="custom-control-input" {% if settings.genre_filter_mode == 'blacklist' %}checked{% endif %}>
                                 <label class="custom-control-label" for="genre_mode_blacklist">Kara Liste</label>
                             </div>
                             <div class="custom-control custom-radio custom-control-inline">
                                 <input type="radio" id="genre_mode_whitelist" name="genre_filter_mode" value="whitelist" class="custom-control-input" {% if settings.genre_filter_mode == 'whitelist' %}checked{% endif %}>
                                 <label class="custom-control-label" for="genre_mode_whitelist">Beyaz Liste</label>
                             </div>
                             <div class="mt-3">
                                 <label class="d-block"><strong>Sanatçı Filtresi:</strong></label>
                                 <div class="custom-control custom-radio custom-control-inline">
                                     <input type="radio" id="artist_mode_blacklist" name="artist_filter_mode" value="blacklist" class="custom-control-input" {% if settings.artist_filter_mode == 'blacklist' %}checked{% endif %}>
                                     <label class="custom-control-label" for="artist_mode_blacklist">Kara Liste</label>
                                 </div>
                                 <div class="custom-control custom-radio custom-control-inline">
                                     <input type="radio" id="artist_mode_whitelist" name="artist_filter_mode" value="whitelist" class="custom-control-input" {% if settings.artist_filter_mode == 'whitelist' %}checked{% endif %}>
                                     <label class="custom-control-label" for="artist_mode_whitelist">Beyaz Liste</label>
                                 </div>
                             </div>
                         </div>
                     </div>
                </div>
            </div>
            <div class="row">
                <div class="col-12 text-center mb-4">
                    <button type="submit" class="btn btn-lg btn-primary"><i class="fas fa-save"></i> Tüm Ayarları Kaydet</button>
                </div>
            </div>
        </form>

        <!-- Filtre Listeleri ve Sistem İşlemleri -->
        <div class="row mb-4">
             <div class="col-md-6 col-lg-4 mb-4">
                <div class="card">
                    <div class="card-header">Tür Filtresi (<span id="genre-mode-display">{{ settings.genre_filter_mode|replace('blacklist', 'Kara Liste')|replace('whitelist', 'Beyaz Liste') }}</span>)</div>
                    <div class="card-body">
                        <ul class="filter-list" id="genre-filter-list"></ul>
                        <div class="input-group mt-2">
                            <input type="text" class="form-control" id="genre-add-input" placeholder="Yeni Tür Ekle...">
                            <div class="input-group-append"><button class="btn btn-outline-success" type="button" onclick="addFilterItem('genre')">Ekle</button></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6 col-lg-4 mb-4">
                <div class="card">
                    <div class="card-header">Sanatçı Filtresi (<span id="artist-mode-display">{{ settings.artist_filter_mode|replace('blacklist', 'Kara Liste')|replace('whitelist', 'Beyaz Liste') }}</span>)</div>
                    <div class="card-body">
                        <ul class="filter-list" id="artist-filter-list"></ul>
                        <div class="input-group mt-2">
                            <input type="text" class="form-control" id="artist-add-input" placeholder="Spotify Sanatçı ID Ekle...">
                            <div class="input-group-append"><button class="btn btn-outline-success" type="button" onclick="addFilterItem('artist')">Ekle</button></div>
                        </div>
                        <hr>
                        <label class="small text-muted">Veya Arama ile Ekle:</label>
                        <div class="input-group">
                            <input type="text" class="form-control" id="artist-search-input" placeholder="Sanatçı Ara...">
                            <div class="input-group-append"><button class="btn btn-outline-primary" type="button" onclick="searchSpotify('artist')">Ara</button></div>
                        </div>
                        <div class="search-results-filter list-group list-group-flush mt-2" id="artist-search-results"></div>
                    </div>
                </div>
            </div>
            <div class="col-md-12 col-lg-4 mb-4">
                 <div class="card">
                    <div class="card-header bg-danger text-white"><i class="fas fa-ban mr-2"></i>Engellenmiş Şarkılar (Kara Liste)</div>
                    <div class="card-body">
                        <div class="input-group mb-3">
                            <input type="text" class="form-control" id="blocked-track-search-input" onkeyup="searchBlockedTracks()" placeholder="Engellenmiş şarkılarda ara...">
                            <div class="input-group-append"><span class="input-group-text"><i class="fas fa-search"></i></span></div>
                        </div>
                        <div class="table-responsive" style="max-height: 280px;">
                            <table class="table table-hover table-sm">
                                <tbody id="blocked-tracks-list"><!-- JS ile doldurulacak --></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6 col-lg-4 mb-4">
                 <div class="card">
                    <div class="card-header"><i class="fas fa-tools mr-2 text-dark"></i>Sistem İşlemleri</div>
                    <div class="card-body d-flex flex-column justify-content-center">
                         <button onclick="switchToAlsa(this)" id="alsa-switch-btn" class="btn btn-outline-dark btn-block mb-3"><i class="fas fa-desktop"></i> ALSA Cihazına Geçiş Yap</button>
                         <button onclick="restartSpotifyd(this)" id="spotifyd-restart-btn" class="btn btn-outline-danger btn-block mb-3"><i class="fas fa-redo"></i> Spotifyd'yi Yeniden Başlat</button>
                         <hr>
                         <div class="port-control-section">
                             <h6 class="mb-3">SSH Port (22) Kontrolü</h6>
                             <div id="port-status" class="alert d-none mb-3"></div>
                             <div class="btn-group w-100">
                                 <button onclick="checkPort(this)" class="btn btn-outline-primary"><i class="fas fa-sync-alt"></i> Durumu Kontrol Et</button>
                                 <button onclick="openPort(this)" class="btn btn-success"><i class="fas fa-door-open"></i> Portu Aç</button>
                                 <button onclick="closePort(this)" class="btn btn-danger"><i class="fas fa-door-closed"></i> Portu Kapat</button>
                             </div>
                         </div>
                         <small class="text-muted text-center mt-3">Not: Ses cihazı değişikliklerinden sonra yeniden başlatma gerekebilir.</small>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- ÇALMA LİSTESİ BÖLÜMÜ -->
        <hr class="my-4">
        <div>
            <h4 class="mb-3">Otomatik Çalma için Çalma Listesi Seçimi</h4>
            <p class="text-muted">Kuyruk boşaldığında, buradan seçtiğiniz listeden rastgele bir şarkı çalınır. Seçiminiz otomatik olarak kaydedilir.</p>
            <input type="hidden" id="active_playlist_uri_input" name="active_playlist_uri" value="{{ active_playlist_uri or '' }}">

            <div class="row">
                {% for playlist in paginated_playlists %}
                    {% if playlist and playlist.id %}
                    <div class="col-6 col-md-4 col-lg-3 col-xl-2 mb-4">
                        <div class="card playlist-card {% if playlist.uri == active_playlist_uri %}selected{% endif %}" data-uri="{{ playlist.uri }}">
                            <div class="playlist-card-img-container">
                                {% if playlist.images and playlist.images|length > 0 %}
                                    <img src="{{ playlist.images[0].url }}" class="playlist-card-img" alt="{{ playlist.name }}">
                                {% else %}
                                    <div class="d-flex justify-content-center align-items-center h-100 bg-secondary position-absolute w-100">
                                        <i class="fas fa-music fa-3x text-light"></i>
                                    </div>
                                {% endif %}
                            </div>
                            <div class="card-body">
                                <h6 class="card-title" title="{{ playlist.name }}">{{ playlist.name }}</h6>
                                <p class="card-text text-light">{{ playlist.tracks.total }} şarkı</p>
                            </div>
                            <div class="selected-checkmark"><i class="fas fa-check-circle"></i></div>
                        </div>
                    </div>
                    {% endif %}
                {% else %}
                    <div class="col-12">
                        <p class="text-center text-muted">Spotify'da hiç çalma listeniz bulunamadı veya yetkilendirme gerekli.</p>
                    </div>
                {% endfor %}
            </div>

            {% if total_pages > 1 %}
            <nav aria-label="Playlist Pagination" class="mt-4">
                <ul class="pagination justify-content-center">
                    <li class="page-item {% if page <= 1 %}disabled{% endif %}"><a class="page-link" href="{{ url_for('admin_panel', page=page-1) }}">Önceki</a></li>
                    {% for p in range(1, total_pages + 1) %}<li class="page-item {% if p == page %}active{% endif %}"><a class="page-link" href="{{ url_for('admin_panel', page=p) }}">{{ p }}</a></li>{% endfor %}
                    <li class="page-item {% if page >= total_pages %}disabled{% endif %}"><a class="page-link" href="{{ url_for('admin_panel', page=page+1) }}">Sonraki</a></li>
                </ul>
            </nav>
            {% endif %}
        </div>

    </div>

    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/popper.js@1.16.1/dist/umd/popper.min.js"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>

    <script>
        // --- Global Değişkenler ---
        let currentSettings = JSON.parse('{{ settings | tojson | safe }}');
        let spotifyNameCache = {}; // ID -> Name eşleşmesi için cache

        // --- Yardımcı Fonksiyonlar ---
        function showFlashMessage(message, category = 'info') {
            const flashDiv = document.getElementById('flash-messages');
            if (!flashDiv) return;
            const alertHtml = `<div class="alert alert-${category} alert-dismissible fade show mt-2" role="alert">${message}<button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button></div>`;
            flashDiv.insertAdjacentHTML('afterbegin', alertHtml);
            window.setTimeout(() => { const el = flashDiv.querySelector('.alert'); if (el) { try { $(el).alert('close'); } catch (e) { el.remove(); } } }, 7000);
        }
        function showListLoading(elementId, message = "Yükleniyor...") { $(`#${elementId}`).html(`<p class="text-muted p-3 text-center"><span class="spinner-border spinner-border-sm mr-2" role="status" aria-hidden="true"></span>${message}</p>`); }
        function setButtonLoading(buttonElement, isLoading) {
            if (!buttonElement || typeof buttonElement.classList === 'undefined') { console.error("setButtonLoading called with invalid buttonElement:", buttonElement); return; }
            if (isLoading) {
                buttonElement.disabled = true; buttonElement.classList.add('btn-loading');
                if (!buttonElement.dataset.originalHtml) { buttonElement.dataset.originalHtml = buttonElement.innerHTML; }
                buttonElement.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> İşleniyor...';
            } else {
                buttonElement.disabled = false; buttonElement.classList.remove('btn-loading');
                if (buttonElement.dataset.originalHtml) { buttonElement.innerHTML = buttonElement.dataset.originalHtml; delete buttonElement.dataset.originalHtml; }
            }
        }
        
        // --- Sayfa Yüklendiğinde Çalışacak Kodlar ---
        document.addEventListener('DOMContentLoaded', function() {
            // <!-- GÜNCELLENDİ: Harita Başlatma ve Arama Özelliği -->
            const latInput = document.getElementById('cafe_latitude');
            const lonInput = document.getElementById('cafe_longitude');
            const radiusInput = document.getElementById('max_distance_meters');
            const initialLat = parseFloat(latInput.value) || 41.015137; // Varsayılan İstanbul
            const initialLon = parseFloat(lonInput.value) || 28.979530; // Varsayılan İstanbul
            const map = L.map('map').setView([initialLat, initialLon], 16);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            }).addTo(map);

            const marker = L.marker([initialLat, initialLon], { draggable: true }).addTo(map);
            let circle = L.circle([initialLat, initialLon], {
                color: 'blue', fillColor: '#3498db', fillOpacity: 0.2, radius: parseInt(radiusInput.value, 10) || 500
            }).addTo(map);

            function updateUI(lat, lng, rad) {
                latInput.value = lat.toFixed(6);
                lonInput.value = lng.toFixed(6);
                circle.setLatLng([lat, lng]);
                if(rad) circle.setRadius(rad);
            }

            // Arama kontrolünü ekle
            const searchControl = new GeoSearch.GeoSearchControl({
                provider: new GeoSearch.OpenStreetMapProvider(),
                style: 'bar',
                showMarker: false, // Kendi marker'ımızı kullanıyoruz
                autoClose: true,
                keepResult: true,
                searchLabel: 'Adres veya yer arayın...',
            });
            map.addControl(searchControl);

            // Arama sonucu bulunduğunda tetiklenecek olay
            map.on('geosearch/showlocation', function (result) {
                const lat = result.location.y;
                const lng = result.location.x;
                marker.setLatLng([lat, lng]); // Marker'ı yeni konuma taşı
                updateUI(lat, lng); // Inputları ve daireyi güncelle
            });

            marker.on('dragend', () => updateUI(marker.getLatLng().lat, marker.getLatLng().lng));
            map.on('click', (e) => { marker.setLatLng(e.latlng); updateUI(e.latlng.lat, e.latlng.lng); });
            radiusInput.addEventListener('input', () => {
                const newRadius = parseInt(radiusInput.value, 10);
                if (!isNaN(newRadius) && newRadius > 0) circle.setRadius(newRadius);
            });
            window.goToMyLocation = () => map.locate({setView: true, maxZoom: 17});
            map.on('locationfound', (e) => { marker.setLatLng(e.latlng); updateUI(e.latlng.lat, e.latlng.lng); });
            map.on('locationerror', (e) => alert("Konum alınamadı: " + e.message));

            // Playlist Seçimi
            const playlistCards = document.querySelectorAll('.playlist-card');
            playlistCards.forEach(card => {
                card.addEventListener('click', function () {
                    const clickedCard = this;
                    const selectedUri = clickedCard.dataset.uri;
                    let newActiveUri = selectedUri;

                    if (clickedCard.classList.contains('selected')) {
                        newActiveUri = ''; // Seçimi kaldır
                    }
                    
                    fetch('{{ url_for("api_set_active_playlist") }}', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ playlist_uri: newActiveUri })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            showFlashMessage(data.message, 'success');
                            if (newActiveUri === '') {
                                clickedCard.classList.remove('selected');
                            } else {
                                playlistCards.forEach(c => c.classList.remove('selected'));
                                clickedCard.classList.add('selected');
                            }
                        } else {
                            showFlashMessage(data.error || 'Bir hata oluştu.', 'danger');
                        }
                    })
                    .catch(error => {
                        console.error('API Hatası:', error);
                        showFlashMessage('Ağ hatası, ayar kaydedilemedi.', 'danger');
                    });
                });
            });

            // Diğer Başlangıç Fonksiyonları
            refreshAudioSinkList(); 
            refreshBluetoothList(0);
            
            const allIdsToFetch = {
                artist: [...new Set([...(currentSettings.artist_blacklist || []), ...(currentSettings.artist_whitelist || [])])],
                track: [...new Set([...(currentSettings.track_blacklist || [])])] // Sadece kara liste için
            };
            const fetchPromises = Object.keys(allIdsToFetch).map(type => {
                if (allIdsToFetch[type].length > 0) {
                    return $.ajax({ url: '/api/spotify/details', type: 'POST', contentType: 'application/json', data: JSON.stringify({ ids: allIdsToFetch[type], type: type }) })
                        .done(data => { if (data.success && data.details) $.extend(spotifyNameCache, data.details); });
                }
            }).filter(p => p);
            $.when.apply($, fetchPromises).always(() => renderAllFilterLists());
        });

        // --- Geri kalan tüm JavaScript fonksiyonları (renderFilterList, quickBlockItem, checkPort vb.) olduğu gibi kalacak ---
        // Kısaltmak adına buraya tekrar eklemiyorum.
        // --- Listeleri Render Etme Fonksiyonları ---
        function renderAudioSinkList(sinks, defaultSinkName) {
            const listElement = $('#audio-sinks-list'); listElement.empty();
            if (sinks && sinks.length > 0) {
                 sinks.forEach(sink => {
                     let stateClass = ''; let isDefault = sink.name === defaultSinkName;
                     if (isDefault) { stateClass = 'default-audio-sink'; }
                     else if (sink.state === 'RUNNING') { stateClass = 'running-audio-sink'; }
                     
                     let stateBadge = `<span class="badge badge-secondary">${sink.state || 'Bilinmiyor'}</span>`;
                     if(isDefault) stateBadge = `<span class="badge badge-primary">Varsayılan</span>`;
                     else if(sink.state === 'RUNNING') stateBadge = `<span class="badge badge-success">Çalışıyor</span>`;

                     let buttonHtml = !isDefault ? `<button onclick="setDefaultAudioSink(this, '${sink.index}')" class="btn btn-sm btn-outline-primary ml-2" style="white-space: nowrap;">Varsayılan Yap</button>` : '';
                     
                     const itemHtml = `
                        <div class="device-list-item ${stateClass}">
                            <div class="d-flex justify-content-between align-items-center">
                                <div style="min-width: 0;">
                                    <strong class="d-block text-truncate" title="${sink.description}">${sink.description}</strong>
                                    <small class="text-muted d-block text-truncate" title="${sink.name}">Index: ${sink.index} ${stateBadge}</small>
                                </div>
                                ${buttonHtml}
                            </div>
                        </div>`;
                     listElement.append(itemHtml);
                 });
            } else { listElement.html('<p class="text-muted text-center p-4">Ses çıkış cihazı (sink) bulunamadı.</p>'); }
         }
        function renderBluetoothList(devices) {
             const listElement = $('#bluetooth-list'); listElement.empty();
             if (devices && devices.length > 0) {
                 devices.forEach(device => {
                     let cardClass = ''; let actionButtonHtml = ''; let statusBadge = '';
                     const devicePath = device.path || '';
                     if (device.paired) {
                         if (device.connected) {
                             cardClass = 'connected-bluetooth-device'; statusBadge = '<span class="badge badge-primary ml-1">Bağlı</span>';
                             actionButtonHtml = `<button onclick="disconnectDevice(this, '${devicePath}')" class="btn btn-sm btn-outline-danger ml-2">Kes</button>`;
                         } else {
                             statusBadge = '<span class="badge badge-secondary ml-1">Eşleşmiş</span>';
                             actionButtonHtml = `<button onclick="pairDevice(this, '${devicePath}')" class="btn btn-sm btn-success ml-2">Bağlan</button>`;
                         }
                     } else {
                         statusBadge = '<span class="badge badge-light ml-1">Yeni</span>';
                         actionButtonHtml = `<button onclick="pairDevice(this, '${devicePath}')" class="btn btn-sm btn-warning ml-2">Eşleştir</button>`;
                     }
                     const itemHtml = `
                        <div class="device-list-item ${cardClass}">
                           <div class="d-flex justify-content-between align-items-center">
                              <div style="min-width: 0;">
                                 <strong class="d-block text-truncate" title="${device.name}">${device.name}</strong>
                                 <small class="text-muted d-block text-truncate">${device.mac_address} ${statusBadge}</small>
                              </div>
                              <div class="ml-2" style="white-space:nowrap;">${actionButtonHtml}</div>
                           </div>
                        </div>`;
                    listElement.append(itemHtml);
                 });
             } else { listElement.html('<p class="text-muted text-center p-4">Bluetooth cihazı bulunamadı.</p>'); }
         }

        // --- API Çağrıları ve Liste Yenileme ---
        function refreshAudioSinkList() {
            showListLoading('audio-sinks-list', 'Ses çıkışları yenileniyor...');
            $.get('/api/audio-sinks')
             .done(function(data) { if(data && data.success) { renderAudioSinkList(data.sinks, data.default_sink_name); } else { $('#audio-sinks-list').html(`<p class="text-danger p-4">Ses listesi alınamadı: ${data.error || 'Veri eksik'}</p>`); } })
             .fail(function(xhr) { $('#audio-sinks-list').html('<p class="text-danger p-4">Ses listesi alınamadı (API Hatası).</p>'); });
        }
        function refreshBluetoothList(duration = 0) {
            const isLoadingKnown = duration === 0; const loadingMessage = isLoadingKnown ? 'Bluetooth cihazları listeleniyor...' : 'Yeni Bluetooth cihazları taranıyor...';
            showListLoading('bluetooth-list', loadingMessage); const discoverBtn = document.getElementById('discover-btn');
            if (!isLoadingKnown && discoverBtn) setButtonLoading(discoverBtn, true);
            $.get(`/api/discover-bluetooth?duration=${duration}`)
             .done(function(data) { if(data && data.success) { renderBluetoothList(data.devices); if (!isLoadingKnown) showFlashMessage('Bluetooth taraması tamamlandı.', 'info'); } else { $('#bluetooth-list').html(`<p class="text-danger p-4">Cihazlar listelenemedi: ${data.error || 'Veri eksik'}</p>`); } })
             .fail(function(xhr) { $('#bluetooth-list').html('<p class="text-danger p-4">Bluetooth API\'sine ulaşılamadı.</p>'); })
             .always(function() { if (!isLoadingKnown && discoverBtn) setButtonLoading(discoverBtn, false); });
        }
        function discoverBluetoothDevices() { const el = document.getElementById('scan-duration-text'); const duration = el ? parseInt(el.textContent || '{{ BLUETOOTH_SCAN_DURATION | default(12) }}', 10) : '{{ BLUETOOTH_SCAN_DURATION | default(12) }}'; refreshBluetoothList(duration); }
        function updateRelevantDeviceLists(data) {
             if (data.sinks !== undefined) { renderAudioSinkList(data.sinks, data.default_sink_name); } else { refreshAudioSinkList(); }
             if (data.bluetooth_devices !== undefined) { renderBluetoothList(data.bluetooth_devices); } else { refreshBluetoothList(0); }
         }
        function setDefaultAudioSink(buttonElement, sinkIdentifier) {
            let sinkDesc = sinkIdentifier; try { const card = buttonElement.closest('.device-list-item'); if(card) { const strongElement = card.querySelector('strong'); if (strongElement) sinkDesc = strongElement.textContent || sinkIdentifier; } } catch(e) {}
            if (!confirm(`"${sinkDesc}" adlı ses çıkışını sistemin varsayılanı yapmak istediğinizden emin misiniz?`)) { return; }
            setButtonLoading(buttonElement, true);
            $.ajax({ url: '/api/set-audio-sink', type: 'POST', contentType: 'application/json', data: JSON.stringify({ sink_identifier: sinkIdentifier }),
                success: function(data) { if (data.success) { showFlashMessage(data.message || 'Varsayılan ses çıkışı başarıyla değiştirildi!', 'success'); updateRelevantDeviceLists(data); } else { showFlashMessage('Hata: ' + (data.error || 'Bilinmeyen hata.'), 'danger'); refreshAudioSinkList(); } },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); refreshAudioSinkList(); }
            });
        }
        function pairDevice(buttonElement, devicePath) {
            if (!devicePath) { showFlashMessage('Hata: Cihaz yolu (path) bulunamadı.', 'danger'); return; }
            setButtonLoading(buttonElement, true);
            $.ajax({ url: '/api/pair-bluetooth', type: 'POST', contentType: 'application/json', data: JSON.stringify({ device_path: devicePath }),
                success: function(data) { if(data.success) { showFlashMessage(data.message || 'Cihaz başarıyla bağlandı/eşleştirildi!', 'success'); updateRelevantDeviceLists(data); } else { showFlashMessage('Hata: ' + (data.error || 'İşlem başarısız.'), 'danger'); refreshBluetoothList(0); refreshAudioSinkList(); } },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); refreshBluetoothList(0); refreshAudioSinkList(); }
            });
        }
        function disconnectDevice(buttonElement, devicePath) {
             if (!devicePath) { showFlashMessage('Hata: Cihaz yolu (path) bulunamadı.', 'danger'); return; }
             setButtonLoading(buttonElement, true);
             $.ajax({ url: '/api/disconnect-bluetooth', type: 'POST', contentType: 'application/json', data: JSON.stringify({ device_path: devicePath }),
                success: function(data) { if(data.success) { showFlashMessage(data.message || 'Bluetooth bağlantısı kesildi.', 'success'); updateRelevantDeviceLists(data); } else { showFlashMessage('Hata: ' + (data.error || 'Bağlantı kesilemedi.'), 'danger'); refreshBluetoothList(0); refreshAudioSinkList(); } },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); refreshBluetoothList(0); refreshAudioSinkList(); }
            });
        }
        function switchToAlsa(buttonElement) {
            if (!confirm('Varsayılan ses çıkışını ALSA uyumlu bir cihaza değiştirmek istediğinizden emin misiniz?')) { return; }
            setButtonLoading(buttonElement, true);
            $.ajax({ url: '/api/switch-to-alsa', type: 'POST', contentType: 'application/json', data: JSON.stringify({}),
                success: function(data) { if (data.success) { showFlashMessage(data.message || 'Başarıyla ALSA ses çıkışına geçildi.', 'success'); updateRelevantDeviceLists(data); } else { showFlashMessage('ALSA Geçiş Hatası: ' + (data.error || 'Bilinmeyen hata.'), 'danger'); refreshAudioSinkList(); } },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); refreshAudioSinkList(); },
                complete: function() { setButtonLoading(buttonElement, false); }
            });
         }
        function restartSpotifyd(buttonElement) {
             if (!confirm('Spotifyd servisini yeniden başlatmak istediğinizden emin misiniz?')) { return; }
             setButtonLoading(buttonElement, true);
             $.ajax({ url: '/api/restart-spotifyd', type: 'POST',
                 success: function(data) { if (data.success) { showFlashMessage(data.message || 'Spotifyd başarıyla yeniden başlatıldı.', 'success'); } else { showFlashMessage('Spotifyd Hatası: ' + (data.error || 'Bilinmeyen hata.'), 'warning'); } },
                 error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); },
                 complete: function() { setButtonLoading(buttonElement, false); }
             });
         }

        // --- Filtre Yönetimi Fonksiyonları ---
        function renderFilterList(filterType) {
            const mode = currentSettings[filterType + '_filter_mode']; const listKey = filterType + '_' + mode;
            const list = currentSettings[listKey] || []; const listElement = $(`#${filterType}-filter-list`);
            const modeDisplayElement = $(`#${filterType}-mode-display`); modeDisplayElement.text(mode === 'blacklist' ? 'Kara Liste' : 'Beyaz Liste');
            listElement.html('');
            if (list.length === 0) { listElement.html('<li class="text-muted text-center">Liste boş.</li>'); return; }
            const idsToFetch = [];
            if (filterType === 'artist' || filterType === 'track') { list.forEach(item => { if (!spotifyNameCache[item] && item.startsWith(`spotify:${filterType}:`)) { idsToFetch.push(item); } }); }
            const fetchNamesAndRender = () => {
                let html = '';
                list.forEach(item => {
                    let displayName = item; let displayId = '';
                    if (filterType === 'artist' || filterType === 'track') { displayName = spotifyNameCache[item] || item; if(spotifyNameCache[item]) { displayId = `<span class="item-id">${item}</span>`; } }
                    else { displayName = item; }
                    html += `<li><span><span class="item-name">${displayName}</span>${displayId}</span><button class="btn btn-xs btn-outline-danger" onclick="removeFilterItem('${filterType}', '${mode}', '${item}')"><i class="fas fa-times"></i></button></li>`;
                });
                listElement.html(html);
            };
            if (idsToFetch.length > 0) {
                $.ajax({ url: '/api/spotify/details', type: 'POST', contentType: 'application/json', data: JSON.stringify({ ids: idsToFetch, type: filterType }),
                    success: function(data) { if (data.success && data.details) { $.extend(spotifyNameCache, data.details); } },
                    complete: function() { fetchNamesAndRender(); }
                });
            } else { fetchNamesAndRender(); }
        }
        function renderAllFilterLists() { renderFilterList('genre'); renderFilterList('artist'); renderBlockedTracksList(); }
        $('input[name$="_filter_mode"]').on('change', function() {
            const filterType = this.name.replace('_filter_mode', ''); const newMode = this.value;
            currentSettings[filterType + '_filter_mode'] = newMode; renderFilterList(filterType);
            $(`#${filterType}-search-results`).html('');
        });
        function addFilterItem(filterType) {
            const mode = currentSettings[filterType + '_filter_mode']; const listType = mode;
            const inputElement = $(`#${filterType}-add-input`); const item = inputElement.val().trim();
            if (!item) { showFlashMessage('Lütfen eklenecek bir değer girin.', 'warning'); inputElement.focus(); return; }
            const buttonElement = inputElement.next('.input-group-append').find('button'); setButtonLoading(buttonElement[0], true);
            $.ajax({ url: '/api/add-to-list', type: 'POST', contentType: 'application/json', data: JSON.stringify({ filter_type: filterType, list_type: listType, item: item }),
                success: function(data) {
                    if (data.success) { showFlashMessage(data.message || 'Öğe listeye eklendi.', 'success'); currentSettings[filterType + '_' + listType] = data.updated_list; renderFilterList(filterType); inputElement.val(''); }
                    else { showFlashMessage('Hata: ' + (data.error || 'Ekleme başarısız.'), 'danger'); }
                },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); },
                complete: function() { setButtonLoading(buttonElement[0], false); }
            });
        }
        function removeFilterItem(filterType, listType, item) {
            if (!confirm(`'${spotifyNameCache[item] || item}' öğesini listeden çıkarmak istediğinizden emin misiniz?`)) { return; }
            $.ajax({ url: '/api/remove-from-list', type: 'POST', contentType: 'application/json', data: JSON.stringify({ filter_type: filterType, list_type: listType, item: item }),
                success: function(data) {
                    if (data.success) { showFlashMessage(data.message || 'Öğe listeden çıkarıldı.', 'success'); currentSettings[filterType + '_' + listType] = data.updated_list; delete spotifyNameCache[item]; renderFilterList(filterType); }
                    else { showFlashMessage('Hata: ' + (data.error || 'Çıkarma başarısız.'), 'danger'); }
                },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); }
            });
        }
        function searchSpotify(searchType) {
            const inputElement = $(`#${searchType}-search-input`); const query = inputElement.val().trim();
            const resultsContainer = $(`#${searchType}-search-results`);
            const buttonElement = inputElement.next('.input-group-append').find('button');
            if (!query) { showFlashMessage('Lütfen arama terimi girin.', 'warning'); return; }
            resultsContainer.html('<p class="text-muted p-2 text-center">Aranıyor...</p>'); setButtonLoading(buttonElement[0], true);
            $.ajax({ url: '/search', type: 'POST', data: `search_query=${encodeURIComponent(query)}&type=${searchType}`,
                success: function(data) {
                    let html = '';
                    if (data.error) { html = `<p class="text-danger p-2 text-center">${data.error}</p>`; }
                    else if (data.results && data.results.length > 0) {
                        data.results.forEach(item => {
                            const itemId = item.id; const itemName = item.name || 'İsimsiz'; let itemDetails = '';
                            if (searchType === 'track') { itemDetails = item.artist || 'Bilinmeyen Sanatçı'; }
                            else if (searchType === 'artist') { itemDetails = (Array.isArray(item.genres) && item.genres.length > 0) ? item.genres.join(', ') : 'Tür bilgisi yok'; }
                            const itemUri = itemId.startsWith(`spotify:${searchType}:`) ? itemId : `spotify:${searchType}:${itemId}`;
                            html += `<a href="#" class="list-group-item list-group-item-action py-1 px-2" onclick="addFilterItemFromSearch(event, '${searchType}', '${itemUri}', '${itemName.replace(/'/g, "\\'")}')"><small><strong>${itemName}</strong><br>${itemDetails || ''}</small></a>`;
                        });
                    } else { html = '<p class="text-muted p-2 text-center">Sonuç bulunamadı.</p>'; }
                    resultsContainer.html(html);
                },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; resultsContainer.html(`<p class="text-danger p-2 text-center">Hata: ${errorMsg}</p>`); },
                complete: function() { setButtonLoading(buttonElement[0], false); }
            });
        }
        function addFilterItemFromSearch(event, filterType, itemUri, itemName) {
            event.preventDefault(); const mode = currentSettings[filterType + '_filter_mode'];
            if (!confirm(`'${itemName}' öğesini ${filterType} ${mode} listesine eklemek istiyor musunuz?`)) { return; }
            $.ajax({ url: '/api/add-to-list', type: 'POST', contentType: 'application/json', data: JSON.stringify({ filter_type: filterType, list_type: mode, item: itemUri }),
                success: function(data) {
                    if (data.success) { showFlashMessage(`'${itemName}' listeye eklendi.`, 'success'); currentSettings[filterType + '_' + mode] = data.updated_list; spotifyNameCache[itemUri] = itemName; renderFilterList(filterType); $(`#${filterType}-search-results`).html(''); $(`#${filterType}-search-input`).val(''); }
                    else { showFlashMessage('Hata: ' + (data.error || 'Ekleme başarısız.'), 'danger'); }
                },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); }
            });
        }
        function quickBlockItem(buttonElement, itemType, identifier) {
            const itemUri = identifier.startsWith(`spotify:${itemType}:`) ? identifier : `spotify:${itemType}:${identifier}`;
            if (!confirm(`${itemType === 'track' ? 'Şarkıyı' : 'Sanatçıyı'} (${spotifyNameCache[itemUri] || itemUri}) kara listeye eklemek istediğinizden emin misiniz?`)) { return; }
            setButtonLoading(buttonElement, true);
            $.ajax({ url: '/api/block', type: 'POST', contentType: 'application/json', data: JSON.stringify({ type: itemType, identifier: itemUri }),
                success: function(data) { if (data.success) { showFlashMessage(data.message || 'Öğe kara listeye eklendi.', 'success'); const listKey = itemType + '_blacklist'; if (!currentSettings[listKey].includes(itemUri)) { currentSettings[listKey].push(itemUri); } renderAllFilterLists(); } else { showFlashMessage('Hata: ' + (data.error || 'Engelleme başarısız.'), 'danger'); } },
                error: function(xhr) { let errorMsg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : 'Sunucu hatası.'; showFlashMessage(`Hata: ${errorMsg}`, 'danger'); },
                complete: function() { setButtonLoading(buttonElement, false); }
            });
        }

        // --- Engellenmiş Şarkılar Tablosu ---
        function renderBlockedTracksList() {
            const list = currentSettings.track_blacklist || []; const listElement = $('#blocked-tracks-list'); listElement.empty();
            if (list.length === 0) { listElement.html('<tr><td colspan="3" class="text-center text-muted py-3">Engellenmiş şarkı yok.</td></tr>'); return; }
            const idsToFetch = list.filter(id => !spotifyNameCache[id]);
            const renderTable = () => {
                let html = '';
                list.forEach(trackId => {
                    const fullInfo = spotifyNameCache[trackId] || trackId;
                    let trackName = fullInfo.split(' - ')[0] || 'Bilinmiyor';
                    let artistName = fullInfo.split(' - ').slice(1).join(' - ') || 'Bilinmiyor';
                    html += `<tr><td><div><strong>${escapeHTML(trackName)}</strong><div class="small text-muted">${escapeHTML(artistName)}</div></div></td><td class="align-middle text-right"><button class="btn btn-sm btn-outline-danger remove-blocked-track" data-track-id="${escapeHTML(trackId)}"><i class="fas fa-trash-alt"></i></button></td></tr>`;
                });
                listElement.html(html);
            };
            if (idsToFetch.length > 0) {
                $.ajax({ url: '/api/spotify/details', type: 'POST', contentType: 'application/json', data: JSON.stringify({ ids: idsToFetch, type: 'track' }),
                    success: data => { if (data.success && data.details) $.extend(spotifyNameCache, data.details); },
                    complete: renderTable
                });
            } else { renderTable(); }
        }
        function searchBlockedTracks() {
             const filter = $('#blocked-track-search-input').val().toLowerCase();
             $('#blocked-tracks-list tr').each(function() {
                const text = $(this).text().toLowerCase();
                $(this).toggle(text.indexOf(filter) > -1);
             });
         }
        $(document).on('click', '.remove-blocked-track', function() {
            const trackId = $(this).data('track-id');
            if (trackId && confirm(`"${(spotifyNameCache[trackId] || trackId).split(' - ')[0]}" şarkısını kara listeden kaldırmak istiyor musunuz?`)) {
                $.ajax({
                    url: '/api/remove-from-list', type: 'POST', contentType: 'application/json',
                    data: JSON.stringify({ filter_type: 'track', list_type: 'blacklist', item: trackId }),
                    success: data => {
                        if (data.success) {
                            showFlashMessage('Şarkı kara listeden kaldırıldı.', 'success');
                            currentSettings.track_blacklist = data.updated_list;
                            delete spotifyNameCache[trackId]; renderBlockedTracksList();
                        } else { showFlashMessage('Hata: ' + (data.error || 'Şarkı kaldırılamadı.'), 'danger'); }
                    },
                    error: xhr => { showFlashMessage(`Hata: ${(xhr.responseJSON && xhr.responseJSON.error) || 'Sunucu hatası.'}`, 'danger'); }
                });
            }
        });
        function escapeHTML(str) { return $('<div>').text(str).html(); }

        // --- Port Kontrol Fonksiyonları ---
        function checkPort(buttonElement) {
            const statusDiv = document.getElementById('port-status');
            setButtonLoading(buttonElement, true);
            
            $.ajax({
                url: '/api/check-port',
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ port: 22 }),
                success: function(data) {
                    statusDiv.removeClass('d-none alert-success alert-danger');
                    if (data.is_open) {
                        statusDiv.addClass('alert-success').html(`<i class="fas fa-check-circle"></i> SSH Port (22) açık`);
                    } else {
                        statusDiv.addClass('alert-danger').html(`<i class="fas fa-times-circle"></i> SSH Port (22) kapalı`);
                    }
                },
                error: function(xhr) {
                    showFlashMessage('Port kontrolü sırasında bir hata oluştu', 'danger');
                },
                complete: function() {
                    setButtonLoading(buttonElement, false);
                }
            });
        }

        function openPort(buttonElement) {
            if (!confirm('SSH Port (22) açmak istediğinizden emin misiniz?')) {
                return;
            }

            setButtonLoading(buttonElement, true);
            $.ajax({
                url: '/api/open-port',
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ port: 22 }),
                success: function(data) {
                    if (data.success) {
                        showFlashMessage('SSH Port (22) başarıyla açıldı', 'success');
                        checkPort(document.querySelector('.port-control-section .btn-outline-primary'));
                    } else {
                        showFlashMessage('Port açma işlemi başarısız: ' + (data.error || 'Bilinmeyen hata'), 'danger');
                    }
                },
                error: function(xhr) {
                    showFlashMessage('Port açma işlemi sırasında bir hata oluştu', 'danger');
                },
                complete: function() {
                    setButtonLoading(buttonElement, false);
                }
            });
        }

        function closePort(buttonElement) {
            if (!confirm('SSH Port (22) kapatmak istediğinizden emin misiniz?')) {
                return;
            }

            setButtonLoading(buttonElement, true);
            $.ajax({
                url: '/api/close-port',
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ port: 22 }),
                success: function(data) {
                    if (data.success) {
                        showFlashMessage('SSH Port (22) başarıyla kapatıldı', 'success');
                        checkPort(document.querySelector('.port-control-section .btn-outline-primary'));
                    } else {
                        showFlashMessage('Port kapatma işlemi başarısız: ' + (data.error || 'Bilinmeyen hata'), 'danger');
                    }
                },
                error: function(xhr) {
                    showFlashMessage('Port kapatma işlemi sırasında bir hata oluştu', 'danger');
                },
                complete: function() {
                    setButtonLoading(buttonElement, false);
                }
            });
        }
    </script>
</body>
</html>