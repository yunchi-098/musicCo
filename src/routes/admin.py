from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template, current_app

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('admin_login.html')
    
    password = request.form.get('password')
    if password == current_app.config['ADMIN_PASSWORD']:
        session['admin'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Geçersiz şifre'})

@admin_bp.route('/admin/panel')
def panel():
    if not session.get('admin'):
        return redirect(url_for('admin.login'))
    return render_template('admin.html')

@admin_bp.route('/admin/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('index')) 