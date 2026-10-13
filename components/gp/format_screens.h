// gp - texts and colours of the design-system screens (pure C++17, no ESPHome includes; unit tested on the host
// compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Included by format.h. Printable ASCII only (the built-in LVGL fonts have no other glyphs), shorter than LABEL_MAX.
// Colours are the values of design/tokens.json (tests/test_screens_gp.py checks the list).
//
// Local civil time never enters this file: the glue converts an epoch to a `Moment` (ESPTime::from_epoch_local).
#pragma once

#include <cstdint>
#include <cstdio>
#include <optional>
#include <string>

#include "zone_model.h"

namespace esphome::gp::fmt {

namespace color {
inline constexpr uint32_t GREEN = 0x78dc77;
inline constexpr uint32_t GREEN_FILL = 0x4caf50;
inline constexpr uint32_t BLUE = 0x9ecaff;
inline constexpr uint32_t BLUE_FILL = 0x1e95f2;
inline constexpr uint32_t AMBER = 0xffb870;
inline constexpr uint32_t AMBER_FILL = 0xe18500;
inline constexpr uint32_t TEXT_DIM = 0xbecab9;
inline constexpr uint32_t BORDER = 0x3f4a3c;
}  // namespace color

/// A local date and time; `known` is false when the epoch was 0 (the clock was not valid) or there is no clock.
struct Moment {
  bool known{false};
  int year{0}, month{0}, day{0}, hour{0}, minute{0};
  bool same_day(const Moment &o) const { return known && o.known && year == o.year && month == o.month && day == o.day; }
};

namespace detail {
inline const char *month_name(int month) {
  static const char *const NAMES[12] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  return month >= 1 && month <= 12 ? NAMES[month - 1] : "---";
}
/// "13 Oct"
inline std::string date_text(const Moment &m) {
  char buf[16];
  std::snprintf(buf, sizeof(buf), "%d %s", m.day, month_name(m.month));
  return buf;
}
inline std::string clock_text(const Moment &m) {
  char buf[8];
  std::snprintf(buf, sizeof(buf), "%02d:%02d", m.hour, m.minute);
  return buf;
}
/// "45 s" / "5 min" (rounded to whole minutes from one minute)
inline std::string duration_text(uint32_t seconds) {
  char buf[16];
  if (seconds < 60)
    std::snprintf(buf, sizeof(buf), "%u s", static_cast<unsigned>(seconds));
  else
    std::snprintf(buf, sizeof(buf), "%u min", static_cast<unsigned>((seconds + 30U) / 60U));
  return buf;
}
/// "45s" / "5m": the short form for the last-watering line of a card
inline std::string duration_short(uint32_t seconds) {
  char buf[16];
  if (seconds < 60)
    std::snprintf(buf, sizeof(buf), "%us", static_cast<unsigned>(seconds));
  else
    std::snprintf(buf, sizeof(buf), "%um", static_cast<unsigned>((seconds + 30U) / 60U));
  return buf;
}
}  // namespace detail

/// The zone name on a card: a leading "<group name> " is dropped ("Greenhouse bed 1" -> "Bed 1").
inline std::string card_name(const char *name, const char *group_name) {
  std::string out = name != nullptr ? name : "";
  const std::string prefix = std::string(group_name != nullptr ? group_name : "") + " ";
  if (prefix.size() > 1 && out.size() > prefix.size() && out.compare(0, prefix.size(), prefix) == 0) {
    out.erase(0, prefix.size());
    if (!out.empty() && out[0] >= 'a' && out[0] <= 'z')
      out[0] = static_cast<char>(out[0] - 'a' + 'A');
  }
  return out;
}

/// Watering / Queued #2 / Off / Locked / Paused / Skipped / Idle
inline std::string card_state(const ZoneView &z) {
  switch (z.state) {
    case ZoneState::RUNNING: return "Watering";
    case ZoneState::QUEUED: {
      if (!z.queue_position.has_value())
        return "Queued";
      char buf[16];
      std::snprintf(buf, sizeof(buf), "Queued #%u", static_cast<unsigned>(*z.queue_position) + 1U);
      return buf;
    }
    case ZoneState::DISABLED: return "Off";
    case ZoneState::LOCKED: return "Locked";
    case ZoneState::PAUSED: return "Paused";
    case ZoneState::SKIPPED: return "Skipped";
    default: return "Idle";
  }
}

/// Text colour of the state word: running green, queued blue, locked / paused amber, otherwise text-dim.
inline uint32_t card_state_color(const ZoneView &z) {
  switch (z.state) {
    case ZoneState::RUNNING: return color::GREEN;
    case ZoneState::QUEUED: return color::BLUE;
    case ZoneState::LOCKED:
    case ZoneState::PAUSED: return color::AMBER;
    default: return color::TEXT_DIM;
  }
}

/// Fill of the 3 px top edge of the card.
inline uint32_t card_edge_color(const ZoneView &z) {
  switch (z.state) {
    case ZoneState::RUNNING: return color::GREEN_FILL;
    case ZoneState::QUEUED: return color::BLUE_FILL;
    case ZoneState::LOCKED:
    case ZoneState::PAUSED: return color::AMBER_FILL;
    default: return color::BORDER;
  }
}

/// Running: "04:59" ("1:02:05" from one hour); otherwise the run duration "5 min"; no duration: "--".
inline std::string card_time(const ZoneView &z) {
  if ((z.state == ZoneState::RUNNING || z.state == ZoneState::PAUSED) && z.time_left.has_value()) {
    const uint32_t t = *z.time_left;
    char buf[16];
    if (t >= 3600U)
      std::snprintf(buf, sizeof(buf), "%u:%02u:%02u", static_cast<unsigned>(t / 3600U), static_cast<unsigned>((t % 3600U) / 60U),
                    static_cast<unsigned>(t % 60U));
    else
      std::snprintf(buf, sizeof(buf), "%02u:%02u", static_cast<unsigned>(t / 60U), static_cast<unsigned>(t % 60U));
    return buf;
  }
  if (z.run_duration == 0)
    return "--";
  return detail::duration_text(z.run_duration);
}

/// Progress of the current run in percent (0 when not running), 0..100.
inline int card_progress(const ZoneView &z) {
  if (!(z.state == ZoneState::RUNNING || z.state == ZoneState::PAUSED) || !z.time_left.has_value() || z.run_total == 0)
    return 0;
  const uint32_t left = *z.time_left > z.run_total ? z.run_total : *z.time_left;
  return static_cast<int>(((z.run_total - left) * 100ULL + z.run_total / 2U) / z.run_total);
}

/// "Soil 58%", or "" when the zone has no soil reading.
inline std::string card_soil(const std::optional<float> &soil) {
  if (!soil.has_value())
    return "";
  const float v = *soil;
  const unsigned pct = v <= 0.0f ? 0U : v >= 100.0f ? 100U : static_cast<unsigned>(v + 0.5f);
  char buf[16];
  std::snprintf(buf, sizeof(buf), "Soil %u%%", pct);
  return buf;
}

/// Last watering line of a card: "06:00 5m" (today), "12 Oct 5m", "--:-- 5m" (the clock was not valid when it ran), "-"
/// (never). `has_last` is false when the zone has no last watering.
inline std::string card_last(const Moment &when, const Moment &today, bool has_last, uint32_t duration) {
  if (!has_last)
    return "-";
  std::string out = !when.known ? "--:--" : when.same_day(today) ? detail::clock_text(when) : detail::date_text(when);
  return out + " " + detail::duration_short(duration);
}

}  // namespace esphome::gp::fmt
