"""Optional BLE scan: does the buds advertise anything useful over BLE / GATT?"""
from __future__ import annotations

import time


async def ble_scan(seconds: float = 12.0, name_hint: str = "buds") -> dict:
    try:
        from bleak import BleakScanner
    except ImportError:
        return {"error": "bleak not installed (pip install bleak)", "devices": []}
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    devices = []
    for addr, (dev, adv) in found.items():
        devices.append({
            "address": addr, "name": adv.local_name or dev.name, "rssi": adv.rssi,
            "service_uuids": list(adv.service_uuids or []),
            "manufacturer_data": {str(k): v.hex() for k, v in (adv.manufacturer_data or {}).items()},
            "service_data": {k: v.hex() for k, v in (adv.service_data or {}).items()},
            "tx_power": adv.tx_power,
            "match": bool(name_hint and name_hint.lower() in ((adv.local_name or dev.name or "").lower())
                          or 0x0075 in (adv.manufacturer_data or {})),   # 0x0075 = Samsung company id
        })
    devices.sort(key=lambda d: (not d["match"], -(d["rssi"] or -999)))
    return {"scanned_seconds": seconds, "finished": time.time(), "devices": devices,
            "note": "match = name contains 'buds' or Samsung manufacturer id 0x0075"}
