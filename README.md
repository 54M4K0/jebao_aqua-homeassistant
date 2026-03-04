# Jebao Aqua - Home Assistant Integration

[![HACS Validation](https://github.com/ergo5/jebao_aqua-homeassistant/actions/workflows/hacs-validate.yml/badge.svg)](https://github.com/ergo5/jebao_aqua-homeassistant/actions/workflows/hacs-validate.yml)
[![hassfest Validation](https://github.com/ergo5/jebao_aqua-homeassistant/actions/workflows/hassfest.yml/badge.svg)](https://github.com/ergo5/jebao_aqua-homeassistant/actions/workflows/hassfest.yml)

Custom Home Assistant integration for Jebao aquarium devices (dosing pumps, wave makers, LED lights, feeders, filters) via the Gizwits cloud API.

## Features

- **Cloud API Integration** — Connect via Jebao Aqua app credentials (EU/US/CN regions)
- **Universal Device Discovery** — Automatically discovers all Jebao devices linked to your account
- **42 Device Models** — Pre-loaded attribute models from the official Jebao app
- **Smart Dosing Status** — Per-channel dosing schedule summary (ml/day, doses, interval)
- **Device Info Sensors** — Device clock, firmware version, cloud status
- **Dosing Schedule Service** — Program dosing schedules directly from Home Assistant
- **English Translations** — All entity names and options translated from Chinese to English

## Supported Devices

- **Dosing Pumps**: MD-4.5, WiFi Multi-Head Doser, BT Multi-Head Doser
- **Wave Makers**: SOW, SLW, OW, RW, MLW series
- **LED Lights**: AL, PL, FL series (Freshwater/Planted/Marine)
- **DC Pumps**: DCS, DCP, DCT series
- **Feeders**: WiFi Auto Feeder
- **Filters**: WiFi Canister Filter

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Jebao Aqua" and install
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Jebao Aqua**

### Manual

1. Copy `custom_components/jebao_aqua` to your HA `custom_components/` directory
2. Restart Home Assistant
3. Add the integration via **Settings → Devices & Services**

## Configuration

Enter your Jebao Aqua app credentials:
- **Email** — Your Jebao Aqua account email
- **Password** — Your Jebao Aqua account password
- **Region** — EU, US, or CN (select based on your account region)

## Services

### `jebao_aqua.set_dosing_schedule`

Program a dosing channel with an automated schedule. The pump runs autonomously after programming.

```yaml
service: jebao_aqua.set_dosing_schedule
data:
  channel: 1            # Channel 1-8
  daily_ml: 100         # ml per day
  doses_per_day: 24     # Doses per day (evenly distributed)
  day_interval: 0       # 0=daily, 1=every 2 days, 2=every 3 days...
  enable: true          # Enable the timer
```

## Entity Types

| Entity | Description |
|--------|-------------|
| **Power** | Master on/off switch |
| **Active Channels** | Number of active dosing channels |
| **Dosing CH1-8** | Per-channel dosing status summary |
| **Device Clock** | Current device date/time |
| **Firmware Version** | MCU and WiFi module version |
| **Cloud Status** | Online/Offline cloud connectivity |
| **UART Fault** | Serial communication error alarm |
| **Open Circuit** | Open circuit detection alarm |

## Credits

Based on the original work by [chrisc123](https://github.com/chrisc123/jebao_aqua-homeassistant).

## License

MIT License — see [LICENSE](LICENSE) for details.
