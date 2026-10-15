# JVC Projector – Home Assistant Integration (Ltek)

A Home Assistant integration for JVC D-ILA projectors using the [**2024 External Command Communication Specification**](https://www.jvc.com/usa/projectors/installers-calibrators/external-command-communication-specification/) over the network.

Current build: **v2026.10.15.4** · full history in [CHANGELOG.md](CHANGELOG.md)

This is the Ltek version of [mjmcg/jvc_projector_ha](https://github.com/mjmcg/jvc_projector_ha). It keeps the same integration domain (`jvc_projector_ha`), so it replaces the original in place. The [JVC Projector Card](https://github.com/Ltek/jvc-projector-card) is the matching Dashboard card: v2026.10.14.3 or later shows every control here (lens memory, anamorphic, HDR, Theater Optimizer, motion, e-shift, low latency, ECO mode), plus firmware, signal details and the connection state.

## Supported Models

Built and tested on the DLA-NZ500; it should work with other models that implement the same API. The integration reads the model and creates only the controls that model supports (from [pyjvcprojector](https://github.com/SteveEasley/pyjvcprojector)'s per-model command tables):

| Family (model code) | Also sold as | Not on this family |
|---|---|---|
| **NZ800 / NZ900** (B8A2 / B8A1) | RS3200, RS4200, N988, N1188, V800R, V900R | — (everything) |
| **NZ500 / NZ700** (D8A2 / D8A1) | RS1200, RS2200, N7xx, N8xx, Z5, Z7 | Low Latency, Theater Optimizer, Motion Enhance, 8K e-shift; lens memory 1–5 |
| **NZ7 / NZ8 / NZ9, NP5** (B5A*, B5B1) | RS2100, RS3100, RS4100, RS1100 | laser power, Dynamic Control; 8K e-shift on the NP5 |
| **NX5 / NX7 / NX9** (B2A*) | RS1000, RS2000, RS3000 | laser power, Dynamic Control; 8K e-shift except on the NX9 |

An unknown model gets every control; a command it doesn't answer is retried only once a minute. The [**2025 specification**](https://www.jvc.com/usa/projectors/installers-calibrators/external_command_dlanz900_series/) for the DLA-NZ800 / NZ900 uses the same API.

> **ECO Mode must be off** for Home Assistant to reach the projector in standby (and so to turn it on). With ECO Mode on, the projector switches its network off in standby, and the integration shows it as not connected until it is turned on with the remote. The **ECO Mode** switch shows the setting.

---

## Entities

**Controls**

| Entity | What it does |
|---|---|
| Remote | Power on / off, and every IR remote key through `remote.send_command` |
| Input | HDMI 1 / HDMI 2 |
| Picture Mode | Cinema, Natural, HDR, FILMMAKER MODE… — only the modes valid for the current content type are offered |
| Dynamic Control | Off / Low / High / Balanced |
| LD Power | Laser power, 1–100 |
| Installation Mode | Lens memory: Memory 1–10 (1–5 on the NZ500 / NZ700 family). The command answers once the lens has finished moving. |
| Anamorphic | Off / A / B / C / D |
| HDR Processing | Static / Frame by Frame / Scene by Scene. Shows HDR10+ when the projector uses it for HDR10+ content (it can't be selected). Available only while the source is HDR. |
| HDR Level | Auto / −2 … +2 / Auto (Wide). Available only while the source is HDR. |
| Low Latency | On / off. The projector refuses it while some picture settings are active (you get an error). While it is on, Clear Motion Drive and Dynamic Control are unavailable. |
| Theater Optimizer | On / off. Available only while the source is HDR. |
| Clear Motion Drive | Off / Low / High / Inverse Telecine (NZ500 / NZ700: Off / Low / High) |
| Motion Enhance | Off / Low / High |
| 8K e-shift | On / off (NZ800 / NZ900, NZ7 / NZ8 / NZ9, NX9) |
| ECO Mode | On / off — keep it **off** (see above) |

**Sensors** (diagnostic)

| Entity | Notes |
|---|---|
| Power State | On / Standby / Warming / Cooling / Error |
| Light Source Time | Hours. Keeps the last value in standby and across HA restarts (the projector only reports it while on). |
| Source Display | Resolution and rate (4K (3840) 24Hz, 1080p60, No signal…) |
| Content Type | SDR / HDR10 / HDR10+ / HLG |
| Colorimetry | BT.709, BT.2020, DCI-P3… |
| Color Depth | 8 / 10 / 12-bit |
| Color Space | RGB, YCbCr 4:4:4 / 4:2:2 / 4:2:0 |
| HDR Signal | SDR, HDR10 (SMPTE ST 2084), HLG, HDR10+ |
| Software Version | The projector's firmware version; also shown on the device page |
| Connection | Whether the integration reaches the projector. Always available, so a Dashboard can tell *not reachable* from *off*. |
| Input Display, Model, Power, Signal Present | Disabled by default |

Controls are available only while the projector is on. Turning the projector on while it is cooling down gives an error instead of doing nothing: it can be turned on once it reaches standby.

**Diagnostics:** Settings → Devices & Services → JVC Projector → ⋮ → Download diagnostics gives the model, specification, firmware version, failing queries and current state (password and host redacted).

**Firmware updates** can't be started over the network: JVC's control protocol only reports the version. Update from a USB stick as JVC describes for your model.

When a command fails (the projector is unreachable, or it doesn't answer because the setting isn't valid with the current signal), the Dashboard shows an error instead of the change silently not happening.

### State values

Sensor and select states are lower-case keys that Home Assistant translates for display, for example `no_signal`, `4k_3840_24`, `hdr10_plus`, `bt2020_ncl`. If you have automations or templates that compare against the old raw values (`No Signal`, `4k(3840)24`, `hdr10+`, `bt2020(constant_luminance)`), update them.

---

## Remote

```yaml
action: remote.send_command
target:
  entity_id: remote.jvc_projector
data:
  command: menu
```

`command` is a button name, a `REMOTE_*` name, or a raw 4-digit hex code. Button names:

| Group | Buttons |
|---|---|
| Power | `on`, `standby` |
| Navigation | `menu`, `up`, `down`, `left`, `right`, `ok`, `back` |
| Quick access | `mpc`, `hide`, `info`, `input`, `advanced_menu` |
| Picture | `picture_mode`, `color_profile`, `gamma_settings`, `cmd`, `gamma`, `color_temp`, `pic_adj` |
| Presets | `mode_1`, `mode_2`, `mode_3`, `natural`, `cinema` |
| Input | `hdmi_1`, `hdmi_2` |
| Lens | `lens_control`, `lens_ap`, `anamo` |
| Other | `setting_memory`, `3d_format` |

`num_repeats` and `delay_secs` are honoured, so a held key can be one call:

```yaml
action: remote.send_command
target:
  entity_id: remote.jvc_projector
data:
  command: down
  num_repeats: 5
  delay_secs: 0.15
```

Key presses and setting changes go ahead of status polling: a key waits for at most the one status query already in flight, not for the whole poll.

For a ready-made Dashboard remote, use the [JVC Projector Card](https://github.com/Ltek/jvc-projector-card).

---

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Ltek&repository=jvc-projector&category=integration)

Or in HACS → ⋮ → Custom repositories, add `https://github.com/Ltek/jvc-projector` as an **Integration**. If you had mjmcg's version installed through HACS, remove that repository first; your config entry and entities are kept because the domain is the same.

### Manual

1. Copy `custom_components/jvc_projector_ha` into `config/custom_components/`.
2. Restart Home Assistant.
3. Add the integration under **Settings → Devices & Services**.

---

## Configuration

You need:

- Network connectivity between Home Assistant and the projector
- The projector's IP address or hostname
- The port (default 20554)
- The network password (see below)

To change the address, port or password later: **Settings → Devices & Services → JVC Projector → ⋮ → Reconfigure**.

### Timing

**Settings → Devices & Services → JVC Projector → Configure** sets how the integration talks to the projector. The defaults suit most projectors.

| Option | Default | What it does |
|---|---|---|
| Poll interval | 10 s | How often the projector is asked for its state. |
| Response timeout | 5 s | Wait for an answer to a query or a quick command (remote key, power). |
| Picture mode / input change timeout | 10 s | The projector answers these only once the change is done. |
| Lens memory timeout | 30 s | The projector answers once the lens has stopped moving. |
| Recovery pause | 30 s | When the projector stops answering, stop polling it this long so it can recover (0 = off). Your own commands are still sent; one that is answered ends the pause. |

If a setting does change on the projector but Home Assistant says *the projector did not answer*, raise that timeout. If the projector often stops answering, a longer poll interval or recovery pause gives it more rest.

### Network password

2024-and-later JVC models require a network password for control. Set one on the projector with the remote; it must be 8–10 characters, e.g. `MyPassword`.

Enter either:

- **the plaintext password** (`MyPassword`) — the integration hashes it, or
- **the pre-hashed value**: SHA-256 of the password followed by `JVCKWPJ`.

To make the hash yourself:

```sh
printf '%s' 'MyPasswordJVCKWPJ' | sha256sum
```

For `MyPassword` the result is `"98c75d723b5bc9d638c87618bdfde6d6dffe2a5cfebf3d2f918c95e1ea2f3b40"` (64 hex characters). Any 64-character hex string is taken as already hashed.

### Address changes

If you configured a **hostname**, the integration looks it up again after a connection failure, so a new DHCP address is picked up without a reload. If you configured an **IP address**, give the projector a DHCP reservation, or use Reconfigure when the address changes.

### Network connectivity

If your projector only has a wired network connection, a travel router such as the [TP-Link TL-WR902AC](https://www.tp-link.com/us/home-networking/wifi-router/tl-wr902ac/) in client mode can bridge it to Wi-Fi.

---

## Polling

Every 10 s (the Poll interval option) the integration reads power, input and signal, and (while on) picture mode, dynamic control, laser power, source resolution and content type. Light-source hours, colorimetry, color depth / space, HDR signal, input display, installation mode, anamorphic, low latency, motion settings, e-shift, ECO mode, Theater Optimizer and the HDR settings are read once a minute and whenever power, input, signal, picture mode or content type changes. A value you set from Home Assistant shows immediately. With no signal, the signal-only queries are skipped. A query that keeps failing (for example a command your model doesn't support) is logged once and then retried only once a minute. When a query gets no answer, the rest of that poll is skipped (the last values are kept) instead of sending the projector more commands it isn't answering.

---

## Development

```sh
uv sync                                   # dev environment (Home Assistant, pytest)
uv run pytest tests/ -q                   # protocol, table and Home Assistant tests
make hassfest                             # HA's integration validator (docker/podman)
```

The tests run a fake projector that speaks the LAN protocol, and start a real Home Assistant instance for the end-to-end tests.

---

## Credits

Original integration by [Matt McGarry (mjmcg)](https://github.com/mjmcg/jvc_projector_ha). The device communication code is derived from [pyjvcprojector](https://github.com/SteveEasley/pyjvcprojector) by [Steve Easley](https://github.com/SteveEasley) (MIT). Inspired by [iloveicedgreentea/jvc_homeassistant](https://github.com/iloveicedgreentea/jvc_homeassistant).

## License

MIT — see [LICENSE](LICENSE).
