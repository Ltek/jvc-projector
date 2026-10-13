# Changelog

Builds are numbered `YYYY.MM.DD.BUILD`. Everything before the first entry is the upstream
[mjmcg/jvc_projector_ha](https://github.com/mjmcg/jvc_projector_ha) history (version 0.1.4),
preserved in this repository's git log up to upstream commit `850aca6`.

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
