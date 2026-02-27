#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Veritabanı Modelleri - Mekan ve Abonelik Sistemi
"""

import sqlite3
import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_FILE = 'musicco.db'


def get_db_connection():
    """Veritabanı bağlantısı oluşturur"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Veritabanı tablolarını oluşturur"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Mekanlar (Venues) tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS venues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            slug TEXT UNIQUE,
            subscription_type TEXT DEFAULT 'free',
            subscription_start DATETIME,
            subscription_end DATETIME,
            is_active INTEGER DEFAULT 1,
            api_key TEXT UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME
        )
    ''')
    
    # Venue Spotify Data tablosu (her venue kendi token'ına sahip)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS venue_spotify_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER UNIQUE NOT NULL,
            spotify_token_info TEXT,
            spotify_user_name TEXT,
            spotify_user_id TEXT,
            active_device_id TEXT,
            active_playlist_uri TEXT,
            auto_advance_enabled INTEGER DEFAULT 1,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (venue_id) REFERENCES venues (id)
        )
    ''')
    
    # Venue Kuyrukları tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS venue_queues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER NOT NULL,
            song_uri TEXT NOT NULL,
            song_name TEXT,
            artist_name TEXT,
            artist_ids TEXT,
            image_url TEXT,
            added_by TEXT,
            position INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (venue_id) REFERENCES venues (id)
        )
    ''')
    
    # Venue Ayarları tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS venue_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER UNIQUE NOT NULL,
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (venue_id) REFERENCES venues (id)
        )
    ''')
    
    # Abonelik Planları tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscription_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            price REAL NOT NULL,
            duration_days INTEGER NOT NULL,
            max_songs_per_day INTEGER DEFAULT -1,
            max_queue_length INTEGER DEFAULT 20,
            allow_filters INTEGER DEFAULT 1,
            allow_playlists INTEGER DEFAULT 1,
            features TEXT,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Abonelik Geçmişi tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscription_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            start_date DATETIME NOT NULL,
            end_date DATETIME NOT NULL,
            amount_paid REAL,
            payment_method TEXT,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (venue_id) REFERENCES venues (id),
            FOREIGN KEY (plan_id) REFERENCES subscription_plans (id)
        )
    ''')
    
    # Oturum tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER NOT NULL,
            session_token TEXT UNIQUE NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY (venue_id) REFERENCES venues (id)
        )
    ''')
    
    # Analytics - Şarkı İstekleri tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS song_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER NOT NULL,
            track_uri TEXT NOT NULL,
            track_name TEXT,
            artist_name TEXT,
            requester_ip TEXT,
            status TEXT DEFAULT 'added',
            played_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (venue_id) REFERENCES venues (id)
        )
    ''')
    
    # Varsayılan abonelik planlarını ekle (yoksa)
    plans = [
        ('free', 'Ücretsiz Deneme', 0, 7, 10, 5, 0, 0, 
         json.dumps({'description': '7 günlük deneme süresi', 'features': ['Günde 10 şarkı', '5 şarkılık kuyruk']})),
        ('basic', 'Temel Plan', 199.99, 30, -1, 20, 1, 0,
         json.dumps({'description': 'Aylık temel plan', 'features': ['Sınırsız şarkı', '20 şarkılık kuyruk', 'Filtre desteği']})),
        ('premium', 'Premium Plan', 399.99, 30, -1, 50, 1, 1,
         json.dumps({'description': 'Aylık premium plan', 'features': ['Sınırsız şarkı', '50 şarkılık kuyruk', 'Tüm filtreler', 'Çalma listesi desteği', 'Öncelikli destek']}))
    ]
    
    for plan in plans:
        cursor.execute('''
            INSERT OR IGNORE INTO subscription_plans 
            (name, display_name, price, duration_days, max_songs_per_day, max_queue_length, allow_filters, allow_playlists, features)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', plan)
    
    conn.commit()
    conn.close()
    print("Veritabanı başarıyla başlatıldı.")


