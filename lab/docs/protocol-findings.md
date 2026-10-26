# Protocol findings (Galaxy Buds FE, SM-R400)

Hand-written notes go here; everything below the marker is regenerated.

<!-- AUTO-GENERATED BELOW: regenerated on every export; edit above this line only -->

_Generated 2026-09-29 18:56:23 from sessions: 20260929-185536_

| Dir | ID | Name | Count | Payload sizes | Confidence | Active during | Example payload (hex) |
|---|---|---|---|---|---|---|---|
| rx | 97 | EXTENDED_STATUS_UPDATED | 28 | [46] | Confirmed | (idle)×28 | `02063a590100113c00008f3300004a014a010300046500010010000001011103` |

## Decoded field examples

### EXTENDED_STATUS_UPDATED (97, rx)

```json
{
  "revision": 2,
  "battery_l": 58,
  "battery_r": 89,
  "coupled": true,
  "main": "R",
  "placement_l": 1,
  "placement_r": 1,
  "battery_case": 60,
  "adjust_sound_sync": false,
  "eq_mode": 0,
  "touch_hold_on": true,
  "touch_triple_on": true,
  "touch_double_on": true,
  "touch_single_on": true,
  "touch_double_call_on": false,
  "touch_hold_call_on": false,
  "touch_locked": false,
  "touch_lock_raw": 143,
  "touch_option_l": "volume",
  "touch_option_r": "volume",
  "noise_mode": "off",
  "ambient_volume": 1,
  "noise_reduction_level": 0,
  "charging_l": false,
  "charging_r": false,
  "charging_case": false,
  "_len": 46
}
```

