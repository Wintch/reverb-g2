"""Shared HP Reverb G2 USB device-ID table.

Used by status-dashboard.py (kiosk USB census) and pmadminka-agent.py (VR
capability self-report, hw.vr_device). Single source of truth so the two
never drift on what "the G2 is plugged in" means.
"""
import subprocess

KNOWN_USB = {
    "04b4:6506": "WMR hub (USB2)",
    "0bda:4c15": "USB Audio",
    "03f0:0580": "QHMD companion (HID control)",
    "04b4:6504": "WMR hub (USB3)",
    "045e:0659": "HoloLens Sensors (cameras)",
}


def lsusb_output():
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        return r.stdout
    except Exception:
        return ""


def all_present(lsusb_text=None):
    """True if all 5 known G2 VID:PIDs are present (the same bar status-dashboard.py uses)."""
    text = lsusb_text if lsusb_text is not None else lsusb_output()
    return all(vidpid in text for vidpid in KNOWN_USB)
