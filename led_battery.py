#!/usr/bin/env python3
"""
led_battery.py
Battery meter on Tony's 7-LED strip (GPIO D10).

Color scale:
  7 LEDs lit  — white    (100%)
  6 LEDs lit  — green    (85%)
  5 LEDs lit  — green    (70%)
  4 LEDs lit  — yellow   (55%)
  3 LEDs lit  — yellow   (40%)
  2 LEDs lit  — orange   (25%)
  1 LED  lit  — red      (10%)
  0 LEDs lit  — all red flashing (critical)

Run standalone:  python3 led_battery.py
Import:          from led_battery import update_leds, clear_leds
"""
import time
import smbus
import board
import neopixel

LED_PIN    = board.D10
LED_COUNT  = 7
BRIGHTNESS = 0.22

ADC_BUS    = 1
ADC_ADDR   = 0x48
ADC_COEFF  = 3

# Color definitions (R, G, B)
WHITE  = (180, 180, 180)
GREEN  = (0, 200, 0)
YELLOW = (180, 140, 0)
ORANGE = (200, 60, 0)
RED    = (200, 0, 0)
OFF    = (0, 0, 0)

SOC_CURVE = [
    (8.40, 100), (8.20, 95), (8.00, 88), (7.80, 78),
    (7.60, 65),  (7.40, 50), (7.20, 35), (7.00, 20),
    (6.80, 10),  (6.40,  5), (6.00,  0),
]


def read_battery_pct():
    try:
        bus = smbus.SMBus(ADC_BUS)
        ch  = 4
        cmd = 0x84 | ((((ch << 2) | (ch >> 1)) & 0x07) << 4)
        bus.write_byte(ADC_ADDR, cmd)
        time.sleep(0.01)
        v1  = bus.read_byte(ADC_ADDR)
        v2  = bus.read_byte(ADC_ADDR)
        raw = v1 if v1 == v2 else (v1 + v2) // 2
        voltage = round(raw / 255.0 * 5 * ADC_COEFF, 2)

        for i, (vt, pct) in enumerate(SOC_CURVE):
            if voltage >= vt:
                if i == 0:
                    return 100.0, voltage
                v_hi, p_hi = SOC_CURVE[i - 1]
                v_lo, p_lo = vt, pct
                soc = p_lo + (voltage - v_lo) / (v_hi - v_lo) * (p_hi - p_lo)
                return round(soc, 1), voltage
        return 0.0, voltage
    except Exception:
        return None, None


def pct_to_leds(pct):
    """Return (num_leds_on, color) based on battery percentage."""
    if pct is None:
        return 1, RED
    if pct >= 93: return 7, WHITE
    if pct >= 78: return 6, GREEN
    if pct >= 63: return 5, GREEN
    if pct >= 48: return 4, YELLOW
    if pct >= 33: return 3, YELLOW
    if pct >= 18: return 2, ORANGE
    if pct >   5: return 1, RED
    return 0, RED


def update_leds(pixels, pct):
    num_on, color = pct_to_leds(pct)
    if num_on == 0:
        # Critical — flash all red
        for i in range(LED_COUNT):
            pixels[i] = RED
        pixels.show()
        time.sleep(0.3)
        for i in range(LED_COUNT):
            pixels[i] = OFF
        pixels.show()
        return

    for i in range(LED_COUNT):
        pixels[i] = color if i < num_on else OFF
    pixels.show()


def clear_leds(pixels):
    pixels.fill(OFF)
    pixels.show()


if __name__ == "__main__":
    pixels = neopixel.NeoPixel(LED_PIN, LED_COUNT, brightness=BRIGHTNESS, auto_write=False)

    print("Tony LED Battery Meter — Ctrl+C to stop\n")
    try:
        while True:
            pct, voltage = read_battery_pct()
            if pct is not None:
                num_on, _ = pct_to_leds(pct)
                print(f"  Battery: {voltage}V  {pct}%  → {num_on}/{LED_COUNT} LEDs")
            else:
                print("  Battery: read error")
            update_leds(pixels, pct)
            time.sleep(10)
    except KeyboardInterrupt:
        clear_leds(pixels)
        print("\nLEDs off.")
