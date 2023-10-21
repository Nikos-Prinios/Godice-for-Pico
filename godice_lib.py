# godice_lib.py

import bluetooth
import time
from ble_advertising import decode_services, decode_name
from micropython import const
import re

# ... [Constants and Utilities] ...

_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_NOTIFY = const(0x12)

_UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_RX_CHAR_UUID = bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX_CHAR_UUID = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")

d6_vectors = {
    "1": [-64, 0, 0],
    "2": [0, 0, 64],
    "3": [0, 64, 0],
    "4": [0, -64, 0],
    "5": [0, 0, -64],
    "6": [64, 0, 0]
}

# ... [Classes] ...

class GoDiceCentral:
    
    def __init__(self, ble, dice_callback=None, battery_callback=None):
        self._dice_callback = dice_callback
        self._battery_callback = battery_callback
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)
        self._reset()

    def _reset(self):
        self._conn_handle = None
        self._uart_tx_value_handle = None

    def _log(self, message):
        print("Log:", message)

    def send_command(self, command, response=True):
        if self._conn_handle is not None and self._uart_rx_value_handle is not None:
            try:
                self._ble.gattc_write(self._conn_handle, self._uart_rx_value_handle, command, 1 if response else 0)
                time.sleep(0.5)
            except Exception as e:
                print(f"Error while writing: {e}")

    def _irq(self, event, data):
        #print(f"Received event {event}, data: {data}")

        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            device_name = decode_name(adv_data) or "?"
            if "godice" in device_name.lower():
                self._addr_type = addr_type
                self._addr = bytes(addr)
                self._ble.gap_scan(None)

        elif event == _IRQ_SCAN_DONE:
            if hasattr(self, '_addr'):
                self.connect(self._addr_type, self._addr)

        elif event == _IRQ_PERIPHERAL_CONNECT:
            conn_handle, addr_type, addr = data
            self._conn_handle = conn_handle
            self._ble.gattc_discover_services(self._conn_handle)

        elif event == _IRQ_GATTC_SERVICE_RESULT:
            conn_handle, start_handle, end_handle, uuid = data
            if uuid == _UART_SERVICE_UUID:
                self._start_handle = start_handle
                self._end_handle = end_handle

        elif event == _IRQ_GATTC_SERVICE_DONE:
            conn_handle, status = data
            if status == 0:
                self._ble.gattc_discover_characteristics(self._conn_handle, self._start_handle, self._end_handle)

        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            conn_handle, def_handle, value_handle, properties, uuid = data
            if uuid == _UART_TX_CHAR_UUID and (properties & bluetooth.FLAG_NOTIFY):
                self._uart_tx_value_handle = value_handle
                # Enabling notifications by writing to CCCD
                self._ble.gattc_write(self._conn_handle, value_handle + 1, bytearray([0x01, 0x00]))
            elif uuid == _UART_RX_CHAR_UUID and (properties & bluetooth.FLAG_WRITE):
                self._uart_rx_value_handle = value_handle  # Save this handle for future writes


        elif event == _IRQ_GATTC_NOTIFY:
            conn_handle, value_handle, notify_data = data
            if conn_handle == self._conn_handle and value_handle == self._uart_tx_value_handle:
                #print("Received raw data from UART TX:", notify_data)
                handle_received_data(self, notify_data)
        
        else:
            #print(f"Unhandled event: {event}, Data: {data}")
            pass

    def scan(self):
        self._ble.gap_scan(2000, 30000, 30000)

    def connect(self, addr_type, addr):
        self._ble.gap_connect(addr_type, addr)

# ... [Fonctions] ...

def get_xyz_from_bytes(data, start_byte):
    x = int.from_bytes(data[start_byte:start_byte+1], 'big') if data[start_byte] < 128 else int.from_bytes(data[start_byte:start_byte+1], 'big') - 256
    y = int.from_bytes(data[start_byte+1:start_byte+2], 'big') if data[start_byte+1] < 128 else int.from_bytes(data[start_byte+1:start_byte+2], 'big') - 256
    z = int.from_bytes(data[start_byte+2:start_byte+3], 'big') if data[start_byte+2] < 128 else int.from_bytes(data[start_byte+2:start_byte+3], 'big') - 256
    return [x, y, z]

def get_stable_die_value(data, index):
    return data[index]

def battery_level_from_char(char):
    # Define bounds
    low_bound = ord('N')
    high_bound = ord('^')
    
    # Convert char to ASCII
    value = ord(char)
    
    # If outside known bounds, return error
    if value < low_bound or value > high_bound:
        return -1
    
    # Calculate the approximate battery percentage
    percentage = int((value - low_bound) * (100 / (high_bound - low_bound)))
    
    return percentage

def handle_received_data(central, raw_data):
    #print("Received raw data:", bytes(raw_data))
    first_byte = raw_data[0]

    if first_byte == ord('S'):
        xyz_array = get_xyz_from_bytes(raw_data, 1)
        x, y, z = xyz_array
        #print(f"XYZ extracted: X = {x}, Y = {y}, Z = {z}")

        dice_result = get_closest_vector(d6_vectors, xyz_array)  # Ensure this gets a value

        if central._dice_callback and dice_result is not None:   # Check if dice_result is not None before calling the callback
            central._dice_callback(dice_result)

        #print(f"The dice shows: {dice_result}")

        request_battery_level(central)
        #toggle_light(central)

    elif first_byte == ord('B'):
        if raw_data[3] == 0x00:
            battery_level = 0
        else:
            battery_char = chr(raw_data[3])
            battery_level = battery_level_from_char(battery_char)
        #print(f"Battery Level: {battery_level}%")
        if central._battery_callback:
            central._battery_callback(battery_level)


def get_closest_vector(die_table, coord):
    coord_x = coord[0]
    coord_y = coord[1]
    coord_z = coord[2]

    min_distance = float('inf')
    value = 0

    for die_value, vector in die_table.items():
        x_result = coord_x - vector[0]
        y_result = coord_y - vector[1]
        z_result = coord_z - vector[2]

        cur_dist = (x_result ** 2) + (y_result ** 2) + (z_result ** 2)

        if cur_dist < min_distance:
            min_distance = cur_dist
            value = die_value

    return int(value)

def request_battery_level(central):
    message_identifier = bytes([3])
    #print(f"Sending Battery Request: {message_identifier}")
    central.send_command(message_identifier, response=True) 
    

def toggle_light(central):
    message_identifier = bytes([8])  # Adjust the message identifier as needed
    #print(f"Sending Light toggle Request: {message_identifier}")
    central.send_command(message_identifier)
    
# ... [Demo] ...

def demo():
    """Demonstration function for using the GoDiceCentral library."""
    ble = bluetooth.BLE()
    central = GoDiceCentral(ble)
    central.scan()
    time.sleep(10)
    while True:
        pass
    
# ... [Usage] ...

#from godice_lib import GoDiceCentral, demo

#ble = bluetooth.BLE()
#dice = GoDiceCentral(ble)
#dice.scan()

# OR simply call the demo function
# demo()