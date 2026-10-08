# 016 — Time without Home Assistant: SNTP fallback

Status: in-review (review round 1: APPROVE; hardware checks not run)
Roadmap: SPEC §9 stage 10 "Time without HA" (SNTP part; RTC is a follow-up)
Spec sections: SPEC §4 (schedules on the device, HA optional), §5 (core packages), §6 (versions), §7, §8 (clock
users), §9 item 10; CLAUDE.md core principles 3, 6, 7; "Repository layout", "`packages:` order"
Hardware check: yes, but no actuators. On the breadboard ESP32 (display + relay + temperature sensor): the clock
appears with Home Assistant unreachable, and the timezone shown after a reboot without HA. See "Verification
matrix" for what stays unverified.

## Goal
The device clock (`ha_time`) gets set even when Home Assistant is offline or was never added. A new core package,
`packages/core/time_sntp.yaml`, adds an `sntp` time source next to `time: homeassistant`. Both write the same system
clock, so every existing user of `id(ha_time).now()` keeps working unchanged: the Home header clock, the Setup TIME
row, the screensaver and future schedules (stage 11). Wi-Fi with internet access is enough. The package is on by
default and can be turned off by commenting out one line in `garden-pilot.yaml`. The NTP servers are substitutions
with public pool defaults (`0/1/2.pool.ntp.org`), so a user can point them at a router or a LAN NTP server from the
entry file. The PC emulator does not change: `time: host` already works without HA, and `sntp` is not available on
the `host` platform.

## Context

