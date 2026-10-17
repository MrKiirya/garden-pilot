// garden_schedule — pure model of the on-device schedule screens (C++17, no ESPHome includes; unit tested on the host).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Two things live here: the editor DRAFT (a plain value edited in RAM by the Schedule N page; the entities are written
// only by SAVE, through `diff()`) and the texts of the Schedule list rows (design D08). The hub (garden_schedule.h)
// feeds it with the slot entities; the YAML calls the hub one-liners. All texts are printable ASCII (built-in LVGL fonts).
#pragma once

#include <cstdint>
#include <cstdio>
#include <functional>
#include <string>

#include "schedule_core.h"
#include "schedule_format.h"

namespace esphome::garden_schedule {

/// Widest texts the list rows are drawn for (180 px wide labels: label montserrat_12, caption montserrat_10).
inline constexpr size_t LABEL_MAX = 26;
inline constexpr size_t CAPTION_MAX = 30;

/// Tone colours of the status word, mirrored from design/tokens.json (`text`, `text-dim`, `green`, `amber`).
inline constexpr uint32_t TONE_TEXT = 0xe5e2e1;
inline constexpr uint32_t TONE_DIM = 0xbecab9;
inline constexpr uint32_t TONE_GREEN = 0x78dc77;
inline constexpr uint32_t TONE_AMBER = 0xffb870;

/// Which fields differ between a draft and the slot it was started from.
struct Diff {
  bool enabled{false};
  bool start{false};
  uint8_t days{0};  ///< bit n = day n changed
  bool zones{false};
  bool pct{false};
  bool any() const { return this->enabled || this->start || this->days != 0 || this->zones || this->pct; }
};

struct ScheduleDraft {
  uint8_t index{0};  ///< 0-based position in the hub (include order)
  bool enabled{false};
  uint8_t hour{0};
  uint8_t minute{0};
  uint8_t days_mask{ALL_DAYS};  ///< bit 0 = Monday
  uint32_t zone_mask{0};  ///< bit n = zone n (0-based); bits without a screen button are kept
  uint8_t pct{100};

  void hour_up() { this->hour = this->hour >= 23 ? 0 : static_cast<uint8_t>(this->hour + 1); }
  void hour_down() { this->hour = this->hour == 0 ? 23 : static_cast<uint8_t>(this->hour - 1); }
  /// Step 5; a minute that is not a multiple of 5 (set from Home Assistant) snaps to the next / previous multiple.
  void minute_up() {
    const unsigned next = (this->minute / 5u + 1u) * 5u;
    this->minute = next >= 60 ? 0 : static_cast<uint8_t>(next);
  }
  void minute_down() {
    if (this->minute % 5u != 0)
      this->minute = static_cast<uint8_t>(this->minute / 5u * 5u);
    else
      this->minute = this->minute == 0 ? 55 : static_cast<uint8_t>(this->minute - 5);
  }
  void toggle_day(uint8_t day) {
    if (day < 7)
      this->days_mask ^= static_cast<uint8_t>(1u << day);
  }
  void toggle_zone(size_t zone, size_t zone_count) {
    if (zone < zone_count && zone < 32)
      this->zone_mask ^= 1u << zone;
  }
  void pct_up() { this->pct = this->pct >= 190 ? 200 : static_cast<uint8_t>(this->pct + 10); }
  void pct_down() { this->pct = this->pct <= 20 ? 10 : static_cast<uint8_t>(this->pct - 10); }
  void toggle_enabled() { this->enabled = !this->enabled; }

  /// An enabled slot needs at least one day and one zone; a disabled one can always be saved.
  bool can_save() const { return !this->enabled || ((this->days_mask & ALL_DAYS) != 0 && this->zone_mask != 0); }

  /// Zone text entity value: "all", or the 1-based zones below `zone_count` ("1 3"); empty when none is selected.
  std::string zones_text(size_t zone_count) const {
    if (zone_count == 0 || zone_count > 32)
      return std::string();
    const uint32_t all = zone_count == 32 ? 0xFFFFFFFFu : ((1u << zone_count) - 1u);
    const uint32_t mask = this->zone_mask & all;
    if (mask == 0)
      return std::string();
    if (mask == all)
      return "all";
    std::string out;
    for (size_t i = 0; i < zone_count; i++) {
      if ((mask >> i) & 1u) {
        if (!out.empty())
          out += ' ';
        out += std::to_string(i + 1);
      }
    }
    return out;
  }
  /// "x1.0" (tenths of the run time factor).
  std::string factor_text() const {
    const unsigned tenths = (static_cast<unsigned>(this->pct) + 5u) / 10u;
    return "x" + std::to_string(tenths / 10u) + "." + std::to_string(tenths % 10u);
  }
  std::string hour_text() const { return two_digits_(this->hour); }
  std::string minute_text() const { return two_digits_(this->minute); }

  Diff diff(const ScheduleDraft &original) const {
    Diff d;
    d.enabled = this->enabled != original.enabled;
    d.start = this->hour != original.hour || this->minute != original.minute;
    d.days = static_cast<uint8_t>((this->days_mask ^ original.days_mask) & ALL_DAYS);
    d.zones = this->zone_mask != original.zone_mask;
    d.pct = this->pct != original.pct;
    return d;
  }

