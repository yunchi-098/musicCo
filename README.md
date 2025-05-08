# Müzik Çalar

Bu proje, Spotify API'sini kullanarak bir müzik çalar uygulamasıdır. Flask web framework'ü ile geliştirilmiştir.

## Özellikler

- Spotify entegrasyonu
- Şarkı çalma, duraklatma, devam ettirme
- Çalma listesi yönetimi
- Tür ve sanatçı filtreleme
- Zaman bazlı çalma profilleri
- Admin paneli
- Otomatik ilerleme

## Kurulum

1. Gerekli paketleri yükleyin:
```bash
pip install -r requirements.txt
```

2. Spotify Developer hesabı oluşturun ve uygulama kimlik bilgilerini alın:
   - [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)'a gidin
   - Yeni bir uygulama oluşturun
   - Client ID ve Client Secret'ı alın

3. `.env` dosyası oluşturun ve Spotify kimlik bilgilerini ekleyin:
```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:5000/callback
```

4. Uygulamayı çalıştırın:
```bash
python app.py
```

## Kullanım

1. Tarayıcınızda `http://localhost:5000` adresine gidin
2. Spotify hesabınızla giriş yapın
3. Şarkı arayın ve çalma listesine ekleyin
4. Admin paneline erişmek için `/admin/control` adresini kullanın

## Admin Paneli

Admin panelinde şunları yapabilirsiniz:
- Maksimum kuyruk uzunluğunu ayarlama
- Tür ve sanatçı filtrelerini yönetme
- Zaman profillerini görüntüleme
- Otomatik ilerlemeyi kontrol etme

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır. Detaylar için `LICENSE` dosyasına bakın.