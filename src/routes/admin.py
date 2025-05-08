from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template
from src.config import ADMIN_PASSWORD

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/login', methods=['POST'])
def login():
    password = request.form.get('password')
    if password == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Geçersiz şifre'})

@admin_bp.route('/admin/control')
def control():
    if not session.get('admin'):
        return redirect(url_for('index'))
    return render_template('admin.html') 