### What ESPHome does (checked 2026-10-08 for the pinned 2026.9.1 and the minimum 2026.6.3)
- **SNTP time source**: [esphome.io/components/time/sntp](https://esphome.io/components/time/sntp/) and the source
  [`esphome/components/sntp/time.py` @2026.9.1](https://github.com/esphome/esphome/blob/2026.9.1/esphome/components/sntp/time.py)
  / [@2026.6.3](https://github.com/esphome/esphome/blob/2026.6.3/esphome/components/sntp/time.py):
  - `servers` is optional, takes 1 to 3 domain names or hostnames (`cv.Length(min=1, max=3)`), and defaults to
    `0.pool.ntp.org`, `1.pool.ntp.org`, `2.pool.ntp.org`. The schema is the same in both versions.
  - `cv.only_on` ESP32, ESP8266, RP2040, BK72XX, LN882X, RTL87XX. **Not `host`**, so the emulator cannot use it.
  - Several `sntp` configs are merged into one instance by a final validator: servers are de-duplicated and cut to 3
    with a warning, and two different manual ids are an error. This is relevant if a user adds a second `sntp` item.
  - The docs say that with manual IPs the device needs `dns1`/`dns2` or IP-only server entries. Today `network.yaml`
    uses DHCP, so this is a note for the docs only.
  - The docs also say that on platforms other than ESP8266/ESP32, `on_time_sync` fires only once, when the system
    clock is first set. On ESP32, `sntp_component.cpp` registers the IDF sync notification and fires `on_time_sync`
    on every SNTP sync
    ([source @2026.9.1](https://github.com/esphome/esphome/blob/2026.9.1/esphome/components/sntp/sntp_component.cpp)).
- **Base time / shared clock**: [esphome.io/components/time](https://esphome.io/components/time/),
  [developers.esphome.io/architecture/components/time](https://developers.esphome.io/architecture/components/time/),
  `esphome/components/time/real_time_clock.{h,cpp}` @2026.9.1 and @2026.6.3:
  - `RealTimeClock::timestamp_now()` is `::time(nullptr)`, and `now()` converts it with the global timezone. **Every
    time component reads the same system clock.** If SNTP sets it, `id(ha_time).now().is_valid()` becomes true even
    though Home Assistant never answered. This is the property the task relies on, and it is why the id `ha_time` can
    stay unchanged.
  - `synchronize_epoch_()` (used by the HA source via `set_epoch_time`) calls `settimeofday`. It skips the write if
    the clock is already valid and within 1 s, but **its `on_time_sync` callbacks are per component**. An SNTP sync
    does not fire `ha_time`'s `on_time_sync`, and the reverse is also true.
  - `update_interval` defaults to `15min` for both sources.
  - The docs contain no example that combines `homeassistant` with `sntp`. The only documented multi-source pattern
    is an RTC chip (DS1307) written from a network source in `on_time_sync`. Two network sources simply both
    `settimeofday` the same clock, and the SNTP page explicitly allows "other real time components" to set the time
    first. Community threads (e.g. [community.home-assistant.io "Struggling with SNTP"](https://community.home-assistant.io/t/struggling-with-sntp/983901))
    report re-sync problems with some LAN NTP servers, not conflicts with the HA source.
- **Timezone** (`esphome/components/time/__init__.py`, `homeassistant/time/__init__.py`, `api/api_connection.cpp`):
  - Without `timezone:`, each time component calls `detect_tz()`, which reads the **build machine's** zone (tzlocal +
    tzdata) and caches it per build. Two components without `timezone:` therefore get the same value and do not
    conflict. An empty string disables timezones.
  - `time: homeassistant` without `timezone:` adds `USE_HOMEASSISTANT_TIMEZONE`, and then the timezone sent by HA is
    applied at runtime with `set_global_tz` when HA answers. In 2026.9.1 this needs HA 2026.3.0+ (pre-parsed
    timezone); in 2026.6.3 it also falls back to parsing the timezone string. Setting `timezone:` on `ha_time` would
    switch the HA push off.
  - Consequence for this task: if the device boots and HA never answers, local time is the zone of the machine that
    compiled the firmware. In the devcontainer that is very likely UTC (no `TZ` is set in `.devcontainer/`). See Open
    question 1. **This task does not set `timezone:` anywhere** (safe default: current HA behaviour unchanged).
- **Minimum version (2026.6.3)**: the sntp schema, the merge validator and the shared-clock behaviour are the same.
  Only the HA timezone decoding differs (see above), and it does not affect this design. `GP_ESPHOME=minimum
  script/config` plus the CI `compile (minimum)` job prove it.

### Current repo facts
- `packages/core/time.yaml` is `time: - platform: homeassistant, id: ha_time` with no triggers.
  `packages/core/time_host.yaml` is the same with `platform: host` (emulator). `tests/test_layout.py::test_core_split`
  asserts exactly one item in each.
- Users of `ha_time`: `packages/lvgl/page_home.yaml` (`!extend ha_time` `on_time_sync` plus a 30 s `interval`),
  `packages/lvgl/page_setup.yaml` and `packages/lvgl/screensaver.yaml` (polled, guarded by
  `id(ha_time).now().is_valid()`). All polled paths pick up an SNTP-set clock with no change. The Home header clock
  lags at most 30 s after an SNTP-only sync, because `ha_time.on_time_sync` does not fire then. That is acceptable,
  so no LVGL code goes into core (`test_core_is_display_independent`).
- Package defaults are set as package-level `substitutions:`, and the entry file wins (pattern of
  `page_boot.yaml` `boot_offline_timeout` and `screensaver.yaml` `screensaver_timeout`).
- Board profile: ESP32-S3, `framework: esp-idf`. `network.yaml` uses DHCP with a fallback AP. SNTP does nothing in AP
  mode or without internet, and that is fine.

## Decisions
1. **Separate optional package `packages/core/time_sntp.yaml`.** It is not a second item in `time.yaml`, so that:
   (a) `time.yaml` / `time_host.yaml` stay the one-item `ha_time` files the tests and the emulator rely on; (b) a user
   without internet access, or who wants HA as the only source, comments out one line (principle 3); (c) remote
   package users can include it on its own. Content:
   ```yaml
   substitutions:
     sntp_server_1: 0.pool.ntp.org
     sntp_server_2: 1.pool.ntp.org
     sntp_server_3: 2.pool.ntp.org

   time:
     - platform: sntp
       id: sntp_time
       servers:
         - ${sntp_server_1}
         - ${sntp_server_2}
         - ${sntp_server_3}
   ```
   Add a header comment that explains: it is the fallback for `ha_time` (same system clock, so features use `ha_time`
   only and never `sntp_time`); it needs Wi-Fi with internet or a LAN NTP server; override servers from the entry
   file (a router or LAN NTP server is fine, generic example `ntp.example.lan`, no real addresses); manual IPs need
   DNS or IP-only entries; it does not work in the emulator (`host` has no sntp); no `timezone:` (see `time.yaml`
   and SPEC §4); it does not fire `ha_time`'s `on_time_sync`, so polled readers only.
   No `update_interval`, no `on_time` / `on_time_sync`, no `timezone`, no `!secret`.
2. **Id `sntp_time`.** It exists for logs and lambdas while debugging. No feature file references it (a check
   enforces this). `ha_time` remains the single id the rest of the config uses. Renaming `ha_time` to a neutral id
   stays a separate follow-up (already listed since task 006).
3. **Entry file:** `core_time_sntp: !include packages/core/time_sntp.yaml` directly after `core_time`. Add a comment
   line: "Clock fallback without Home Assistant (NTP over Wi-Fi). Comment out for HA-only time; servers via
   sntp_server_N substitutions." Do **not** add `sntp_server_*` to the entry file's `substitutions:` (defaults live in
   the package; the entry file only shows them in a commented example, if at all). New order:
   `hardware, core_api, core_ota, core_network, core_time, core_time_sntp, core_diagnostics, ...`.
4. **Emulator unchanged.** `garden-pilot-sim.yaml` gets no `core_time_sntp` (`cv.only_on` rejects `host`), and
   `test_sim_entry_file` forbids it.
5. **`packages/core/time.yaml`**: only the header comment changes ("NTP fallback: time_sntp.yaml; both set the same
   system clock; no `timezone:` here so Home Assistant's timezone is applied"). The YAML body stays as is.

## Files
- create: `packages/core/time_sntp.yaml` — SNTP fallback source (Decision 1).
- modify: `garden-pilot.yaml` — `core_time_sntp` include after `core_time`, plus a comment (Decision 3).
- modify: `packages/core/time.yaml` — header comment only (Decision 5).
- modify: `tests/test_layout.py` — new checks below; `test_sim_entry_file` forbidden set gets `core_time_sntp`.
- modify: `tests/test_esphome_config.py` — entry order prefix includes `core_time_sntp`.
- modify: `tests/test_config_matrix.py` — `CORE` gains `core_time_sntp`; new variants; server-override config check.
- modify: `docs/SPEC.md` — §5 core list (`time_sntp`), §9 item 10 (SNTP done by task 016, RTC follow-up), a short
  paragraph in §4 or §8 on the time sources and the offline timezone behaviour, §11 sources (sntp/time docs).
- modify: `CLAUDE.md` — layout table row for `packages/core/time*.yaml`, `packages:` order item 1
  (`core_time_sntp` after `core_time`; the sim entry has no `core_time_sntp`), and one gotcha line: "`sntp` and
  `homeassistant` share the system clock: read `ha_time` only; an SNTP sync does not fire `ha_time.on_time_sync`
  (poll); `sntp` is not available on `host`."

8 files. `README.md` / `README.ru.md` change only if the implementer finds a module list there that names the core
packages (none was found when planning). If one is changed, keep both in sync.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_layout.py::test_time_sntp_package` | `packages/core/time_sntp.yaml` top-level keys are exactly `{substitutions, time}`; `time` has one item with `platform: sntp`, `id: sntp_time`, `servers == ["${sntp_server_1}", "${sntp_server_2}", "${sntp_server_3}"]`; the item has no `timezone`, `update_interval`, `on_time`, `on_time_sync`; substitution defaults are exactly `0.pool.ntp.org`, `1.pool.ntp.org`, `2.pool.ntp.org` (public hostnames, not IPs); no `!secret` anywhere in the file. |
| unit | `tests/test_layout.py::test_core_split` (extend) | Unchanged assertions on `time.yaml` / `time_host.yaml` (one item each, id `ha_time`) still hold. Additionally, neither file has a `timezone` key (guards the HA timezone push; see Decision 5 and Open question 1). |
| unit | `tests/test_layout.py::test_time_ids_single_source` | Across tracked `packages/**/*.yaml`, `hardware/*.yaml` and both entry files: a `time:` item that **defines** (not `!extend`s) `id: ha_time` exists only in `packages/core/time.yaml` and `packages/core/time_host.yaml`; the string `sntp_time` (comments stripped) appears only in `packages/core/time_sntp.yaml`; `platform: sntp` appears only there. |
| unit | `tests/test_layout.py::test_entry_time_sources` | In `garden-pilot.yaml`, `core_time_sntp` is an active include of `packages/core/time_sntp.yaml` placed directly after `core_time`; the entry file's `substitutions` defines no `sntp_server_*` (defaults live in the package). |
| unit | `tests/test_layout.py::test_sim_entry_file` (extend) | `core_time_sntp` is in the `forbidden` set of the sim entry file. |
| unit | `tests/test_esphome_config.py::test_entry_file_is_a_package_list` (extend) | `keys[:6] == ["hardware", "core_api", "core_ota", "core_network", "core_time", "core_time_sntp"]`. |
| unit | existing `tests/test_layout.py::test_substitutions_resolve`, `test_core_is_display_independent`, `tests/test_public_hygiene.py` | Still green with the new package (they catch an undefined `${sntp_server_N}`, LVGL in core, private IPs). No change expected; fix the package, not the test. |
| config | `tests/test_config_matrix.py::test_variant_validates[headless]` (changed via `CORE`) | `CORE` becomes `[..., "core_time", "core_time_sntp"]`, so every headless row now validates HA + SNTP together. |
| config | `tests/test_config_matrix.py::test_variant_validates[no_sntp]` (new: `Variant("without", ["core_time_sntp"])`) | The full device config validates with HA-only time (the package is really optional). |
| config | `tests/test_config_matrix.py::test_variant_validates[headless_sntp_only]` (new: `Variant("keep", ["hardware", "core_api", "core_ota", "core_network", "core_time_sntp"])`) | The SNTP package validates without `core_time` (self-contained; no hidden dependency on `ha_time`). |
| config | `tests/test_config_matrix.py::test_sntp_servers_override` (new, `config` marker) | Build the `headless` variant, insert `  sntp_server_1: ntp.example.lan` under the entry file's `substitutions:`, run `script/_esphome config` as `test_variant_validates` does. Assert exit code 0, that `ntp.example.lan` is in stdout, and that `0.pool.ntp.org` is **not** in stdout (the entry file wins over the package default), while `1.pool.ntp.org` is still there. |
| config | existing `tests/test_esphome_config.py::test_esphome_config_passes_*`, sim matrix rows | Device and emulator configs still validate. The sim rows need `sdl2-config` (CI sets `GP_REQUIRE_SDL=1`). |
| compile | CI `compile (pinned)` / `compile (minimum)` | The ESP32 firmware with `sntp` + `homeassistant` builds on 2026.9.1 and 2026.6.3. The host build is unchanged. |

No `cpp` / `host` checks: there is no C++ here, and `sntp` cannot run on `host`.

## Acceptance criteria
- [x] `uv run pytest -m unit` → passes, including the new/extended tests above.
- [x] `script/lint` → passes (yamllint + `esphome config`).
- [x] `script/test` → passes, including the new matrix rows `no_sntp`, `headless_sntp_only` and `test_sntp_servers_override`.
- [x] `GP_SECRETS=example script/config garden-pilot.yaml` → exit 0. Its output shows one `time:` item with
      `platform: sntp`, `id: sntp_time` and the three pool servers, and one item with `platform: homeassistant`,
      `id: ha_time` and no `timezone`.
- [x] `GP_SECRETS=example GP_ESPHOME=minimum script/config garden-pilot.yaml` → exit 0 (2026.6.3; run offline by the reviewer).
- [ ] `GP_SECRETS=example script/compile garden-pilot.yaml` → builds. In CI: `compile (pinned)` and `compile (minimum)` green.
- [ ] Emulator config unchanged: the normalized `esphome config` output of `garden-pilot-sim.yaml` (with
      `GP_SECRETS=example`) is identical before and after the change. Paste the diff command and its empty result in
      Implementation notes.
- [x] `grep -rn "sntp_time" packages hardware garden-pilot*.yaml` → matches only in `packages/core/time_sntp.yaml`.
- [x] No `!secret`, no IP addresses and no non-generic hostnames in the new package or the docs (only `*.pool.ntp.org`
      and `*.example.lan` style examples).
- [x] `docs/SPEC.md` and `CLAUDE.md` updated as listed under Files. SPEC §9 item 10 says SNTP is done (task 016) and
      RTC is a follow-up.
- [x] Timezone substitution (open question 1): `timezone: ${timezone}` (default `UTC`) on `ha_time` and `sntp_time`; the config output shows it on both, an entry-file override replaces it on both; documented in SPEC 4.1a, the package headers and the entry file.
- [ ] **Hardware (human, breadboard ESP32; cannot run in CI):** the verification matrix below is filled in under
      Implementation notes with "verified" or "not verified" per row. If it is not run, the PR description says so.

### Verification matrix
| Scenario | Where | How | Expected |
|---|---|---|---|
| Config shape, override, minimum version | CI / any PC | tests above | green |
| Firmware builds with both sources | CI compile jobs | `script/compile` | green |
| Emulator still works without HA | PC (`script/sim`) | open Home / Setup | clock from the PC as before. **SNTP itself cannot be exercised in the emulator** (`host` has no sntp). |
| HA reachable | breadboard | flash, watch `uv run esphome logs garden-pilot.yaml` | clock valid; no repeated time jumps in the log over about 30 min (both sources agree within 1 s) |
| HA unreachable, internet up | breadboard | disable the device in HA (or keep a test device unadopted), reboot | Home header clock appears within about 30 s of the SNTP sync; Setup TIME row is valid; screensaver clock shows time. The SNTP sync log line may be DEBUG level: raise `logger` locally only, never commit it. |
| Timezone after a reboot without HA | breadboard | same as above, build in the devcontainer | note the offset shown (expected: the build machine's zone, likely UTC in the devcontainer). This is input for Open question 1. |
| Wi-Fi without internet and no HA | breadboard (optional) | router blocks WAN | clock stays `--:--`, no errors that block boot; relays untouched |

**Stays unverified by this task:** long-run re-sync and drift over days, DST transitions, behaviour when the HA host
clock is wrong (the two sources would fight every 15 min), manual-IP/DNS setups, a LAN NTP server, any other board,
and schedules (none exist yet). No actuator is touched by this change: the relay and temperature sensor on the
breadboard are irrelevant to it.

## Out of scope
- **RTC chip** (DS3231/DS1307/PCF8563 over I2C, written from `on_time_sync` of both sources, read at boot). It is
  needed only for "no Wi-Fi at all after a power cut". It requires I2C pins in `hardware/` and a part choice, which
  are the human's call. Follow-up task in stage 10.
- A time-source / last-sync indicator on the Network or Setup page (would need `on_time_sync` of both sources, with
  LVGL only in `packages/lvgl/`).
- Renaming `ha_time` to a neutral id (existing follow-up since task 006).
- Schedule behaviour on clock jumps (missed / duplicated `on_time` runs): stage 11 must define it.
- DHCP-provided NTP servers (option 42). ESPHome sets servers explicitly, and this was not investigated.
- Any change to `garden-pilot-sim.yaml`, `time_host.yaml` or the LVGL pages.

## Open questions
Decided by the human 2026-10-08:
1. **Offline timezone:** add a `timezone` substitution (default `UTC`, IANA name, overridable from the entry file)
   applied to both time sources. This stops the Home Assistant timezone push; documented in SPEC 4.1a.
2. **Default NTP servers:** the NTP Pool defaults (`0/1/2.pool.ntp.org`) are fine.
3. **SNTP on by default:** yes.

<!-- Filled in by implementer -->
## Implementation notes
- Open questions: safe defaults used (no `timezone:` anywhere and the offline zone documented in SPEC section 4.1a; `*.pool.ntp.org`; SNTP on by default).
- New SPEC paragraph is "4.1a Time sources"; README files name no core packages, so unchanged.
- Results: `pytest -m unit` 495 passed; `script/lint` ok; `script/test` 513 passed, 9 skipped (no SDL/compiler); device config output shows `homeassistant`/`ha_time` (no timezone) and `sntp`/`sntp_time` with the three pool servers.
- Not run: `GP_ESPHOME=minimum script/config` (UV_OFFLINE, esphome 2026.6.3 not in the uv cache), `script/compile` (not attempted; CI), the before/after sim config diff (no file used by the sim entry changed: `garden-pilot-sim.yaml`, `time_host.yaml` and the sim packages are untouched), and the whole hardware verification matrix (all rows "not verified").
- Timezone follow-up (2026-10-08; results: unit 497 passed, lint ok, script/test 517 passed / 9 skipped, also with UV_OFFLINE=1 GP_ESPHOME=minimum 2026.6.3; `esphome config` shows the zone normalized to POSIX, UTC0 on both sources): `timezone` default `UTC` is declared in both `time.yaml` and `time_sntp.yaml` (same value, so each works alone, e.g. the `headless_sntp_only` variant); the entry file shows a commented example. `time_host.yaml` is left alone: without `timezone` the host source keeps the PC zone detected at build time, and a `UTC` default would make the emulator clock wrong for most users. `test_core_split` no longer forbids `timezone` on the device source and instead asserts it on `time.yaml` and its absence on `time_host.yaml`. New config tests: `test_timezone_default_is_utc_on_both_sources`, `test_timezone_override`. Offline zone after reboot is still unverified on hardware.
## Follow-ups