class Venue:
    """Mekan (Venue) modeli"""
    
    def __init__(self, id=None, name=None, email=None, password_hash=None, 
                 phone=None, address=None, slug=None, subscription_type='free',
                 subscription_start=None, subscription_end=None, 
                 is_active=True, api_key=None, created_at=None, last_login=None):
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash
        self.phone = phone
        self.address = address
        self.slug = slug
        self.subscription_type = subscription_type
        self.subscription_start = subscription_start
        self.subscription_end = subscription_end
        self.is_active = is_active
        self.api_key = api_key
        self.created_at = created_at
        self.last_login = last_login
    
    @staticmethod
    def create(name, email, password, phone=None, address=None, slug=None):
        """Yeni mekan oluşturur"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Şifreyi hashle
        password_hash = generate_password_hash(password)
        
        # API anahtarı oluştur
        api_key = secrets.token_hex(32)
        
        # Slug oluştur (yoksa isimden türet)
        if not slug:
            import re
            slug = re.sub(r'[^a-z0-9]+', '-', name.lower().strip()).strip('-')
        
        # Ücretsiz deneme süresi
        subscription_start = datetime.now()
        subscription_end = subscription_start + timedelta(days=7)
        
        try:
            cursor.execute('''
                INSERT INTO venues (name, email, password_hash, phone, address, slug,
                                   subscription_type, subscription_start, subscription_end, api_key)
                VALUES (?, ?, ?, ?, ?, ?, 'free', ?, ?, ?)
            ''', (name, email, password_hash, phone, address, slug,
                  subscription_start.isoformat(), subscription_end.isoformat(), api_key))
            conn.commit()
            venue_id = cursor.lastrowid
            conn.close()
            return {'success': True, 'venue_id': venue_id, 'api_key': api_key, 'slug': slug}
        except sqlite3.IntegrityError as e:
            conn.close()
            if 'email' in str(e).lower():
                return {'success': False, 'error': 'Bu e-posta adresi zaten kayıtlı.'}
            if 'slug' in str(e).lower():
                return {'success': False, 'error': 'Bu subdomain zaten kullanılıyor.'}
            return {'success': False, 'error': f'Kayıt hatası: {e}'}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': f'Beklenmedik hata: {e}'}
    
    @staticmethod
    def authenticate(email, password):
        """E-posta ve şifre ile giriş yapar"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM venues WHERE email = ? AND is_active = 1', (email,))
        row = cursor.fetchone()
        
        if row and check_password_hash(row['password_hash'], password):
            # Son giriş zamanını güncelle
            cursor.execute('UPDATE venues SET last_login = ? WHERE id = ?', 
                          (datetime.now().isoformat(), row['id']))
            conn.commit()
            conn.close()
            return Venue.from_row(row)
        
        conn.close()
        return None
    
    @staticmethod
    def get_by_id(venue_id):
        """ID ile mekan bilgisi alır"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM venues WHERE id = ?', (venue_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Venue.from_row(row)
        return None
    
    @staticmethod
    def get_by_email(email):
        """E-posta ile mekan bilgisi alır"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM venues WHERE email = ?', (email,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Venue.from_row(row)
        return None
    
    @staticmethod
    def get_by_slug(slug):
        """Slug ile mekan bilgisi alır (subdomain routing için)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM venues WHERE slug = ? AND is_active = 1', (slug,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Venue.from_row(row)
        return None
    
    @staticmethod
    def from_row(row):
        """Veritabanı satırından Venue objesi oluşturur"""
        return Venue(
            id=row['id'],
            name=row['name'],
            email=row['email'],
            password_hash=row['password_hash'],
            phone=row['phone'],
            address=row['address'],
            slug=row['slug'] if 'slug' in row.keys() else None,
            subscription_type=row['subscription_type'],
            subscription_start=row['subscription_start'],
            subscription_end=row['subscription_end'],
            is_active=bool(row['is_active']),
            api_key=row['api_key'],
            created_at=row['created_at'],
            last_login=row['last_login']
        )
    
    def is_subscription_active(self):
        """Abonelik aktif mi kontrol eder"""
        if not self.subscription_end:
            return False
        
        try:
            end_date = datetime.fromisoformat(self.subscription_end)
            return datetime.now() < end_date
        except:
            return False
    
    def get_subscription_days_left(self):
        """Kalan abonelik günü sayısını döndürür"""
        if not self.subscription_end:
            return 0
        
        try:
            end_date = datetime.fromisoformat(self.subscription_end)
            delta = end_date - datetime.now()
            return max(0, delta.days)
        except:
            return 0
    
    def get_plan_limits(self):
        """Mevcut plana göre limitleri döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM subscription_plans WHERE name = ?', (self.subscription_type,))
        plan = cursor.fetchone()
        conn.close()
        
        if plan:
            return {
                'max_songs_per_day': plan['max_songs_per_day'],
                'max_queue_length': plan['max_queue_length'],
                'allow_filters': bool(plan['allow_filters']),
                'allow_playlists': bool(plan['allow_playlists'])
            }
        
        # Varsayılan limitler (free plan)
        return {
            'max_songs_per_day': 10,
            'max_queue_length': 5,
            'allow_filters': False,
            'allow_playlists': False
        }
    
    def upgrade_subscription(self, plan_name, amount_paid=0, payment_method='manual'):
        """Aboneliği yükseltir"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Planı bul
        cursor.execute('SELECT * FROM subscription_plans WHERE name = ?', (plan_name,))
        plan = cursor.fetchone()
        
        if not plan:
            conn.close()
            return {'success': False, 'error': 'Geçersiz plan.'}
        
        # Yeni abonelik tarihleri
        start_date = datetime.now()
        end_date = start_date + timedelta(days=plan['duration_days'])
        
        try:
            # Mekani güncelle
            cursor.execute('''
                UPDATE venues 
                SET subscription_type = ?, subscription_start = ?, subscription_end = ?
                WHERE id = ?
            ''', (plan_name, start_date.isoformat(), end_date.isoformat(), self.id))
            
            # Geçmişe kaydet
            cursor.execute('''
                INSERT INTO subscription_history 
                (venue_id, plan_id, start_date, end_date, amount_paid, payment_method)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (self.id, plan['id'], start_date.isoformat(), end_date.isoformat(), 
                  amount_paid, payment_method))
            
            conn.commit()
            conn.close()
            
            # Objeyi güncelle
            self.subscription_type = plan_name
            self.subscription_start = start_date.isoformat()
            self.subscription_end = end_date.isoformat()
            
            return {'success': True, 'message': f'{plan["display_name"]} planına yükseltildi.'}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': f'Abonelik güncellenemedi: {e}'}
    
    def to_dict(self):
        """Sözlük olarak döndürür"""
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'subscription_type': self.subscription_type,
            'subscription_end': self.subscription_end,
            'is_active': self.is_active,
            'days_left': self.get_subscription_days_left(),
            'is_subscription_active': self.is_subscription_active()
        }


class SubscriptionPlan:
    """Abonelik Planı modeli"""
    
    @staticmethod
    def get_all():
        """Tüm aktif planları döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM subscription_plans WHERE is_active = 1 ORDER BY price')
        plans = cursor.fetchall()
        conn.close()
        
        result = []
        for plan in plans:
            features = json.loads(plan['features']) if plan['features'] else {}
            result.append({
                'id': plan['id'],
                'name': plan['name'],
                'display_name': plan['display_name'],
                'price': plan['price'],
                'duration_days': plan['duration_days'],
                'max_songs_per_day': plan['max_songs_per_day'],
                'max_queue_length': plan['max_queue_length'],
                'allow_filters': bool(plan['allow_filters']),
                'allow_playlists': bool(plan['allow_playlists']),
                'features': features
            })
        
        return result
    
    @staticmethod
    def get_by_name(name):
        """İsimle plan bilgisi alır"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM subscription_plans WHERE name = ?', (name,))
        plan = cursor.fetchone()
        conn.close()
        
        if plan:
            features = json.loads(plan['features']) if plan['features'] else {}
            return {
                'id': plan['id'],
                'name': plan['name'],
                'display_name': plan['display_name'],
                'price': plan['price'],
                'duration_days': plan['duration_days'],
                'features': features
            }
        return None


class VenueSpotifyData:
    """Venue Spotify Verisi modeli"""
    
    @staticmethod
    def get_by_venue_id(venue_id):
        """Venue ID ile Spotify verisini alır"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM venue_spotify_data WHERE venue_id = ?', (venue_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row['id'],
                'venue_id': row['venue_id'],
                'spotify_token_info': json.loads(row['spotify_token_info']) if row['spotify_token_info'] else None,
                'spotify_user_name': row['spotify_user_name'],
                'spotify_user_id': row['spotify_user_id'],
                'active_device_id': row['active_device_id'],
                'active_playlist_uri': row['active_playlist_uri'],
                'auto_advance_enabled': bool(row['auto_advance_enabled']),
                'updated_at': row['updated_at']
            }
        return None
    
    @staticmethod
    def save_token(venue_id, token_info, user_name=None, user_id=None):
        """Spotify token bilgisini kaydeder veya günceller"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        token_json = json.dumps(token_info) if token_info else None
        now = datetime.now().isoformat()
        
        try:
            cursor.execute('''
                INSERT INTO venue_spotify_data (venue_id, spotify_token_info, spotify_user_name, spotify_user_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(venue_id) DO UPDATE SET 
                spotify_token_info = excluded.spotify_token_info,
                spotify_user_name = COALESCE(excluded.spotify_user_name, spotify_user_name),
                spotify_user_id = COALESCE(excluded.spotify_user_id, spotify_user_id),
                updated_at = excluded.updated_at
            ''', (venue_id, token_json, user_name, user_id, now))
            conn.commit()
            conn.close()
            return {'success': True}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def update_device(venue_id, device_id):
        """Aktif cihazı günceller"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE venue_spotify_data SET active_device_id = ?, updated_at = ?
            WHERE venue_id = ?
        ''', (device_id, datetime.now().isoformat(), venue_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_playlist(venue_id, playlist_uri):
        """Aktif çalma listesini günceller"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE venue_spotify_data SET active_playlist_uri = ?, updated_at = ?
            WHERE venue_id = ?
        ''', (playlist_uri, datetime.now().isoformat(), venue_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def set_auto_advance(venue_id, enabled):
        """Otomatik geçişi ayarlar"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE venue_spotify_data SET auto_advance_enabled = ?, updated_at = ?
            WHERE venue_id = ?
        ''', (1 if enabled else 0, datetime.now().isoformat(), venue_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def delete_token(venue_id):
        """Spotify token'ı siler"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE venue_spotify_data SET spotify_token_info = NULL WHERE venue_id = ?', (venue_id,))
        conn.commit()
        conn.close()


