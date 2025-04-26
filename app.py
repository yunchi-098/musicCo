#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import subprocess
import threading
import pulsectl
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash

# --- Bluetooth ve Sink Yöneticileri ---

class BluetoothManager:
    def __init__(self):
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.adapter_obj = self.bus.get_object('org.bluez', '/org/bluez/hci0')
        self.adapter = dbus.Interface(self.adapter_obj, 'org.bluez.Adapter1')
        self.adapter_props = dbus.Interface(self.adapter_obj, 'org.freedesktop.DBus.Properties')
        self.device_list = []

    def start_discovery(self):
        try:
            self.adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
            if not self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                self.adapter.StartDiscovery()
            time.sleep(5)
            return self.list_devices()
        except Exception as e:
            return []

    def stop_discovery(self):
        try:
            if self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                self.adapter.StopDiscovery()
        except Exception as e:
            pass

    def list_devices(self):
        devices = []
        try:
            om = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = om.GetManagedObjects()
            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    device_props = interfaces['org.bluez.Device1']
                    if 'Name' in device_props and 'Address' in device_props:
                        devices.append({
                            'path': path,
                            'name': device_props['Name'],
                            'address': device_props['Address'],
                            'connected': device_props.get('Connected', False),
                            'paired': device_props.get('Paired', False),
                        })
            self.device_list = devices
            return devices
        except Exception as e:
            return []

    def connect_device(self, device_address):
        try:
            for device in self.device_list:
                if device['address'] == device_address:
                    device_obj = self.bus.get_object('org.bluez', device['path'])
                    device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
                    if not device['paired']:
                        device_interface.Pair()
                    device_interface.Connect()
                    time.sleep(3)
                    return True
            return False
        except Exception as e:
            return False

    def disconnect_device(self, device_address):
        try:
            for device in self.device_list:
                if device['address'] == device_address:
                    device_obj = self.bus.get_object('org.bluez', device['path'])
                    device_interface = dbus.Interface(device_obj, 'org.bluez.Device1')
                    device_interface.Disconnect()
                    return True
            return False
        except Exception as e:
            return False

class AudioSinkManager:
    def list_sinks(self):
        try:
            with pulsectl.Pulse('list-sinks') as pulse:
                return [{'index': s.index, 'name': s.name, 'description': s.description} for s in pulse.sink_list()]
        except Exception as e:
            return []

    def switch_to_sink(self, sink_index):
        try:
            with pulsectl.Pulse('switch-sink') as pulse:
                sink = next((s for s in pulse.sink_list() if s.index == sink_index), None)
                if sink:
                    for stream in pulse.sink_input_list():
                        pulse.sink_input_move(stream.index, sink.index)
                    pulse.default_set(sink)
                    return True
            return False
        except Exception as e:
            return False

def restart_spotifyd():
    try:
        subprocess.call(['pkill', 'spotifyd'])
        time.sleep(2)
        subprocess.Popen(['spotifyd'])
        return True
    except Exception as e:
        return False

# --- Flask Uygulaması ---

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'guvensiz_anahtar_degistir')

bt_manager = BluetoothManager()
sink_manager = AudioSinkManager()

# --- Admin Giriş Koruması ---

def admin_login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Admin girişi yapmalısınız.', 'warning')
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Web Sayfaları ---

@app.route('/')
def index():
    return redirect(url_for('admin'))

@app.route('/admin')
def admin():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'mekan123')
    if request.form.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return redirect(url_for('admin_panel'))
    else:
        flash('Şifre yanlış!', 'danger')
        return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Çıkış yapıldı.', 'info')
    return redirect(url_for('admin'))

@app.route('/admin-panel')
@admin_login_required
def admin_panel():
    return render_template('admin_panel.html')

# --- API Rotaları ---

@app.route('/api/bluetooth/scan')
@admin_login_required
def bluetooth_scan():
    devices = bt_manager.start_discovery()
    bt_manager.stop_discovery()
    return jsonify({'devices': devices})

@app.route('/api/bluetooth/connect', methods=['POST'])
@admin_login_required
def bluetooth_connect():
    address = request.json.get('address')
    success = bt_manager.connect_device(address)
    return jsonify({'success': success})

@app.route('/api/bluetooth/disconnect', methods=['POST'])
@admin_login_required
def bluetooth_disconnect():
    address = request.json.get('address')
    success = bt_manager.disconnect_device(address)
    return jsonify({'success': success})

@app.route('/api/sink/list')
@admin_login_required
def sink_list():
    sinks = sink_manager.list_sinks()
    return jsonify({'sinks': sinks})

@app.route('/api/sink/switch', methods=['POST'])
@admin_login_required
def sink_switch():
    sink_index = request.json.get('sink_index')
    success = sink_manager.switch_to_sink(sink_index)
    return jsonify({'success': success})

@app.route('/api/spotifyd/restart', methods=['POST'])
@admin_login_required
def spotifyd_restart():
    success = restart_spotifyd()
    return jsonify({'success': success})

# --- Uygulamayı Başlat ---

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
