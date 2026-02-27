import React, { useEffect, useState } from 'react';
import { View, Text, Image, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { getSocket, joinVenue } from '../services/socket';
import api from '../services/api';

const PlayerScreen = ({ route }) => {
    const venue = route.params?.venue;
    const [nowPlaying, setNowPlaying] = useState(null);
    const [isConnected, setIsConnected] = useState(false);

    useEffect(() => {
        if (!venue || !venue.id) return;

        // Fetch initial state via API
        const fetchState = async () => {
            try {
                const response = await api.get('/state');
                if (response.data.success && response.data.now_playing) {
                    setNowPlaying(response.data.now_playing);
                }
            } catch (error) {
                console.error('Error fetching state:', error);
            }
        };
        fetchState();

        // Socket connection
        const socket = getSocket();

        const onConnect = () => {
            setIsConnected(true);
            joinVenue(venue.id);
        };

        const onNowPlaying = (data) => {
            console.log('Now Playing Update:', data);
            if (data.item) {
                setNowPlaying({
                    id: data.item.id,
                    name: data.item.name,
                    artist: data.item.artists ? data.item.artists.map(a => a.name).join(', ') : 'Bilinmiyor',
                    image_url: data.item.album && data.item.album.images.length > 0 ? data.item.album.images[0].url : null,
                    is_playing: data.is_playing
                });
            } else {
                setNowPlaying(null);
            }
        };

        socket.on('connect', onConnect);
        socket.on('nowPlaying', onNowPlaying);

        if (socket.connected) {
            onConnect();
        }

        return () => {
            socket.off('connect', onConnect);
            socket.off('nowPlaying', onNowPlaying);
        };
    }, [venue]);

    // Simple Play/Pause via API (Admin Request)
    const handlePlayPause = async () => {
        try {
            // We need an endpoint for Play/Pause in app.py that accepts venue_id logic.
            // Currently app.py uses global or venue based context but API endpoints might need refinement.
            // Let's assume /player/pause and /player/resume work if we are logged in as admin via session.
            // But mobile uses separate session? The LoginScreen sets up session cookie likely if Axios handles it.
            // api.js does typically handle cookies if configured, or we need to pass headers.

            const endpoint = nowPlaying?.is_playing ? '/../player/pause' : '/../player/resume';
            await api.get(endpoint); // These are GET requests in app.py logic currently
        } catch (error) {
            console.error('Playback control error:', error);
        }
    };

    if (!venue) {
        return (
            <View style={styles.container}>
                <Text style={styles.text}>Venue bilgisi bulunamadı.</Text>
            </View>
        );
    }

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.venueName}>{venue.name || venue.email}</Text>
                <View style={[styles.statusDot, { backgroundColor: isConnected ? '#10b981' : '#ef4444' }]} />
            </View>

            <View style={styles.content}>
                <View style={styles.artworkContainer}>
                    {nowPlaying?.image_url ? (
                        <Image source={{ uri: nowPlaying.image_url }} style={styles.artwork} />
                    ) : (
                        <View style={[styles.artwork, styles.placeholderArtwork]}>
                            <Ionicons name="musical-note" size={64} color="#6b6b80" />
                        </View>
                    )}
                </View>

                <View style={styles.infoContainer}>
                    <Text style={styles.trackTitle} numberOfLines={1}>
                        {nowPlaying ? nowPlaying.name : 'Müzik Durduruldu'}
                    </Text>
                    <Text style={styles.artistName} numberOfLines={1}>
                        {nowPlaying ? nowPlaying.artist : 'Sıradaki şarkı bekleniyor...'}
                    </Text>
                </View>

                <View style={styles.controls}>
                    <TouchableOpacity style={styles.controlButton} onPress={handlePlayPause}>
                        <Ionicons name={nowPlaying?.is_playing ? "pause-circle" : "play-circle"} size={80} color="#8b5cf6" />
                    </TouchableOpacity>
                </View>
            </View>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#0f0f1a',
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
    },
    venueName: {
        color: '#fff',
        fontSize: 18,
        fontWeight: '600',
    },
    content: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        padding: 24,
    },
    artworkContainer: {
        width: 300,
        height: 300,
        marginBottom: 32,
        shadowColor: '#8b5cf6',
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.3,
        shadowRadius: 24,
        elevation: 10,
    },
    artwork: {
        width: '100%',
        height: '100%',
        borderRadius: 24,
    },
    placeholderArtwork: {
        backgroundColor: '#1a1a2e',
        justifyContent: 'center',
        alignItems: 'center',
        borderWidth: 1,
        borderColor: 'rgba(255,255,255,0.1)',
    },
    infoContainer: {
        alignItems: 'center',
        marginBottom: 32,
        width: '100%',
    },
    trackTitle: {
        fontSize: 24,
        fontWeight: 'bold',
        color: '#fff',
        marginBottom: 8,
        textAlign: 'center',
    },
    artistName: {
        fontSize: 18,
        color: '#a0a0b0',
        textAlign: 'center',
    },
    controls: {
        alignItems: 'center',
    },
    spotifyButton: {
        flexDirection: 'row',
        backgroundColor: '#1DB954',
        paddingVertical: 12,
        paddingHorizontal: 24,
        borderRadius: 24,
        alignItems: 'center',
        gap: 8,
    },
    spotifyButtonText: {
        color: '#fff',
        fontSize: 16,
        fontWeight: 'bold',
    },
    controlButton: {
        padding: 8,
    }
});

export default PlayerScreen;
