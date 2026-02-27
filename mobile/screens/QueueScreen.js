import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, TextInput, TouchableOpacity, Image, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { getSocket } from '../services/socket';
import api from '../services/api';

const QueueScreen = ({ route }) => {
    const venue = route.params?.venue;
    const [queue, setQueue] = useState([]);

    // Search State
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [searchLoading, setSearchLoading] = useState(false);

    useEffect(() => {
        if (!venue) return;

        // Fetch initial queue via API
        const fetchQueue = async () => {
            try {
                const response = await api.get('/state');
                if (response.data.success) {
                    setQueue(response.data.queue);
                }
            } catch (error) {
                console.error('Error fetching queue:', error);
            }
        };
        fetchQueue();

        const socket = getSocket();

        const onQueueUpdated = (newQueue) => {
            console.log('Queue Updated:', newQueue.length);
            setQueue(newQueue);
        };

        socket.on('queueUpdated', onQueueUpdated);

        return () => {
            socket.off('queueUpdated', onQueueUpdated);
        };
    }, [venue]);

    const handleSearch = async () => {
        if (!searchQuery.trim()) return;

        setSearchLoading(true);
        setIsSearching(true);
        setSearchResults([]);

        try {
            // Use Backend API for search (Proxy to Spotify)
            // Note: The backend expects form-data for /search usually, but let's check or adjust API
            // app.py: @app.route('/search', methods=['POST']) -> expects form-data 'search_query', 'type'

            const formData = new FormData();
            formData.append('search_query', searchQuery);
            formData.append('type', 'track');

            const response = await api.post('/search', formData, {
                headers: { 'Content-Type': 'multipart/form-data' } // Axios might need help here, or use fetch
            });
            // React Native Axios FormData implementation can be tricky. 
            // If it fails, we might need to adjust backend to accept JSON too.
            // Assuming backend returns { results: [...] }
            if (response.data.results) {
                setSearchResults(response.data.results);
            }
        } catch (error) {
            console.error('Search error:', error);
            Alert.alert('Hata', 'Arama yapılamadı. Sunucu hatası.');
        } finally {
            setSearchLoading(false);
        }
    };

    const handleAddToQueue = async (track) => {
        try {
            // Backend API for adding to queue
            const response = await api.post('/add-to-queue', {
                track_id: track.id || track.uri,
                venue_id: venue.id
            });

            if (response.status === 200 || response.status === 201) {
                Alert.alert('Başarılı', `${track.name} kuyruğa eklendi.`);
                setSearchQuery('');
                setIsSearching(false);
                setSearchResults([]);
            }
        } catch (error) {
            Alert.alert('Hata', error.response?.data?.error || error.message);
        }
    };

    const renderQueueItem = ({ item, index }) => (
        <View style={styles.itemContainer}>
            <View style={styles.positionContainer}>
                <Text style={styles.positionText}>{index + 1}</Text>
            </View>
            <Image source={{ uri: item.image_url || 'https://placehold.co/40' }} style={styles.itemImage} />
            <View style={styles.itemInfo}>
                <Text style={styles.itemTitle} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.itemArtist} numberOfLines={1}>{item.artist}</Text>
            </View>
        </View>
    );

    const renderSearchItem = ({ item }) => (
        <TouchableOpacity style={styles.itemContainer} onPress={() => handleAddToQueue(item)}>
            <Image source={{ uri: item.image || 'https://placehold.co/40' }} style={styles.itemImage} />
            <View style={styles.itemInfo}>
                <Text style={styles.itemTitle} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.itemArtist} numberOfLines={1}>{item.artist}</Text>
            </View>
            <Ionicons name="add-circle" size={24} color="#8b5cf6" />
        </TouchableOpacity>
    );

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <View style={styles.searchBar}>
                    <Ionicons name="search" size={20} color="#6b6b80" />
                    <TextInput
                        style={styles.searchInput}
                        placeholder="Şarkı ara..."
                        placeholderTextColor="#666"
                        value={searchQuery}
                        onChangeText={setSearchQuery}
                        onSubmitEditing={handleSearch}
                        returnKeyType="search"
                    />
                </View>
                <FlatList
                    data={queue}
                    renderItem={renderQueueItem}
                    keyExtractor={item => item.id}
                    contentContainerStyle={{ gap: 8 }}
                    ListEmptyComponent={() => (
                        <Text style={styles.emptyText}>Kuyruk taranıyor veya boş...</Text>
                    )}
                />
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
        padding: 16,
        backgroundColor: 'rgba(255, 255, 255, 0.02)',
    },
    searchBar: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: 'rgba(255, 255, 255, 0.05)',
        borderRadius: 12,
        paddingHorizontal: 12,
        height: 48,
        gap: 8,
    },
    searchInput: {
        flex: 1,
        color: '#fff',
        fontSize: 16,
    },
    listContainer: {
        flex: 1,
        padding: 16,
    },
    metricsContainer: {
        marginBottom: 16,
    },
    metricsText: {
        color: '#a0a0b0',
        fontSize: 14,
    },
    itemContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        padding: 12,
        borderRadius: 12,
        gap: 12,
    },
    positionContainer: {
        width: 24,
        height: 24,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: 'rgba(255, 255, 255, 0.1)',
        borderRadius: 12,
    },
    positionText: {
        color: '#a0a0b0',
        fontSize: 12,
        fontWeight: 'bold',
    },
    itemImage: {
        width: 48,
        height: 48,
        borderRadius: 8,
    },
    itemInfo: {
        flex: 1,
        justifyContent: 'center',
    },
    itemTitle: {
        color: '#fff',
        fontSize: 16,
        fontWeight: '500',
    },
    itemArtist: {
        color: '#a0a0b0',
        fontSize: 14,
    },
    emptyText: {
        color: '#6b6b80',
        textAlign: 'center',
        marginTop: 32,
    },
});

export default QueueScreen;
