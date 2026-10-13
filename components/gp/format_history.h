// gp — history page texts (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Kept apart from format.h (the debug / status formatters) so the History page owns its own file. Same rules: printable
// ASCII only (built-in LVGL fonts), shorter than LABEL_MAX. The glue (gp.h) converts the epoch to local time and passes
// the broken-down time in; this file knows nothing about time zones.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>

#include "format.h"
#include "history.h"
#include "zone_model.h"

namespace esphome::gp::fmt {

/// Rows of one History page (the page never creates more widgets than this).
inline constexpr size_t HISTORY_ROWS = 6;

/// The local date and time of an entry; `valid` = false when the clock was not valid or the epoch is 0.
struct LocalTime {
  bool valid{false};
  uint8_t day{0};     ///< 1-31
  uint8_t month{0};   ///< 1-12
  uint8_t hour{0};    ///< 0-23
  uint8_t minute{0};  ///< 0-59
};

/// "done" / "stopped" / "skipped wet" / "skipped" / "-"; a service (valve test) run reads "test".
inline const char *result_word(const HistoryEntry &entry) {
  if (entry.source == static_cast<uint8_t>(Source::SERVICE))
    return "test";
  switch (result_of(entry)) {
    case Result::DONE: return "done";
    case Result::STOPPED: return "stopped";
    case Result::SKIPPED_WET: return "skipped wet";
    case Result::SKIPPED: return "skipped";
    default: return "-";
  }
}

/// "45 s" below one minute, otherwise whole minutes: "5 min".
inline std::string duration_text(uint32_t seconds) {
  char buf[24];
  if (seconds < 60U)
    std::snprintf(buf, sizeof(buf), "%u s", static_cast<unsigned>(seconds));
  else
    std::snprintf(buf, sizeof(buf), "%u min", static_cast<unsigned>((seconds + 30U) / 60U));
  return buf;
}

/// "13 Oct 06:00", or "--:--" when the start time is unknown.
inline std::string date_time_text(uint32_t epoch, const LocalTime &when) {
  static const char *const MONTHS[12] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  if (epoch == 0 || !when.valid || when.month < 1 || when.month > 12)
    return "--:--";
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%u %s %02u:%02u", static_cast<unsigned>(when.day), MONTHS[when.month - 1],
                static_cast<unsigned>(when.hour), static_cast<unsigned>(when.minute));
  return buf;
}

/// "B2  13 Oct 06:00  5 min  done" / "B2  13 Oct 06:00  skipped wet" (a skip has no duration).
inline std::string history_row(const HistoryEntry &entry, const LocalTime &when) {
  const Result result = result_of(entry);
  const bool skip = result == Result::SKIPPED_WET || result == Result::SKIPPED;
  char head[16];
  std::snprintf(head, sizeof(head), "B%u  ", static_cast<unsigned>(entry.zone) + 1U);
  std::string out = head + date_time_text(entry.epoch, when) + "  ";
  if (!skip)
    out += duration_text(entry.duration) + "  ";
  return out + result_word(entry);
}

/// Number of pages for `total` entries (at least 1).
inline size_t history_page_count(size_t total, size_t per_page = HISTORY_ROWS) {
  return total == 0 ? 1 : (total + per_page - 1) / per_page;
}

/// `page` limited to 0..last page (a negative page, from PREV on the first page, becomes 0).
inline int history_clamp_page(size_t total, int page, size_t per_page = HISTORY_ROWS) {
  if (page < 0)
    return 0;
  const size_t last = history_page_count(total, per_page) - 1;
  return static_cast<size_t>(page) > last ? static_cast<int>(last) : page;
}

/// "1-6 of 37" / "37-37 of 37" / "No watering yet".
inline std::string history_pager(size_t total, int page, size_t per_page = HISTORY_ROWS) {
  if (total == 0)
    return "No watering yet";
  const size_t p = static_cast<size_t>(history_clamp_page(total, page, per_page));
  const size_t first = p * per_page + 1;
  const size_t last = (p + 1) * per_page < total ? (p + 1) * per_page : total;
  char buf[40];
  std::snprintf(buf, sizeof(buf), "%u-%u of %u", static_cast<unsigned>(first), static_cast<unsigned>(last),
                static_cast<unsigned>(total));
  return buf;
}

}  // namespace esphome::gp::fmt
