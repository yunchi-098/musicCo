/**
 * MusicCo Modern UI - JavaScript
 * WebSocket, Toast Notifications, Theme Toggle, QR Modal
 */

// ========================================
// CONFIGURATION
// ========================================
const CONFIG = {
    toastDuration: 3000,
    debounceDelay: 300,
    animationDuration: 300
};

// ========================================
// WEBSOCKET CONNECTION
// ========================================
class SocketManager {
    constructor() {
        this.socket = null;
        this.venueId = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
    }

    connect(venueId) {
        if (typeof io === 'undefined') {
            console.warn('Socket.IO not loaded');
            return;
        }

        this.venueId = venueId;
        this.socket = io({
            transports: ['websocket', 'polling']
        });

        this.socket.on('connect', () => {
            console.log('WebSocket connected');
            this.connected = true;
            this.reconnectAttempts = 0;

            if (this.venueId) {
                this.socket.emit('join_venue', { venue_id: this.venueId });
            }
        });

        this.socket.on('disconnect', () => {
            console.log('WebSocket disconnected');
            this.connected = false;
        });

        this.socket.on('queue_updated', (data) => {
            console.log('Queue updated:', data);
            this.handleQueueUpdate(data.queue);
        });

        this.socket.on('now_playing', (data) => {
            console.log('Now playing:', data);
            this.handleNowPlaying(data);
        });

        this.socket.on('connect_error', () => {
            this.reconnectAttempts++;
            if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.error('Max reconnect attempts reached');
            }
        });
    }

    handleQueueUpdate(queue) {
        const event = new CustomEvent('queueUpdated', { detail: queue });
        document.dispatchEvent(event);
    }

    handleNowPlaying(track) {
        const event = new CustomEvent('nowPlaying', { detail: track });
        document.dispatchEvent(event);
    }
}

const socketManager = new SocketManager();

// ========================================
// TOAST NOTIFICATIONS
// ========================================
class ToastManager {
    constructor() {
        this.container = null;
        this.init();
    }

    init() {
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        document.body.appendChild(this.container);
    }

