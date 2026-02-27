import * as SecureStore from 'expo-secure-store';
import { makeRedirectUri, useAuthRequest, ResponseType } from 'expo-auth-session';

// Spotify Configuration
const discovery = {
    authorizationEndpoint: 'https://accounts.spotify.com/authorize',
    tokenEndpoint: 'https://accounts.spotify.com/api/token',
};

// Replace with your Spotify Client ID
const CLIENT_ID = 'YOUR_SPOTIFY_CLIENT_ID';
const REDIRECT_URI = makeRedirectUri({
    scheme: 'musicco'
});

export const useSpotifyAuth = () => {
    const [request, response, promptAsync] = useAuthRequest(
        {
            responseType: ResponseType.Token,
            clientId: CLIENT_ID,
            scopes: [
                'user-read-currently-playing',
                'user-read-playback-state',
                'user-modify-playback-state',
                'streaming',
            ],
            usePKCE: false,
            redirectUri: REDIRECT_URI,
        },
        discovery
    );

    return { request, response, promptAsync };
};
