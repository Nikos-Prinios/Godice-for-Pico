from godice_lib import GoDiceCentral
import bluetooth
import writer
import freesans20
from machine import Pin, I2C, Timer
from ssd1306 import SSD1306_I2C
import time

current_value = ""
current_level = ""

WIDTH = 128
HEIGHT = 32
i2c = I2C(0, scl=Pin(17), sda=Pin(16), freq=200000)
oled = SSD1306_I2C(WIDTH, HEIGHT, i2c)

def my_dice_callback(received_value):
    print(f"Dice Value Received: {received_value}")
    global current_value
    current_value = received_value

def my_battery_callback(received_level):
    print(f"Battery Level Received: {received_level}%")
    global current_level
    current_level = received_level

def display_value(level, value):
    oled.fill(0)
    font_writer = writer.Writer(oled, freesans20)
    font_writer.set_textpos(5, 0)  
    font_writer.printstring(str(value))
    
    oled.text(f"Bat: {level}%", 55, 25)  
    oled.show()

ble = bluetooth.BLE()
dice = GoDiceCentral(ble, dice_callback=my_dice_callback, battery_callback=my_battery_callback)
dice.scan()

while True:
    display_value(current_level, current_value)
    time.sleep(1)  # Delay for 1 second before updating again
