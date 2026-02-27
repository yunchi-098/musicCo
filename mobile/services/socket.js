import io from 'socket.io-client';
import { API_URL } from '../constants';

let socket = null;

export const connectSocket = () => {
    socket = io(API_URL, {
        transports: ['websocket'],
        reconnection: true,
    });

    socket.on('connect', () => {
        console.log('Socket connected:', socket.id);
    });

    socket.on('disconnect', () => {
        console.log('Socket disconnected');
    });

    return socket;
};

export const getSocket = () => {
    if (!socket) {
        return connectSocket();
    }
    return socket;
};

export const joinVenue = (venueId) => {
    if (socket) {
        socket.emit('join_venue', { venue_id: venueId });
    }
};