 protected:
  static std::string two_digits_(unsigned v) {
    char buf[4];
    std::snprintf(buf, sizeof(buf), "%02u", v % 100u);
    return buf;
  }
};

// ------------------------------------------------------------------------------------------------ list rows (D08)

/// "06:00", or "--:--" for a slot that is off.
inline std::string row_time(bool enabled, uint16_t start_minute) { return enabled ? format_time(start_minute) : "--:--"; }

/// "Greenhouse - all beds", "- bed 2", "- beds 1 3", "- 4 beds" (more than three of not all), "- no beds".
inline std::string zones_label(const std::string &group, const std::string &noun, uint32_t mask, size_t zone_count) {
  const uint32_t all = zone_count >= 32 ? 0xFFFFFFFFu : ((1u << zone_count) - 1u);
  mask &= all;
  size_t count = 0;
  for (size_t i = 0; i < 32; i++)
    count += (mask >> i) & 1u;
  if (count == 0)
    return group + " - no " + noun + "s";
  if (mask == all && zone_count > 1)
    return group + " - all " + noun + "s";
  if (count > 3)
    return group + " - " + std::to_string(count) + " " + noun + "s";
  std::string list;
  for (size_t i = 0; i < 32; i++) {
    if ((mask >> i) & 1u) {
      if (!list.empty())
        list += ' ';
      list += std::to_string(i + 1);
    }
  }
  return group + " - " + noun + (count > 1 ? "s " : " ") + list;
}

/// "45 s", "5 min": seconds below a minute, else whole minutes (rounded).
inline std::string duration_part(uint32_t seconds) {
  if (seconds < 60)
    return std::to_string(seconds) + " s";
  return std::to_string((seconds + 30u) / 60u) + " min";
}

/// Run time of the selected zones at the slot's factor: "5 min" (one zone), "5 min each" (equal zones), "12 min total".
/// `zone_seconds(z)` is the zone's configured run duration (0-based zone).
inline std::string duration_text(uint32_t mask, size_t zone_count, const std::function<uint32_t(size_t)> &zone_seconds,
                                 uint8_t pct) {
  if (!zone_seconds)  // an empty std::function would throw (abort on ESP32)
    return std::string();
  size_t count = 0;
  uint64_t total = 0;
  uint32_t first = 0;
  bool equal = true;
  for (size_t z = 0; z < zone_count && z < 32; z++) {
    if (((mask >> z) & 1u) == 0)
      continue;
    const uint32_t s = static_cast<uint32_t>((static_cast<uint64_t>(zone_seconds(z)) * pct + 50u) / 100u);
    if (count == 0)
      first = s;
    else if (s != first)
      equal = false;
    total += s;
    count++;
  }
  if (count == 0)
    return std::string();
  if (count == 1)
    return duration_part(first);
  if (equal)
    return duration_part(first) + " each";
  return duration_part(static_cast<uint32_t>(total)) + " total";
}

/// Second line of a row: "Every day - 5 min each". Past CAPTION_MAX the days become a count ("5 days").
inline std::string row_caption(bool enabled, uint8_t days_mask, const std::string &duration) {
  if (!enabled)
    return "Not set - tap to set up";
  std::string days = days_text(days_mask);
  std::string out = days + " - " + duration;
  if (out.size() > CAPTION_MAX) {
    unsigned n = 0;
    for (unsigned d = 0; d < 7; d++)
      n += (days_mask >> d) & 1u;
    out = std::to_string(n) + (n == 1 ? " day" : " days") + " - " + duration;
  }
  return out;
}

/// Value of "no countdown" (an OFF slot): drawn as "-".
inline constexpr int64_t NO_COUNTDOWN = INT64_MIN;

/// "in 2d 6h", "in 3h 28m", "in 45m" (whole units, rounded down, at least "in 1m"); "-" for NO_COUNTDOWN, empty when
/// negative.
inline std::string countdown_text(int64_t seconds) {
  if (seconds == NO_COUNTDOWN)
    return "-";
  if (seconds < 0)
    return std::string();
  const int64_t minutes = seconds / 60;
  const int64_t hours = minutes / 60;
  if (hours >= 24)
    return "in " + std::to_string(hours / 24) + "d " + std::to_string(hours % 24) + "h";
  if (hours >= 1)
    return "in " + std::to_string(hours) + "h " + std::to_string(minutes % 60) + "m";
  return "in " + std::to_string(minutes < 1 ? 1 : minutes) + "m";
}

struct StatusWord {
  std::string text;
  uint32_t color{TONE_DIM};
};

/// The coloured word at the right of a row (LATER: enabled, neither next nor done today). `today` is the slot's state on the current local day.
inline StatusWord status_word(bool enabled, bool master_on, DayRunState today, bool pending, bool is_next) {
  if (!enabled || !master_on)
    return {"OFF", TONE_DIM};
  switch (today) {
    case DayRunState::FIRED:
      return pending ? StatusWord{"ACTIVE", TONE_GREEN} : StatusWord{"DONE", TONE_DIM};
    case DayRunState::SKIPPED:
    case DayRunState::MISSED:
    case DayRunState::STOPPED:
      return {"SKIP", TONE_AMBER};
    default:
      break;
  }
  if (is_next)
    return {"NEXT", TONE_GREEN};
  return {"LATER", TONE_TEXT};
}

}  // namespace esphome::garden_schedule
