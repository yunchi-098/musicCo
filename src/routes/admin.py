from flask import Blueprint, render_template, redirect, url_for, session, flash
from ..services.spotify_service import spotify_service
from ..services.queue_service import queue_service
from ..utils.auth import admin_login_required, load_settings
from ..utils.formatters import format_track_info

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin')
def admin():
    """Admin giriş sayfasını gösterir."""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin.admin_panel'))
    return render_template('admin.html')

@admin_bp.route('/admin-login', methods=['POST'])
def admin_login():
    """Admin giriş isteğini işler."""
    from ..config import ADMIN_PASSWORD
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        flash("Yönetim paneline hoş geldiniz!", "success")
        return redirect(url_for('admin.admin_panel'))
    else:
        flash("Yanlış şifre girdiniz.", "danger")
        return redirect(url_for('admin.admin'))

@admin_bp.route('/logout')
@admin_login_required
def logout():
    """Admin çıkış işlemini yapar."""
    session.clear()
    flash("Başarıyla çıkış yaptınız.", "info")
    return redirect(url_for('admin.admin'))

@admin_bp.route('/admin-panel')
@admin_login_required
def admin_panel():
    """Admin panelini gösterir."""
    try:
        # Spotify bağlantısını kontrol et
        spotify = spotify_service.get_client()
        spotify_authenticated = bool(spotify)
        
        # Şu an çalan şarkı bilgilerini al
        currently_playing_info = None
        if spotify_authenticated:
            try:
                current = spotify.current_playback()
                if current and current.get('item'):
                    currently_playing_info = format_track_info(current['item'])
                    currently_playing_info['is_playing'] = current.get('is_playing', False)
            except Exception as e:
                logger.error(f"Şu an çalan şarkı bilgileri alınırken hata: {str(e)}")

        # Kuyruğu al
        queue = queue_service.get_queue()
        
        # Ayarları yükle
        settings = load_settings()
        
        return render_template('admin_panel.html',
                             spotify_authenticated=spotify_authenticated,
                             currently_playing_info=currently_playing_info,
                             queue=queue,
                             settings=settings)
    except Exception as e:
        logger.error(f"Admin panel yüklenirken hata: {str(e)}")
        flash('Panel yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('admin.admin')) 