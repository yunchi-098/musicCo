#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import pulsectl
import sys
import os
import time
import dbus
from dbus.mainloop.glib import DBusGMainLoop
import json  # For JSON output
import argparse  # For command-line arguments
import logging  # For logging

# Logging settings
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('ex_script')


# --- BluetoothManager Class (DBus Usage - Error Handling Added) ---
class BluetoothManager:
    def __init__(self):
        self.bus = None
        self.adapter = None
        self.adapter_props = None
        try:
            self.bus = dbus.SystemBus()
            # Try to find the default adapter (usually hci0)
            adapter_path = '/org/bluez/hci0'
            self.adapter_obj = self.bus.get_object('org.bluez', adapter_path)
            self.adapter = dbus.Interface(self.adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(self.adapter_obj, 'org.freedesktop.DBus.Properties')
            logger.info("BluetoothManager initialized successfully.")
        except dbus.exceptions.DBusException as e:
            logger.error(
                f"DBus initialization error: {e}. Is the Bluetooth service running or is the adapter path correct?")
            self.bus = None
            self.adapter = None
            self.adapter_props = None
        except Exception as e:
            logger.error(f"Unexpected error while initializing BluetoothManager: {e}", exc_info=True)
            self.bus = None
            self.adapter = None
            self.adapter_props = None

    def _get_managed_objects(self):
        """Gets Bluez objects."""
        if not self.bus:
            logger.error("No DBus connection.")
            return {}
        try:
            om = dbus.Interface(self.bus.get_object('org.bluez', '/'),
                                'org.freedesktop.DBus.ObjectManager')
            return om.GetManagedObjects()
        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error while getting Bluez objects: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error while getting Bluez objects: {e}", exc_info=True)
            return {}

    def list_devices(self, discovery_duration=5):
        """Discovers and lists Bluetooth devices."""
        if not self.adapter or not self.adapter_props:
            logger.error("Bluetooth adapter not initialized properly.")
            return {'success': False,
                    'error': 'Bluetooth adapter not found or could not be initialized.',
                    'devices': []}

        devices = []
        try:
            # Start discovery
            logger.info(f"Scanning for Bluetooth devices for {discovery_duration} seconds...")
            try:
                self.adapter.StartDiscovery(timeout=dbus.UInt32(discovery_duration + 1, variant_level=1))
                time.sleep(discovery_duration)
            except dbus.exceptions.DBusException as e:
                if "Already discovering" not in str(e):
                    logger.warning(f"Could not start discovery (maybe already active?): {e}")
            finally:
                # Try to stop discovery
                try:
                    if self.adapter_props.Get('org.bluez.Adapter1', 'Discovering'):
                        self.adapter.StopDiscovery()
                        logger.info("Device discovery stopped.")
                except dbus.exceptions.DBusException as e:
                    logger.warning(f"Error while stopping discovery: {e}")

            logger.info("Getting device list...")
            objects = self._get_managed_objects()
            if not objects:
                return {'success': False, 'error': 'Could not get Bluez objects.', 'devices': []}

            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    device_props = interfaces['org.bluez.Device1']
                    # Get basic information
                    name = str(
                        device_props.get('Name', device_props.get('Alias', 'Unknown Device')))
                    address = str(device_props.get('Address', 'No Address'))
                    connected = bool(device_props.get('Connected', False))
                    paired = bool(device_props.get('Paired', False))
                    # Check for audio profile support
                    uuids = device_props.get('UUIDs', [])
                    is_audio_device = any(
                        'a2dp' in str(uuid).lower() or 'hfp' in str(uuid).lower() or 'avrcp' in str(
                            uuid).lower() for uuid in uuids)

                    device_info = {
                        'path': str(path),
                        'name': name,
                        'mac_address': address,
                        'connected': connected,
                        'paired': paired,
                        'is_audio': is_audio_device,
                        'type': 'bluetooth'
                    }
                    devices.append(device_info)

            logger.info(f"{len(devices)} Bluetooth devices found/listed.")
            return {'success': True, 'devices': devices}

        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error while listing devices: {e}")
            return {'success': False, 'error': f'DBus error: {e}', 'devices': []}
        except Exception as e:
            logger.error(f"Error while listing devices: {e}", exc_info=True)
            return {'success': False, 'error': f'Unexpected error: {e}', 'devices': []}
        finally:
            # Try to stop discovery again just in case
            try:
                if self.adapter and self.adapter_props and self.adapter_props.Get('org.bluez.Adapter1',
                                                                                   'Discovering'):
                    self.adapter.StopDiscovery()
            except:
                pass

    def _get_device_interface(self, device_path):
        """Gets the device interface at the given path."""
        if not self.bus: return None
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            return dbus.Interface(device_obj, 'org.bluez.Device1')
        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error while getting device interface ({device_path}): {e}")
            return None
        except Exception as e:
            logger.error(f"Error while getting device interface ({device_path}): {e}",
                         exc_info=True)
            return None

    def connect_device(self, device_path):
        """Connects to the device at the given DBus path."""
        if not self.adapter:
            return {'success': False, 'error': 'Bluetooth adapter not found.'}

        device_interface = self._get_device_interface(device_path)
        if not device_interface:
            return {'success': False,
                    'error': f'Could not get device interface ({device_path}).'}

        try:
            props_iface = dbus.Interface(device_interface, 'org.freedesktop.DBus.Properties')
            device_name = str(props_iface.Get('org.bluez.Device1', 'Name'))
            is_connected = bool(props_iface.Get('org.bluez.Device1', 'Connected'))
            is_paired = bool(props_iface.Get('org.bluez.Device1', 'Paired'))

            if is_connected:
                logger.info(f"'{device_name}' is already connected.")
                return {'success': True, 'message': f"'{device_name}' is already connected."}

            if not is_paired:
                logger.info(f"'{device_name}' is not paired, pairing...")
                try:
                    # Mark as trusted before pairing
                    try:
                        props_iface.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
                        logger.info(f"'{device_name}' marked as trusted.")
                    except Exception as trust_err:
                        logger.warning(f"Could not mark '{device_name}' as trusted: {trust_err}")

                    # Pairing process
                    device_interface.Pair(timeout=dbus.UInt32(20, variant_level=1))
                    logger.info(f"'{device_name}' paired successfully.")

                    # Mark as trusted again after pairing
                    try:
                        props_iface.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
                        logger.info(f"'{device_name}' marked as trusted.")
                    except Exception as trust_err:
                        logger.warning(f"Could not mark '{device_name}' as trusted: {trust_err}")

                except dbus.exceptions.DBusException as e:
                    logger.error(f"Could not pair '{device_name}': {e}")

            logger.info(f"Connecting to '{device_name}' device...")
            device_interface.Connect(timeout=dbus.UInt32(30, variant_level=1))
            time.sleep(3)
            if bool(props_iface.Get('org.bluez.Device1', 'Connected')):
                logger.info(f"Successfully connected to '{device_name}' device.")
                return {'success': True,
                        'message': f"Successfully connected to '{device_name}' device."}
            else:
                logger.error(
                    f"Could not connect to '{device_name}' device (timeout or other issue).")
                return {'success': False,
                        'error': f"Could not connect to '{device_name}' device."}

        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error while connecting to device ({device_path}): {e}")
            error_str = str(e).lower()
            if "already connected" in error_str:
                logger.info(f"'{device_name}' is already connected (DBus error).")
                return {'success': True, 'message': f"'{device_name}' is already connected."}
            elif "connection attempt failed" in error_str or "failed" in error_str:
                return {'success': False, 'error': f"Connection attempt failed: {e}"}
            else:
                return {'success': False, 'error': f"DBus error: {e}"}
        except Exception as e:
            logger.error(f"Error while connecting to device ({device_path}): {e}",
                         exc_info=True)
            return {'success': False, 'error': f"Unexpected error: {e}"}

    def disconnect_device(self, device_path):
        """Disconnects the device at the given DBus path."""
        if not self.adapter:
            return {'success': False, 'error': 'Bluetooth adapter not found.'}

        device_interface = self._get_device_interface(device_path)
        if not device_interface:
            return {'success': False,
                    'error': f'Could not get device interface ({device_path}).'}

        try:
            props_iface = dbus.Interface(device_interface, 'org.freedesktop.DBus.Properties')
            device_name = str(props_iface.Get('org.bluez.Device1', 'Name'))
            is_connected = bool(props_iface.Get('org.bluez.Device1', 'Connected'))

            if not is_connected:
                logger.info(f"'{device_name}' is not connected.")
                return {'success': True, 'message': f"'{device_name}' is not connected."}

            logger.info(f"Disconnecting from '{device_name}' device...")
            device_interface.Disconnect(timeout=dbus.UInt32(10, variant_level=1))
            time.sleep(1)
            logger.info(f"'{device_name}' disconnected.")
            return {'success': True, 'message': f"'{device_name}' disconnected."}

        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error while disconnecting ({device_path}): {e}")
            error_str = str(e).lower()
            if "not connected" in error_str:
                logger.info(f"'{device_name}' is not connected (DBus error).")
                return {'success': True, 'message': f"'{device_name}' is not connected."}
            else:
                return {'success': False, 'error': f"DBus error: {e}"}
        except Exception as e:
            logger.error(f"Error while disconnecting ({device_path}): {e}", exc_info=True)
            return {'success': False, 'error': f"Unexpected error: {e}"}


# --- AudioSinkManager Class (Pulsectl Usage) ---
class AudioSinkManager:
    def __init__(self, app_name='ex_script_audio'):
        self.app_name = app_name

    def list_sinks(self):
        """Lists all available audio output devices (sinks)."""
        sinks_info = []
        default_sink_name = None
        try:
            with pulsectl.Pulse(self.app_name + '-list') as pulse:
                raw_sinks = pulse.sink_list()
                server_info = pulse.server_info()
                default_sink_name = server_info.default_sink_name

                if not raw_sinks:
                    logger.info("No audio output devices (sinks) found.")
                    return {'success': True, 'sinks': [], 'default_sink_name': None}

                for sink in raw_sinks:
                    is_default = sink.name == default_sink_name
                    sinks_info.append({
                        'index': sink.index,
                        'name': sink.name,
                        'description': sink.description,
                        'state': str(sink.state),
                        'mute': sink.mute,
                        'volume': round(sink.volume.value_flat * 100),
                        'is_default': is_default,
                    })
                logger.info(
                    f"{len(sinks_info)} sinks listed. Default: {default_sink_name}")
                return {'success': True, 'sinks': sinks_info,
                        'default_sink_name': default_sink_name}

        except pulsectl.PulseError as e:
            logger.error(f"PulseAudio/PipeWire connection error (list_sinks): {e}")
            return {'success': False, 'error': f"Audio server error: {e}", 'sinks': [],
                    'default_sink_name': None}
        except Exception as e:
            logger.error(f"General error while listing audio devices: {e}", exc_info=True)
            return {'success': False, 'error': f"Unknown error: {e}", 'sinks': [],
                    'default_sink_name': None}

    def switch_to_sink(self, sink_identifier):
        """Switches to the specified sink (by index or name/description)."""
        target_sink = None
        try:
            with pulsectl.Pulse(self.app_name + '-switch') as pulse:
                sinks = pulse.sink_list()
                if not sinks:
                    logger.error("Cannot switch sink, no sinks found.")
                    return {'success': False, 'error': "No audio output devices found."}

                # Find the target sink
                if isinstance(sink_identifier, int) or sink_identifier.isdigit():
                    try:
                        sink_index = int(sink_identifier)
                        target_sink = pulse.sink_info(sink_index)
                        if not target_sink: raise ValueError("Sink not found by index")
                    except (ValueError, pulsectl.PulseError) as e:
                        logger.error(
                            f"Invalid or non-existent sink index: {sink_identifier} - Error: {e}")
                        return {'success': False,
                                'error': f"Invalid or non-existent sink index: {sink_identifier}"}
                else:
                    # Search by name or description (case-insensitive)
                    search_term = str(sink_identifier).lower()
                    found = False
                    for s in sinks:
                        if search_term in s.name.lower() or search_term in s.description.lower():
                            target_sink = s
                            found = True
                            break
                    if not found:
                        logger.error(
                            f"Sink with name/description '{sink_identifier}' not found!")
                        return {'success': False,
                                'error': f"Sink with name/description '{sink_identifier}' not found!"}

                if not target_sink:
                    logger.error(f"Target sink could not be determined: {sink_identifier}")
                    return {'success': False,
                            'error': f"Target sink could not be determined: {sink_identifier}"}

                logger.info(
                    f"Setting default sink to '{target_sink.description}' (Index: {target_sink.index})...")
                pulse.default_set(target_sink)
                logger.info(
                    f"Default audio output successfully set to '{target_sink.description}'.")
                return {'success': True,
                        'message': f"Default audio output set to '{target_sink.description}'."}

        except pulsectl.PulseError as e:
            logger.error(f"PulseAudio/PipeWire connection error (switch_to_sink): {e}")
            return {'success': False, 'error': f"Could not connect to audio server: {e}"}
        except Exception as e:
            logger.error(f"General error while switching sink: {e}", exc_info=True)
            return {'success': False, 'error': f"Error while switching sink: {e}"}

    def find_sink_by_device_name(self, device_name):
        """Finds the corresponding sink by device name and returns its information."""
        try:
            with pulsectl.Pulse(self.app_name + '-find') as pulse:
                sinks = pulse.sink_list()
                if not sinks: return {'success': True, 'found': False,
                                      'sink': None}

                search_term = device_name.lower()
                bluez_search_term = f"bluez_sink.{device_name.replace(':', '_').lower()}"

                for sink in sinks:
                    name_lower = sink.name.lower()
                    desc_lower = sink.description.lower()
                    if search_term in name_lower or search_term in desc_lower or bluez_search_term in name_lower:
                        logger.info(
                            f"Matching sink found for '{device_name}': {sink.description}")
                        sink_info = {
                            'index': sink.index,
                            'name': sink.name,
                            'description': sink.description,
                            'state': str(sink.state),
                            'is_default': sink.name == pulse.server_info().default_sink_name
                        }
                        return {'success': True, 'found': True, 'sink': sink_info}

                logger.warning(f"No matching sink found for '{device_name}'.")
                return {'success': True, 'found': False, 'sink': None}
        except pulsectl.PulseError as e:
            logger.error(f"PulseAudio/PipeWire connection error (find_sink): {e}")
            return {'success': False, 'error': f"Audio server error: {e}", 'found': False,
                    'sink': None}
        except Exception as e:
            logger.error(f"General error while searching for sink for device: {e}",
                         exc_info=True)
            return {'success': False, 'error': f"Unknown error: {e}", 'found': False,
                    'sink': None}


# --- Spotifyd Functions ---
def get_spotifyd_pid():
    """Finds the PID of running spotifyd processes."""
    try:
        output = subprocess.check_output(["pgrep", "spotifyd"], text=True)
        pids = output.strip().split("\n")
        return {'success': True, 'pids': pids}
    except subprocess.CalledProcessError:
        return {'success': True, 'pids': []}
    except FileNotFoundError:
        return {'success': False, 'error': "'pgrep' command not found."}
    except Exception as e:
        return {'success': False, 'error': f"Error while getting PID: {e}"}


def restart_spotifyd():
    """Restarts the spotifyd service."""
    logger.info("Restarting spotifyd...")
    pid_result = get_spotifyd_pid()
    if not pid_result['success']:
        return pid_result

    pids = pid_result['pids']
    killed_pids = []
    messages = []
    start_success = False

    # Terminate existing processes
    if pids:
        for pid in pids:
            try:
                os.kill(int(pid), 15)
                killed_pids.append(pid)
                messages.append(f"PID {pid} terminated.")
                time.sleep(0.5)
            except ValueError:
                messages.append(f"Invalid PID skipped: {pid}")
            except ProcessLookupError:
                messages.append(f"PID {pid} already terminated.")
            except Exception as e:
                messages.append(f"Could not terminate PID {pid}: {e}")
    else:
        messages.append("No running Spotifyd process found.")

    # Start a new process
    spotifyd_command = ["spotifyd", "--no-daemon"]
    config_home = os.path.expanduser("~/.config/spotifyd/spotifyd.conf")
    config_etc = "/etc/spotifyd.conf"
    if os.path.exists(config_home):
        spotifyd_command = ["spotifyd", "--config-path", config_home, "--no-daemon"]
        logger.info(f"Using spotifyd config: {config_home}")
    elif os.path.exists(config_etc):
        spotifyd_command = ["spotifyd", "--config-path", config_etc, "--no-daemon"]
        logger.info(f"Using spotifyd config: {config_etc}")

    try:
        subprocess.Popen(spotifyd_command)
        time.sleep(2)
        new_pid_result = get_spotifyd_pid()
        if new_pid_result['success'] and new_pid_result['pids'] and any(
                pid not in killed_pids for pid in new_pid_result['pids']):
            messages.append("Spotifyd restarted successfully.")
            start_success = True
        else:
            messages.append(
                "Spotifyd terminated but could not be restarted or new process not found.")
            start_success = False
    except FileNotFoundError:
        messages.append("Error: 'spotifyd' command not found. Is it installed?")
        start_success = False
    except Exception as e:
        messages.append(f"Error while starting spotifyd: {e}")
        start_success = False

    return {'success': start_success, 'message': " ".join(messages)}


# --- ALSA Switch Function ---
def switch_alsa():
    """Switches to an ALSA-compatible sink."""
    audio_manager = AudioSinkManager()
    list_result = audio_manager.list_sinks()
    if not list_result['success']:
        return list_result

    sinks = list_result['sinks']
    if not sinks:
        return {'success': False, 'error': "No audio output devices found."}

    alsa_sinks = []
    for sink in sinks:
        name_lower = sink.get('name', '').lower()
        desc_lower = sink.get('description', '').lower()
        if ("alsa" in name_lower or "analog" in name_lower or "builtin" in desc_lower) and "bluez" not in name_lower:
            alsa_sinks.append(sink)

    if not alsa_sinks:
        return {'success': False, 'error': "No suitable ALSA audio output device found."}

    target_sink = None
    for sink in alsa_sinks:
        if not sink.get('is_default'):
            target_sink = sink
            break
    if not target_sink:
        target_sink = alsa_sinks[0]

    if target_sink.get('is_default'):
        return {'success': True,
                'message': f"ALSA audio output ('{target_sink.get('description')}') is already the default."}

    switch_result = audio_manager.switch_to_sink(target_sink.get('index'))
    if switch_result['success']:
        switch_result[
            'message'] = f"Switched to ALSA audio output: {switch_result['message']}"
    else:
        switch_result[
            'error'] = f"Could not switch to ALSA audio output: {switch_result.get('error', 'Unknown error')}"

    return switch_result


# --- Main Execution Block ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audio and Bluetooth Management Script")
    parser.add_argument('command', help="Command to execute", choices=[
        'list_sinks', 'discover_bluetooth', 'pair_bluetooth',
        'disconnect_bluetooth', 'switch_to_alsa', 'set_audio_sink',
        'restart_spotifyd'
    ])
    parser.add_argument('--identifier',
                        help="Sink index or name/description for set_audio_sink")
    parser.add_argument('--path',
                        help="Device DBus path for pair_bluetooth and disconnect_bluetooth")
    parser.add_argument('--duration', type=int, default=5,
                        help="Scan duration for discover_bluetooth (seconds)")

    args = parser.parse_args()

    result = {'success': False, 'error': 'Invalid command or argument'}

    if args.command == 'list_sinks':
        manager = AudioSinkManager()
        result = manager.list_sinks()
    elif args.command == 'discover_bluetooth':
        manager = BluetoothManager()
        result = manager.list_devices(discovery_duration=args.duration)
    elif args.command == 'pair_bluetooth':
        if args.path:
            manager = BluetoothManager()
            result = manager.connect_device(args.path)
        else:
            result = {'success': False, 'error': '--path argument is required'}
    elif args.command == 'disconnect_bluetooth':
        if args.path:
            manager = BluetoothManager()
            result = manager.disconnect_device(args.path)
        else:
            result = {'success': False, 'error': '--path argument is required'}
    elif args.command == 'switch_to_alsa':
        result = switch_alsa()
    elif args.command == 'set_audio_sink':
        if args.identifier:
            manager = AudioSinkManager()
            result = manager.switch_to_sink(args.identifier)
        else:
            result = {'success': False, 'error': '--identifier argument is required'}
    elif args.command == 'restart_spotifyd':
        result = restart_spotifyd()

    print(json.dumps(result, indent=2))
