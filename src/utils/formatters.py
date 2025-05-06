def format_track_info(track):
    """Spotify şarkı bilgilerini formatlar."""
    if not track:
        return None
        
    return {
        'id': track.get('id'),
        'name': track.get('name'),
        'artist': track.get('artists', [{}])[0].get('name', 'Bilinmeyen Sanatçı'),
        'album': track.get('album', {}).get('name', 'Bilinmeyen Albüm'),
        'duration_ms': track.get('duration_ms', 0),
        'image_url': track.get('album', {}).get('images', [{}])[0].get('url'),
        'uri': track.get('uri')
    }

def format_duration(ms):
    """Milisaniye cinsinden süreyi dakika:saniye formatına çevirir."""
    if not ms:
        return "0:00"
    seconds = int(ms / 1000)
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}" 