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

def format_artist_info(artist):
    """Spotify sanatçı bilgilerini formatlar."""
    if not artist:
        return None
        
    return {
        'id': artist.get('id'),
        'name': artist.get('name'),
        'image_url': artist.get('images', [{}])[0].get('url'),
        'uri': artist.get('uri'),
        'genres': artist.get('genres', []),
        'popularity': artist.get('popularity', 0)
    }

def format_playlist_info(playlist):
    """Spotify çalma listesi bilgilerini formatlar."""
    if not playlist:
        return None
        
    return {
        'id': playlist.get('id'),
        'name': playlist.get('name'),
        'description': playlist.get('description'),
        'image_url': playlist.get('images', [{}])[0].get('url'),
        'uri': playlist.get('uri'),
        'tracks_count': playlist.get('tracks', {}).get('total', 0),
        'owner': playlist.get('owner', {}).get('display_name', 'Bilinmeyen Kullanıcı')
    }

def format_duration(ms):
    """Milisaniye cinsinden süreyi dakika:saniye formatına çevirir."""
    if not ms:
        return "0:00"
    seconds = int(ms / 1000)
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}" 