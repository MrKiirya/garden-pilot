// gp — ASCII label helpers (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Every LVGL label lambda of the greenhouse pages is one call to a function in this file, so the formatting is
// testable and shared. Texts are printable ASCII (the built-in LVGL fonts have no other glyphs) and shorter than
// LABEL_MAX characters.
#pragma once

#include <cstdint>
#include <cstdio>
#include <string>

#include "zone_model.h"
#include "format_screens.h"

namespace esphome::gp::fmt {

inline constexpr size_t LABEL_MAX = 64;

namespace detail {
inline std::string hms(uint32_t seconds) {
  char buf[16];
  std::snprintf(buf, sizeof(buf), "%02u:%02u:%02u", static_cast<unsigned>(seconds / 3600U),
                static_cast<unsigned>((seconds % 3600U) / 60U), static_cast<unsigned>(seconds % 60U));
  return buf;
}

/// " B1 B3 ..." (a leading space before every entry), at most as many as fit.
inline std::string bed_list(const GroupSummary &s) {
  std::string out;
  for (size_t i = 0; i < s.active_count; i++) {
    char one[8];
    std::snprintf(one, sizeof(one), " B%u", static_cast<unsigned>(s.active[i] + 1));
    if (out.size() + 3 + 24 < LABEL_MAX)
      out += one;
  }
  return out;
}
}  // namespace detail

/// Home status: "Alarm" / "Watering" / "Idle"
inline std::string home_status(const GroupSummary &s) {
  if (s.watchdog_tripped)
    return "Alarm";
  if (s.active_count > 0)
    return "Watering";
  return "Idle";
}

/// Home Assistant status text: "Idle" / "Watering B1 B3" / "Locked"
inline std::string ha_status(const GroupSummary &s) {
  if (s.watchdog_tripped)
    return "Locked";
  if (s.active_count > 0)
    return "Watering" + detail::bed_list(s);
  return "Idle";
}

/// Valve test row: "OPEN - 8 s" / "locked" / "closed"
inline std::string valve_test_row(const ZoneView &z) {
  if (z.state == ZoneState::RUNNING) {
    char buf[24];
    std::snprintf(buf, sizeof(buf), "OPEN - %u s", static_cast<unsigned>(z.time_left.value_or(0)));
    return buf;
  }
  if (z.state == ZoneState::LOCKED)
    return "locked";
  return "closed";
}

/// Valve test row colour (design tokens): open green, otherwise the muted on-surface colour.
inline uint32_t valve_test_color(const ZoneView &z) { return z.state == ZoneState::RUNNING ? 0x78dc77U : 0xbecab9U; }

/// Screensaver indicator: "" when idle, "Bed 2" or "Bed 1+" (more zones active) otherwise.
inline std::string saver_bed(const GroupSummary &s) {
  if (s.active_count == 0)
    return "";
  char buf[16];
  std::snprintf(buf, sizeof(buf), "Bed %u%s", static_cast<unsigned>(s.active[0] + 1), s.active_count > 1 ? "+" : "");
  return buf;
}

}  // namespace esphome::gp::fmt
