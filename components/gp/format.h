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

/// "Watchdog: locked" / "Running: B1 B3" / "Irrigation: idle"
inline std::string status_line(const GroupSummary &s) {
  if (s.watchdog_tripped)
    return "Watchdog: locked";
  if (s.active_count > 0)
    return "Running:" + detail::bed_list(s);
  return "Irrigation: idle";
}

/// "AA:on  Q:2"
inline std::string modes_line(const GroupSummary &s) {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "AA:%s  Q:%u", s.auto_advance ? "on" : "off", static_cast<unsigned>(s.queue_length));
  return buf;
}

/// "Dur: B1 5  B2 5  B3 5 min" (run durations in minutes)
inline std::string durations_line(const GroupModel &m) {
  std::string out = "Dur:";
  const size_t count = m.summary().zone_count;
  for (size_t i = 0; i < count; i++) {
    char one[24];
    std::snprintf(one, sizeof(one), "%sB%u %.0f", i == 0 ? " " : "  ", static_cast<unsigned>(i + 1),
                  static_cast<double>(m.zone(i).run_duration) / 60.0);
    if (out.size() + std::char_traits<char>::length(one) + 4 >= LABEL_MAX)
      break;
    out += one;
  }
  return out + " min";
}

/// "Zone left: 00:01:05" (the smallest time left of the active zones)
inline std::string zone_left_line(const GroupSummary &s) {
  return "Zone left: " + (s.has_zone_left ? detail::hms(s.zone_left) : std::string("--:--:--"));
}

/// "Total left: 01:02:05" (the group's current operation)
inline std::string total_left_line(const GroupSummary &s) {
  return "Total left: " + (s.has_total_left ? detail::hms(s.total_left) : std::string("--:--:--"));
}

/// "Queue: (empty)" / "Queue: 00:02:05 next B2" / "Queue: 00:02:05"
inline std::string queue_line(const GroupSummary &s) {
  if (s.queue_time == 0 && s.queue_length == 0)
    return "Queue: (empty)";
  std::string out = "Queue: " + detail::hms(s.queue_time);
  if (s.next_zone >= 0) {
    char one[16];
    std::snprintf(one, sizeof(one), " next B%u", static_cast<unsigned>(s.next_zone + 1));
    out += one;
  }
  return out;
}

/// Home status: "Alarm" / "Watering" / "Idle"
inline std::string home_status(const GroupSummary &s) {
  if (s.watchdog_tripped)
    return "Alarm";
  if (s.active_count > 0)
    return "Watering";
  return "Idle";
}

/// Home "next": "--:--" or "MM:SS" of the queued time
inline std::string home_next(const GroupSummary &s) {
  if (s.queue_time == 0 && s.queue_length == 0)
    return "--:--";
  char buf[16];
  std::snprintf(buf, sizeof(buf), "%02u:%02u", static_cast<unsigned>((s.queue_time % 3600U) / 60U),
                static_cast<unsigned>(s.queue_time % 60U));
  return buf;
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

/// Screensaver date line, e.g. "Friday - 16 Oct" (ASCII only: the built-in fonts have no middle dot).
/// ESPTime fields: `day_of_week` 1 = Sunday .. 7, `day_of_month` 1..31, `month` 1..12. "" when invalid or out of range.
inline std::string saver_date(bool valid, int day_of_week, int day_of_month, int month) {
  static const char *const DAYS[] = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};
  static const char *const MONTHS[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  if (!valid || day_of_week < 1 || day_of_week > 7 || day_of_month < 1 || day_of_month > 31 || month < 1 || month > 12)
    return "";
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%s - %d %s", DAYS[day_of_week - 1], day_of_month, MONTHS[month - 1]);
  return buf;
}

/// ESPHome version text without the config hash / build date: everything up to the first space
/// ("2026.9.1 (config hash 0x1a2b3c4d)" -> "2026.9.1"), so it fits one line of the Network page.
inline std::string version_short(const std::string &version) { return version.substr(0, version.find(' ')); }

/// Same, or "--" while the text sensor has no state yet.
inline std::string version_short_or_dash(bool has_state, const std::string &version) {
  return has_state ? version_short(version) : std::string("--");
}

}  // namespace esphome::gp::fmt
