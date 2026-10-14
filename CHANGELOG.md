# Changelog

Builds are numbered `YYYY.MM.DD.BUILD`. Everything before the first entry is the upstream
[mjmcg/jvc_projector_ha](https://github.com/mjmcg/jvc_projector_ha) history (version 0.1.4),
preserved in this repository's git log up to upstream commit `850aca6`.

## v2026.10.14.3

Phase 3: model-aware controls, firmware version, connection status.

- **Controls follow the model.** The integration reads the model code and creates only what that model supports (from pyjvcprojector's per-specification command tables). On the NZ500 / NZ700 family the **Low Latency** switch is no longer created — those models don't have it.
- **Model names fixed and extended:** B8A2 is the NZ800 (it was shown as NZ900); NZ7 / NZ8 / NZ9, NP5 and NX5 / NX7 / NX9 are recognised.
- New controls: **Theater Optimizer** (HDR only), **Clear Motion Drive** (codes differ on NZ500 / NZ700, handled per model), **Motion Enhance**, **8K e-shift** (NZ800 / NZ900, NZ7 / NZ8 / NZ9, NX9), **ECO Mode**.
- Clear Motion Drive and Dynamic Control are unavailable while Low Latency is on (the projector disables them).
- New sensors: **Color Depth**, **Color Space**, **HDR Signal**, **Software Version**. The firmware version is now read at setup (retried later if the projector doesn't answer) and shown on the device page — it was never read before.
- **Connection** binary sensor: always available, on while the integration reaches the projector.
- **Diagnostics** download (password and host redacted).
- Turning on while the projector is cooling down raises a clear error instead of showing "warming" for a command the projector ignores; turning on when already on does nothing.
- Decoding fixes: Color Space reported only RGB / YUV (now RGB / YCbCr 4:4:4 / 4:2:2 / 4:2:0); HDR Signal lacked HDR10+.
- README: ECO Mode must be off for control in standby; supported-model table; firmware updates are USB-only.
- Removed the old example YAML remote (`lovelace/jvc_remote_card.yaml`); the JVC Projector Card replaces it.
- Tests for all of the above, including an NZ500 that gets only what it supports. **Not yet verified on a real projector:** the new controls, and lens memory over the network.

## v2026.10.13.2

Phase 2: new controls from the command table.

- **Installation Mode** select (lens memory, `INML`): Memory 1–10, or 1–5 on the NZ500 / NZ700 family (model `D8A1` / `D8A2`). The set command waits up to 30 s, because the projector answers only once the lens has stopped. **Not yet verified on a real projector over the network.**
- **Anamorphic** select (`INVS`): Off / A / B / C / D.
- **Low Latency** switch (`PMLL`).
- **HDR Processing** select (`PMHP`): Static / Frame by Frame / Scene by Scene; shows HDR10+ (read-only) for HDR10+ content. **HDR Level** select (`PMHL`): Auto, −2 … +2, Auto (Wide). Both are available only while the source is HDR, and not queried otherwise. Codes checked against pyjvcprojector's 2024 command table.
- These are read on the slow schedule, and re-read after a picture-mode or content-type change and after any change made from HA.
- A command can carry its own timeout (used for the lens move).
- Tests for all of the above (protocol, tables, end-to-end in HA).

## v2026.10.13.1

First build of the Ltek version: fixes.

### Remote lag

- Key presses, power and setting changes no longer wait behind status polling. Upstream held one lock for the whole poll (about 10 commands, each allowed 30 s), so a key could lag by seconds or minutes. Now a user command waits for at most the one poll query already on the wire.
- A command that gets no answer now fails after 5 s (was 15–30 s) and drops the connection, so a late reply can no longer be read as the answer to the next command. A refused connection fails after about 2 s instead of 11 s.
- Polling no longer sends an extra test command and a fresh connection per poll; a burst of commands reuses one connection.

### Errors are shown

- Failed or unanswered remote keys, power, select and laser commands raise an error that the Dashboard shows (upstream only logged them). Unknown remote keys are rejected before anything is sent.
- Selects and laser power update immediately when the projector accepts the command (upstream waited a fixed 2 s first).

### Remote

- `remote.send_command` honours `num_repeats` and `delay_secs`.
- The remote no longer advertises the key list as "activities".

### Translations and states

- `strings.json` replaced (it was left over from a different JVC integration) and kept identical to `translations/en.json`.
- State values are now valid translation keys, so HA shows the translated names and hassfest passes: `no_signal`, `out_of_range`, `4k_3840_24`, `2048x1080_p24`, `vga_640x480`…, `hdr10_plus`, `bt2020_cl` / `bt2020_ncl`. **Automations comparing against the old raw values need updating.**

### Other fixes

- `services.yaml` removed: it documented `jvc_projector_ha.info` and `jvc_projector_ha.send_command`, which never existed and failed when called.
- README: the password hash is SHA-256 (it said MD5). Plaintext passwords are accepted too.
- Light-source hours keep the last value in standby and across HA restarts instead of going "unknown".
- A hostname is resolved again after a connection failure, so a changed DHCP address is picked up without a reload. New **Reconfigure** step to change host, port or password.
- `aiodns` is no longer used (it was imported but not declared); the standard resolver is used.
- No log spam: with no signal the signal-only queries are skipped, and a query that keeps failing is logged once, then retried once a minute.
- Two polling schedules: power, input, signal and picture settings every 10 s; hours, colorimetry and input display once a minute and on any power/input/signal change.
- Coordinator passes its config entry explicitly (required from HA 2026.8). Reauth uses the current API; the password field is described consistently (optional in the form, required by 2024+ models).
- Tests: a fake projector speaking the LAN protocol, protocol tests, translation/table checks, and end-to-end tests in a real Home Assistant instance. `make hassfest` runs HA's validator.