    show(message, type = 'info', duration = CONFIG.toastDuration) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${message}</span>
        `;

        this.container.appendChild(toast);

        // Auto remove
        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.3s ease forwards';
            setTimeout(() => toast.remove(), 300);
        }, duration);

        return toast;
    }

    success(message) { return this.show(message, 'success'); }
    error(message) { return this.show(message, 'error'); }
    warning(message) { return this.show(message, 'warning'); }
    info(message) { return this.show(message, 'info'); }
}

const toast = new ToastManager();

// ========================================
// THEME MANAGER
// ========================================
class ThemeManager {
    constructor() {
        this.theme = localStorage.getItem('theme') || 'dark';
        this.init();
    }

    init() {
        document.documentElement.setAttribute('data-theme', this.theme);
    }

    toggle() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', this.theme);
        localStorage.setItem('theme', this.theme);
        return this.theme;
    }

    get isDark() {
        return this.theme === 'dark';
    }
}

const themeManager = new ThemeManager();

// ========================================
// QR CODE MODAL
// ========================================
class QRModal {
    constructor() {
        this.modal = null;
        this.init();
    }

    init() {
        this.modal = document.getElementById('qr-modal');
        if (this.modal) {
            this.modal.addEventListener('click', (e) => {
                if (e.target === this.modal) this.close();
            });
        }
    }

    async show() {
        try {
            const response = await fetch('/api/venue/qr-code');
            const data = await response.json();

            if (data.success) {
                this.modal = this.createModal(data);
                document.body.appendChild(this.modal);

                // Trigger animation
                requestAnimationFrame(() => {
                    this.modal.classList.add('active');
                });
            } else {
                toast.error(data.error || 'QR kod oluşturulamadı');
            }
        } catch (error) {
            console.error('QR code error:', error);
            toast.error('QR kod yüklenirken hata oluştu');
        }
    }

    createModal(data) {
        const modal = document.createElement('div');
        modal.className = 'qr-modal';
        modal.id = 'qr-modal';
        modal.innerHTML = `
            <div class="qr-modal-content">
                <h2 style="margin-bottom: 1rem;">${data.venue_name}</h2>
                <img src="${data.qr_code}" alt="QR Code">
                <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 1rem;">
                    Müşterileriniz bu QR kodu tarayarak şarkı ekleyebilir
                </p>
                <div class="flex gap-sm justify-center">
                    <a href="/api/venue/qr-code/download" class="btn btn-primary" download>
                        📥 İndir
                    </a>
                    <button class="btn btn-secondary" onclick="qrModal.close()">
                        Kapat
                    </button>
                </div>
            </div>
        `;

        modal.addEventListener('click', (e) => {
            if (e.target === modal) this.close();
        });

        return modal;
    }

    close() {
        if (this.modal) {
            this.modal.classList.remove('active');
            setTimeout(() => {
                this.modal.remove();
                this.modal = null;
            }, CONFIG.animationDuration);
        }
    }
}

const qrModal = new QRModal();

// ========================================
// SEARCH AUTOCOMPLETE
// ========================================
class SearchAutocomplete {
    constructor(inputSelector, resultsSelector) {
        this.input = document.querySelector(inputSelector);
        this.results = document.querySelector(resultsSelector);
        this.debounceTimer = null;

        if (this.input) {
            this.init();
        }
    }

    init() {
        this.input.addEventListener('input', () => {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                this.search(this.input.value);
            }, CONFIG.debounceDelay);
        });
    }

    async search(query) {
        if (query.length < 2) {
            this.clearResults();
            return;
        }

        try {
            const response = await fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': getCsrfToken()
                },
                body: `search_query=${encodeURIComponent(query)}&type=track`
            });

            const data = await response.json();

            if (data.results) {
                this.displayResults(data.results);
            }
        } catch (error) {
            console.error('Search error:', error);
        }
    }

    displayResults(results) {
        if (!this.results) return;

        this.results.innerHTML = results.slice(0, 8).map(track => `
            <div class="song-card animate-fade-in" onclick="addToQueue('${track.id}')">
                <img class="cover" src="${track.image_url || '/static/placeholder.png'}" alt="${track.name}">
                <div class="info">
                    <div class="title">${track.name}</div>
                    <div class="artist">${track.artist}</div>
                </div>
                <button class="btn btn-primary btn-icon" onclick="event.stopPropagation(); addToQueue('${track.id}')">
                    +
                </button>
            </div>
        `).join('');
    }

    clearResults() {
        if (this.results) {
            this.results.innerHTML = '';
        }
    }
}

// ========================================
// UTILITY FUNCTIONS
// ========================================
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

async function addToQueue(trackId, venueId = null) {
    try {
        const body = { track_id: trackId };
        if (venueId) body.venue_id = venueId;

        const response = await fetch('/add-to-queue', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(body)
        });

        const data = await response.json();

        if (data.success) {
            toast.success(data.message);
        } else {
            toast.error(data.error || 'Şarkı eklenemedi');
        }
    } catch (error) {
        console.error('Add to queue error:', error);
        toast.error('Bağlantı hatası');
    }
}

// ========================================
// INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    // Initialize search if exists
    const searchInput = document.querySelector('#search-input');
    const searchResults = document.querySelector('#search-results');
    if (searchInput && searchResults) {
        new SearchAutocomplete('#search-input', '#search-results');
    }

    // Connect WebSocket if venue ID exists
    const venueIdMeta = document.querySelector('meta[name="venue-id"]');
    if (venueIdMeta) {
        socketManager.connect(venueIdMeta.content);
    }

    // Theme toggle buttons
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            themeManager.toggle();
        });
    });

    // Add stagger animation to lists
    document.querySelectorAll('.stagger-animation').forEach(list => {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('animated');
                }
            });
        });
        observer.observe(list);
    });

    console.log('MusicCo Modern UI initialized');
});

// Export for global usage
window.toast = toast;
window.qrModal = qrModal;
window.themeManager = themeManager;
window.addToQueue = addToQueue;
window.socketManager = socketManager;
