// garden_schedule — pure texts and view hash for the screens (C++17, no ESPHome includes; unit tested on the host).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The schedule's own data is formatted here (not in components/gp), so `gp` never depends on the schedule and the other
// way round. All texts are printable ASCII (the built-in LVGL fonts have nothing else).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "schedule_core.h"

namespace esphome::garden_schedule {

/// What happened to a slot today (screen word).
enum class Today : uint8_t { NONE, RUNNING, DONE, MISSED, SKIPPED, STOPPED };

/// Everything a screen shows about one slot.
struct SlotView {
  uint8_t number{0};  ///< 1-based slot number (entity names)
  bool enabled{false};
  uint16_t start_minute{0};
  uint8_t days_mask{ALL_DAYS};
  uint32_t zone_mask{0};
  uint8_t pct{100};
  Today today{Today::NONE};
};

/// "Every day", "Mon-Fri", "Sat Sun", "Mon Wed Fri", "Never": runs of three or more days are ranges.
inline std::string days_text(uint8_t mask) {
  mask &= ALL_DAYS;
  if (mask == 0)
    return "Never";
  if (mask == ALL_DAYS)
    return "Every day";
  std::string out;
  uint8_t day = 0;
  while (day < 7) {
    if ((mask & (1u << day)) == 0) {
      day++;
      continue;
    }
    uint8_t last = day;
    while (last + 1 < 7 && (mask & (1u << (last + 1))) != 0)
      last++;
    if (!out.empty())
      out += ' ';
    out += weekday_name(day);
    if (last - day >= 2) {
      out += '-';
      out += weekday_name(last);
    } else if (last - day == 1) {
      out += ' ';
      out += weekday_name(last);
    }
    day = static_cast<uint8_t>(last + 1);
  }
  return out;
}

inline const char *today_word(Today t) {
  switch (t) {
    case Today::RUNNING:
      return "running";
    case Today::DONE:
      return "done";
    case Today::MISSED:
      return "missed";
    case Today::SKIPPED:
      return "skipped";
    case Today::STOPPED:
      return "stopped";
    default:
      return "";
  }
}

/// Home "next": "06:00" (today), "Tue 06:00" (another day), "--:--" (nothing ahead).
inline std::string next_short(bool has_next, int32_t day, uint16_t start_minute, int32_t today) {
  if (!has_next)
    return "--:--";
  if (day == today)
    return format_time(start_minute);
  return std::string(weekday_name(weekday_of(day))) + " " + format_time(start_minute);
}

// ---- change detection ----

/// FNV-1a over everything a schedule screen shows (never 0, so 0 can mean "not drawn yet"). `extra` is anything else the
/// texts depend on (the zone run durations of the list captions).
inline uint32_t view_hash(const std::vector<SlotView> &slots, bool master, const std::string &next, uint32_t extra = 0) {
  uint32_t h = 2166136261u;
  auto mix = [&h](uint32_t value) {
    for (int i = 0; i < 4; i++) {
      h ^= (value >> (8 * i)) & 0xFFu;
      h *= 16777619u;
    }
  };
  mix(master ? 1u : 0u);
  mix(extra);
  mix(static_cast<uint32_t>(slots.size()));
  for (const SlotView &v : slots) {
    mix(v.number);
    mix(v.enabled ? 1u : 0u);
    mix(v.start_minute);
    mix(v.days_mask);
    mix(v.zone_mask);
    mix(v.pct);
    mix(static_cast<uint32_t>(v.today));
  }
  for (char c : next)
    mix(static_cast<uint8_t>(c));
  return h == 0 ? 1u : h;
}

}  // namespace esphome::garden_schedule
