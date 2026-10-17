// gp — History page texts (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Kept apart from format.h (the debug / status formatters) so the History page owns its own file. Same rules: printable
// ASCII only (built-in LVGL fonts). The glue (gp.h) converts the epoch to local time and passes the broken-down time in;
// this file knows nothing about time zones. One row of the page = five cells (history_cells), one colour tone each.
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <optional>
#include <string>

#include "format.h"
#include "history.h"
#include "zone_model.h"

namespace esphome::gp::fmt {

/// Rows of one History page (design D20); the page creates exactly this many label rows.
inline constexpr size_t HISTORY_ROWS = 8;
inline constexpr size_t HISTORY_COLS = 5;  ///< DATE, TIME, ZONE, TIME ON, SOURCE

/// The local date and time of an entry; `valid` = false when the clock was not valid or the epoch is 0.
struct LocalTime {
  bool valid{false};
  uint8_t day{0};     ///< 1-31
  uint8_t month{0};   ///< 1-12
  uint8_t hour{0};    ///< 0-23
  uint8_t minute{0};  ///< 0-59
};

/// Colour roles of a cell; the page maps them to the design tokens text / text-dim / green / amber.
enum class Tone : uint8_t { TEXT = 0, DIM = 1, GREEN = 2, AMBER = 3 };

struct HistoryCells {
  std::string text[HISTORY_COLS];
  Tone tone[HISTORY_COLS]{Tone::TEXT, Tone::TEXT, Tone::TEXT, Tone::TEXT, Tone::TEXT};
};

/// "45 s" below one minute, otherwise whole minutes floored: "5 min". Five seconds of tolerance: the valve-open time is
/// sampled every 250 ms, so a 5 minute run can be measured as 4 min 59 s and must still read "5 min".
inline std::string duration_text(uint32_t seconds) {
  char buf[24];
  if (seconds < 60U)
    std::snprintf(buf, sizeof(buf), "%u s", static_cast<unsigned>(seconds));
  else  // capped at 99: the column is 9 characters wide ("99 min..."), a run is never that long (60 min watchdog)
    std::snprintf(buf, sizeof(buf), "%u min", static_cast<unsigned>(std::min<uint32_t>((seconds + 5U) / 60U, 99U)));
  return buf;
}

/// Source column words: manual, HA, schedule, queue, test (a service / valve-test run), "-" when unknown.
inline const char *history_source_word(uint8_t source) {
  switch (static_cast<Source>(source)) {
    case Source::MANUAL: return "manual";
    case Source::QUEUE: return "queue";
    case Source::SERVICE: return "test";
    case Source::SCHEDULE: return "schedule";
    case Source::HA: return "HA";
    default: return "-";
  }
}

/// The ZONE cell: the zone's name when it fits the 62 px column (8 characters), otherwise the name without its leading
/// words ("Greenhouse bed 1" -> "Bed 1", "Front flower border" -> "Border"), first letter upper case; "B<n>" when the
/// name is empty or no tail fits.
inline std::string history_zone_label(const char *name, uint8_t zone) {
  constexpr size_t MAX_LEN = 8;
  std::string text = name != nullptr ? name : "";
  while (text.size() > MAX_LEN) {
    const size_t space = text.find(' ');
    if (space == std::string::npos)
      break;
    text = text.substr(space + 1);
  }
  if (text.empty() || text.size() > MAX_LEN) {
    char buf[8];
    std::snprintf(buf, sizeof(buf), "B%u", static_cast<unsigned>(zone) + 1U);
    return buf;
  }
  if (text[0] >= 'a' && text[0] <= 'z')
    text[0] = static_cast<char>(text[0] - 'a' + 'A');
  return text;
}

/// The five cells of one row.`live_s` = the valve-open seconds of the zone while the model says its run is open (an
/// OPEN entry without it is drawn like a finished one with its planned time). `zone_name` null / empty = "B<n>".
inline HistoryCells history_cells(const HistoryEntry &entry, const LocalTime &when, std::optional<uint32_t> live_s,
                                  const char *zone_name) {
  HistoryCells c;
  char buf[24];
  if (entry.epoch == 0 || !when.valid) {
    c.text[0] = "--.--";
    c.text[1] = "--:--";
  } else {
    std::snprintf(buf, sizeof(buf), "%02u.%02u", static_cast<unsigned>(when.day), static_cast<unsigned>(when.month));
    c.text[0] = buf;
    std::snprintf(buf, sizeof(buf), "%02u:%02u", static_cast<unsigned>(when.hour), static_cast<unsigned>(when.minute));
    c.text[1] = buf;
  }
  c.text[2] = history_zone_label(zone_name, entry.zone);
  c.text[4] = history_source_word(entry.source);
  c.tone[0] = Tone::DIM;
  c.tone[4] = Tone::DIM;

  const Result result = result_of(entry);
  if (result == Result::SKIPPED_WET || result == Result::SKIPPED) {
    c.text[3] = "skipped";
    if (result == Result::SKIPPED_WET) {
      if (entry.detail == DETAIL_UNKNOWN) {
        c.text[4] = "too wet";
      } else {
        std::snprintf(buf, sizeof(buf), "soil > %u%%", static_cast<unsigned>(entry.detail));
        c.text[4] = buf;
      }
    } else {
      c.text[4] = "no sensor";
    }
    c.tone[1] = c.tone[2] = c.tone[3] = Tone::DIM;
    return c;
  }
  if (result == Result::OPEN && live_s.has_value()) {
    c.text[3] = duration_text(*live_s) + "...";
    c.tone[1] = c.tone[2] = c.tone[3] = Tone::GREEN;
    return c;
  }
  if (result == Result::INTERRUPTED) {
    c.text[3] = entry.duration == 0 ? std::string("?") : "<" + duration_text(entry.duration);
    c.tone[3] = Tone::AMBER;
    return c;
  }
  c.text[3] = duration_text(entry.duration);  // done, an old entry, or an OPEN entry whose run is not live any more
  if (result == Result::STOPPED)
    c.tone[3] = Tone::AMBER;
  return c;
}

/// Number of pages for `total` entries (at least 1).
inline size_t history_page_count(size_t total, size_t per_page = HISTORY_ROWS) {
  return total == 0 ? 1 : (total + per_page - 1) / per_page;
}

/// `page` limited to 0..last page (a negative page, from NEWER on the first page, becomes 0).
inline int history_clamp_page(size_t total, int page, size_t per_page = HISTORY_ROWS) {
  if (page < 0)
    return 0;
  const size_t last = history_page_count(total, per_page) - 1;
  return static_cast<size_t>(page) > last ? static_cast<int>(last) : page;
}

/// Page title: "History - 1/13", or "History" when there is nothing to page.
inline std::string history_title(size_t total, int page, size_t per_page = HISTORY_ROWS) {
  if (total == 0)
    return "History";
  char buf[32];
  std::snprintf(buf, sizeof(buf), "History - %u/%u", static_cast<unsigned>(history_clamp_page(total, page, per_page)) + 1U,
                static_cast<unsigned>(history_page_count(total, per_page)));
  return buf;
}

}  // namespace esphome::gp::fmt