class VenueQueue:
    """Venue Kuyruk modeli"""
    
    @staticmethod
    def get_queue(venue_id):
        """Venue'nun kuyruğunu döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM venue_queues WHERE venue_id = ? ORDER BY position, created_at
        ''', (venue_id,))
        rows = cursor.fetchall()
        conn.close()
        
        queue = []
        for row in rows:
            queue.append({
                'id': row['song_uri'],
                'name': row['song_name'],
                'artist': row['artist_name'],
                'artist_ids': json.loads(row['artist_ids']) if row['artist_ids'] else [],
                'image_url': row['image_url'],
                'added_by': row['added_by'],
                'queue_id': row['id']
            })
        return queue
    
    @staticmethod
    def add_song(venue_id, song_uri, song_name, artist_name, artist_ids=None, image_url=None, added_by=None):
        """Kuyruğa şarkı ekler"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Mevcut maksimum pozisyonu bul
        cursor.execute('SELECT MAX(position) as max_pos FROM venue_queues WHERE venue_id = ?', (venue_id,))
        result = cursor.fetchone()
        next_position = (result['max_pos'] or 0) + 1
        
        artist_ids_json = json.dumps(artist_ids) if artist_ids else None
        
        try:
            cursor.execute('''
                INSERT INTO venue_queues (venue_id, song_uri, song_name, artist_name, artist_ids, image_url, added_by, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (venue_id, song_uri, song_name, artist_name, artist_ids_json, image_url, added_by, next_position))
            conn.commit()
            queue_id = cursor.lastrowid
            conn.close()
            return {'success': True, 'queue_id': queue_id, 'position': next_position}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def remove_song(venue_id, song_uri):
        """Kuyruktan şarkı çıkarır"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM venue_queues WHERE venue_id = ? AND song_uri = ?', (venue_id, song_uri))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return {'success': deleted > 0, 'deleted': deleted}
    
    @staticmethod
    def pop_first(venue_id):
        """Kuyruğun ilk şarkısını çıkarır ve döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM venue_queues WHERE venue_id = ? ORDER BY position, created_at LIMIT 1
        ''', (venue_id,))
        row = cursor.fetchone()
        
        if row:
            song = {
                'id': row['song_uri'],
                'name': row['song_name'],
                'artist': row['artist_name'],
                'artist_ids': json.loads(row['artist_ids']) if row['artist_ids'] else [],
                'image_url': row['image_url']
            }
            cursor.execute('DELETE FROM venue_queues WHERE id = ?', (row['id'],))
            conn.commit()
            conn.close()
            return song
        
        conn.close()
        return None
    
    @staticmethod
    def clear_queue(venue_id):
        """Kuyruğu temizler"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM venue_queues WHERE venue_id = ?', (venue_id,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return {'success': True, 'deleted': deleted}
    
    @staticmethod
    def get_length(venue_id):
        """Kuyruk uzunluğunu döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM venue_queues WHERE venue_id = ?', (venue_id,))
        result = cursor.fetchone()
        conn.close()
        return result['count'] if result else 0


class VenueSettings:
    """Venue Ayarları modeli"""
    
    DEFAULT_SETTINGS = {
        'max_queue_length': 20,
        'filter_mode_track': 'blacklist',
        'filter_mode_artist': 'blacklist', 
        'filter_mode_genre': 'blacklist',
        'blacklisted_tracks': [],
        'whitelisted_tracks': [],
        'blacklisted_artists': [],
        'whitelisted_artists': [],
        'blacklisted_genres': [],
        'whitelisted_genres': [],
        'cooldown_seconds': 300,
        'max_user_requests_per_hour': 5
    }
    
    @staticmethod
    def get_settings(venue_id):
        """Venue ayarlarını döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT settings_json FROM venue_settings WHERE venue_id = ?', (venue_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row['settings_json']:
            try:
                settings = json.loads(row['settings_json'])
                # Eksik ayarları varsayılanlarla doldur
                for key, default_value in VenueSettings.DEFAULT_SETTINGS.items():
                    if key not in settings:
                        settings[key] = default_value
                return settings
            except:
                pass
        
        return VenueSettings.DEFAULT_SETTINGS.copy()
    
    @staticmethod
    def save_settings(venue_id, settings):
        """Venue ayarlarını kaydeder"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        settings_json = json.dumps(settings, ensure_ascii=False)
        now = datetime.now().isoformat()
        
        try:
            cursor.execute('''
                INSERT INTO venue_settings (venue_id, settings_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(venue_id) DO UPDATE SET 
                settings_json = excluded.settings_json,
                updated_at = excluded.updated_at
            ''', (venue_id, settings_json, now))
            conn.commit()
            conn.close()
            return {'success': True}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}


class SongRequestAnalytics:
    """Şarkı istek istatistikleri için analytics sınıfı"""
    
    @staticmethod
    def log_request(venue_id, track_uri, track_name, artist_name, requester_ip):
        """Yeni bir şarkı isteği kaydeder"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO song_requests (venue_id, track_uri, track_name, artist_name, requester_ip)
                VALUES (?, ?, ?, ?, ?)
            ''', (venue_id, track_uri, track_name, artist_name, requester_ip))
            conn.commit()
            conn.close()
            return {'success': True}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def mark_as_played(venue_id, track_uri):
        """Şarkıyı çalındı olarak işaretler"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE song_requests 
                SET status = 'played', played_at = CURRENT_TIMESTAMP
                WHERE venue_id = ? AND track_uri = ? AND status = 'added'
                ORDER BY created_at DESC LIMIT 1
            ''', (venue_id, track_uri))
            conn.commit()
            conn.close()
            return {'success': True}
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_top_tracks(venue_id, limit=10, days=30):
        """En çok istenen şarkıları döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT track_uri, track_name, artist_name, COUNT(*) as request_count
                FROM song_requests 
                WHERE venue_id = ? 
                  AND created_at >= datetime('now', ?)
                GROUP BY track_uri
                ORDER BY request_count DESC
                LIMIT ?
            ''', (venue_id, f'-{days} days', limit))
            rows = cursor.fetchall()
            conn.close()
            return [{
                'track_uri': row['track_uri'],
                'track_name': row['track_name'],
                'artist_name': row['artist_name'],
                'request_count': row['request_count']
            } for row in rows]
        except Exception as e:
            conn.close()
            return []
    
    @staticmethod
    def get_hourly_stats(venue_id, days=7):
        """Saat bazlı istek istatistiklerini döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT strftime('%H', created_at) as hour, COUNT(*) as count
                FROM song_requests 
                WHERE venue_id = ? 
                  AND created_at >= datetime('now', ?)
                GROUP BY hour
                ORDER BY hour
            ''', (venue_id, f'-{days} days'))
            rows = cursor.fetchall()
            conn.close()
            return [{
                'hour': int(row['hour']),
                'count': row['count']
            } for row in rows]
        except Exception as e:
            conn.close()
            return []
    
    @staticmethod
    def get_daily_stats(venue_id, days=30):
        """Günlük istek istatistiklerini döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT date(created_at) as date, COUNT(*) as count
                FROM song_requests 
                WHERE venue_id = ? 
                  AND created_at >= datetime('now', ?)
                GROUP BY date
                ORDER BY date
            ''', (venue_id, f'-{days} days'))
            rows = cursor.fetchall()
            conn.close()
            return [{
                'date': row['date'],
                'count': row['count']
            } for row in rows]
        except Exception as e:
            conn.close()
            return []
    
    @staticmethod
    def get_summary(venue_id):
        """Genel özet istatistikleri döndürür"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Toplam istek
            cursor.execute('SELECT COUNT(*) as total FROM song_requests WHERE venue_id = ?', (venue_id,))
            total = cursor.fetchone()['total']
            
            # Bugün
            cursor.execute('''
                SELECT COUNT(*) as today FROM song_requests 
                WHERE venue_id = ? AND date(created_at) = date('now')
            ''', (venue_id,))
            today = cursor.fetchone()['today']
            
            # Bu hafta
            cursor.execute('''
                SELECT COUNT(*) as week FROM song_requests 
                WHERE venue_id = ? AND created_at >= datetime('now', '-7 days')
            ''', (venue_id,))
            week = cursor.fetchone()['week']
            
            # Benzersiz şarkı sayısı
            cursor.execute('''
                SELECT COUNT(DISTINCT track_uri) as unique_tracks FROM song_requests 
                WHERE venue_id = ?
            ''', (venue_id,))
            unique_tracks = cursor.fetchone()['unique_tracks']
            
            conn.close()
            return {
                'total_requests': total,
                'today_requests': today,
                'week_requests': week,
                'unique_tracks': unique_tracks
            }
        except Exception as e:
            conn.close()
            return {'total_requests': 0, 'today_requests': 0, 'week_requests': 0, 'unique_tracks': 0}


# Veritabanını başlat
if __name__ == '__main__':
    init_db()
    print("Veritabanı hazır!")

