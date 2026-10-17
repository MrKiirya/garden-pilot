// garden_schedule — the pure schedule core (C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Decides which schedule slots are due, from a stream of clock ticks. Rules (see components/garden_schedule/README.md):
//  * An invalid clock fires nothing and marks nothing.
//  * A tick is "continuous" when the clock advanced like the monotonic timer (+-5 s). On a continuous tick every
//    enabled slot whose start was crossed in LOCAL time fires once per local day (DST safe: the day mark blocks the
//    repeated hour of a fall-back, the skipped hour of a spring-forward is crossed in one step).
//  * The first valid tick and every tick after a clock jump are "discontinuous": nothing fires by crossing. Slots of
//    today whose start has passed are caught up (inside the catch-up window) or recorded as missed.
//  * The run mark is keyed by (local day, start minute): a slot is "handled today" only while its start is the one it
//    ran with. Moving a slot to a later time runs it again the same day (also after a STOP); saving the same start again
//    never does. ANY_MINUTE (marks migrated from before the minute was stored) matches every start.
//  * The "done" mark is per zone: a fired slot keeps a pending zone mask; a zone leaves it when its watering
//    completes. After a restart inside the window only the pending zones run again. A user STOP settles the slot
//    (`stop_pending`): the pending zones are dropped and nothing resumes.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string>
#include <vector>

namespace esphome::garden_schedule {

inline constexpr size_t MAX_SLOTS = 8;
inline constexpr int32_t NEVER = INT32_MIN;
inline constexpr int64_t CONTINUOUS_TOLERANCE_MS = 5000;
inline constexpr uint8_t ALL_DAYS = 0x7F;
/// Start minute of a run mark that predates the minute (migrated v1 marks): it matches whatever the start is now.
inline constexpr uint16_t ANY_MINUTE = 0xFFFF;

// ------------------------------------------------------------------------------------------------ calendar

/// Days since 1970-01-01 of a civil date (proleptic Gregorian).
inline int32_t days_from_civil(int y, unsigned m, unsigned d) {
  y -= m <= 2 ? 1 : 0;
  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int32_t>(doe) - 719468;
}

inline void civil_from_days(int32_t z, int &y, unsigned &m, unsigned &d) {
  z += 719468;
  const int era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = static_cast<unsigned>(z - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  y = static_cast<int>(yoe) + era * 400;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  d = doy - (153 * mp + 2) / 5 + 1;
  m = mp < 10 ? mp + 3 : mp - 9;
  if (m <= 2)
    y++;
}

/// 0 = Monday ... 6 = Sunday (1970-01-01 was a Thursday).
inline uint8_t weekday_of(int32_t day) {
  int32_t w = (day + 3) % 7;
  if (w < 0)
    w += 7;
  return static_cast<uint8_t>(w);
}

inline const char *weekday_name(uint8_t weekday) {
  static const char *const NAMES[7] = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"};
  return NAMES[weekday % 7];
}

struct LocalTime {
  int32_t day{0};  ///< local day number (days_from_civil of the local date)
  uint16_t minute{0};  ///< minute of the local day
  uint8_t second{0};
  int64_t linear() const { return static_cast<int64_t>(day) * 86400 + minute * 60 + second; }
};

/// One reading of the clock. `epoch` is UTC seconds, `mono_ms` the monotonic millisecond counter (wraps at 2^32).
struct Tick {
  bool valid{false};
  int64_t epoch{0};
  uint32_t mono_ms{0};
  LocalTime local;
};

// ------------------------------------------------------------------------------------------------ parsing / text

/// Zone list of a slot: "all" or 1-based zone numbers separated by spaces ("1 3"). Numbers outside 1..zone_count are
/// dropped (`*dropped` is set so the caller can warn). Garbage, an empty text or a result without zones: nullopt.
inline std::optional<uint32_t> parse_zones(const std::string &text, size_t zone_count, bool *dropped = nullptr) {
  if (dropped != nullptr)
    *dropped = false;
  if (zone_count == 0 || zone_count > 32)
    return std::nullopt;
  const uint32_t all = zone_count == 32 ? 0xFFFFFFFFu : ((1u << zone_count) - 1u);
  uint32_t mask = 0;
  size_t i = 0;
  bool any = false;
  while (i < text.size()) {
    if (text[i] == ' ') {
      i++;
      continue;
    }
    size_t j = i;
    while (j < text.size() && text[j] != ' ')
      j++;
    const std::string token = text.substr(i, j - i);
    i = j;
    any = true;
    if (token == "all") {
      mask |= all;
      continue;
    }
    if (token.size() > 2)
      return std::nullopt;
    unsigned value = 0;
    for (char c : token) {
      if (c < '0' || c > '9')
        return std::nullopt;
      value = value * 10 + static_cast<unsigned>(c - '0');
    }
    if (value == 0 || value > zone_count) {
      if (dropped != nullptr)
        *dropped = true;
      continue;
    }
    mask |= 1u << (value - 1);
  }
  if (!any || mask == 0)
    return std::nullopt;
  return mask;
}

inline std::string format_time(uint16_t minute) {
  char buf[8];
  std::snprintf(buf, sizeof(buf), "%02u:%02u", static_cast<unsigned>(minute / 60 % 24), static_cast<unsigned>(minute % 60));
  return buf;
}

/// ISO 8601 local time with offset: "2026-10-11T06:00:00+02:00".
inline std::string format_iso(int32_t day, uint16_t minute, int32_t offset_s) {
  int y = 0;
  unsigned m = 0, d = 0;
  civil_from_days(day, y, m, d);
  const char sign = offset_s < 0 ? '-' : '+';
  const int32_t off = offset_s < 0 ? -offset_s : offset_s;
  char buf[40];
  std::snprintf(buf, sizeof(buf), "%04d-%02u-%02uT%02u:%02u:00%c%02d:%02d", y, m, d, static_cast<unsigned>(minute / 60 % 24),
                static_cast<unsigned>(minute % 60), sign, off / 3600, off % 3600 / 60);
  return buf;
}

// ------------------------------------------------------------------------------------------------ scheduler

struct SlotConfig {
  bool enabled{false};
  uint16_t start_minute{0};
  uint8_t days_mask{ALL_DAYS};  ///< bit 0 = Monday
  uint32_t zone_mask{0};  ///< bit n = zone n (0-based)
  uint8_t pct{100};
};

enum class Result : uint8_t { NONE, RAN, CATCH_UP, MISSED, SKIPPED, STOPPED };

struct SlotState {
  int32_t last_fired_day{NEVER};  ///< local day number of the last fire / miss / skip (persisted)
  uint16_t last_fired_minute{ANY_MINUTE};  ///< the slot's start minute at that fire (persisted)
  uint32_t pending{0};  ///< zones of the fired run that did not complete yet (persisted)
  Result result{Result::NONE};  ///< not persisted
};

struct Fire {
  uint8_t slot{0};
  uint32_t zone_mask{0};
  uint8_t pct{100};
  bool catch_up{false};
};

struct Missed {
  uint8_t slot{0};
  uint32_t minutes_late{0};
  uint32_t zone_mask{0};
};

struct Events {
  std::vector<Fire> fires;
  std::vector<Missed> missed;
  std::vector<uint8_t> dropped;  ///< slots whose pending zones were dropped because their start changed meanwhile
  bool state_changed{false};  ///< a persisted field changed: save the state
  bool future_cleared{false};  ///< a day mark from the future was cleared (warn)
  bool clock_became_valid{false};
};

struct NextRun {
  uint8_t slot{0};
  int32_t day{0};
  uint16_t start_minute{0};
};

enum class DayRunState : uint8_t { PENDING, FIRED, MISSED, SKIPPED, STOPPED };

struct DayRun {
  uint8_t slot{0};
  uint16_t start_minute{0};
  DayRunState state{DayRunState::PENDING};
};

/// Slot run-time percentage times the global factor, clamped to 10..200.
inline uint8_t effective_pct(uint8_t slot_pct, uint8_t global_pct) {
  int v = (static_cast<int>(slot_pct) * static_cast<int>(global_pct) + 50) / 100;
  if (v < 10)
    v = 10;
  if (v > 200)
    v = 200;
  return static_cast<uint8_t>(v);
}

class Scheduler {
 public:
  void set_catch_up_minutes(uint32_t minutes) { this->catch_up_s_ = static_cast<int64_t>(minutes) * 60; }
  void set_master(bool on) { this->master_ = on; }
  bool master() const { return this->master_; }
  void set_global_pct(uint8_t pct) { this->global_pct_ = pct; }
  uint8_t global_pct() const { return this->global_pct_; }

  const SlotState &state(size_t slot) const { return this->states_[slot]; }
  void restore(size_t slot, int32_t last_fired_day, uint16_t last_fired_minute, uint32_t pending) {
    this->states_[slot].last_fired_day = last_fired_day;
    this->states_[slot].last_fired_minute = last_fired_minute;
    this->states_[slot].pending = pending;
  }
  bool clock_valid() const { return this->have_prev_; }
  /// Local day number of the last valid tick (0 before the first one).
  int32_t today() const { return this->prev_.local.day; }

  /// Evaluates one clock reading against the slot configuration (slot index = position in `cfg`).
  void tick(const Tick &t, const SlotConfig *cfg, size_t n, Events &out) {
    if (n > MAX_SLOTS)
      n = MAX_SLOTS;
    if (!t.valid) {
      this->have_prev_ = false;
      return;
    }
    const bool first = !this->have_prev_;
    bool continuous = false;
    if (!first) {
      const int64_t dmono = static_cast<int64_t>(static_cast<uint32_t>(t.mono_ms - this->prev_.mono_ms));
      const int64_t depoch = (t.epoch - this->prev_.epoch) * 1000;
      continuous = std::llabs(depoch - dmono) <= CONTINUOUS_TOLERANCE_MS;
    }
    if (first)
      out.clock_became_valid = true;
    const int32_t today = t.local.day;

    // marks from the future (the clock was wrong when they were written) and stale pending zones of earlier days
    if (!continuous) {
      for (size_t i = 0; i < MAX_SLOTS; i++) {
        SlotState &st = this->states_[i];
        if (st.last_fired_day != NEVER && st.last_fired_day > today + 1) {
          st.last_fired_day = NEVER;
          st.last_fired_minute = ANY_MINUTE;
          st.pending = 0;
          out.future_cleared = true;
          out.state_changed = true;
        }
        if (st.pending != 0 && st.last_fired_day != today) {
          st.pending = 0;
          out.state_changed = true;
        }
      }
    }

    const bool resume = !this->resumed_;
    if (this->master_) {
      if (continuous)
        this->crossing_(t, cfg, n, out);
      else
        this->catch_up_(t, cfg, n, resume, out);
    }
    this->resumed_ = true;
    this->prev_ = t;
    this->have_prev_ = true;
  }

  /// A zone's watering completed: it leaves every pending mask. Returns true when a persisted field changed.
  bool zone_done(size_t zone) {
    bool changed = false;
    for (SlotState &st : this->states_) {
      if (st.pending & (1u << zone)) {
        st.pending &= ~(1u << zone);
        changed = true;
      }
    }
    return changed;
  }

  /// The wrapper decided not to run a fired slot (rain delay, service mode): nothing is left to run.
  void mark_skipped(size_t slot) {
    this->states_[slot].pending = 0;
    this->states_[slot].result = Result::SKIPPED;
  }

  /// A user STOP (or entering service mode) settles today's slots: every slot that still has pending zones loses
  /// them (result "stopped"), so nothing resumes after a restart. The day mark stays, so the slot does not run
  /// again today. Returns the slot indexes that were settled (empty = nothing to do; persist when not empty).
  std::vector<uint8_t> stop_pending() {
    std::vector<uint8_t> stopped;
    for (size_t i = 0; i < MAX_SLOTS; i++) {
      SlotState &st = this->states_[i];
      if (st.pending == 0)
        continue;
      st.pending = 0;
      st.result = Result::STOPPED;
      stopped.push_back(static_cast<uint8_t>(i));
    }
    return stopped;
  }

  /// The earliest run that is still ahead, over the next 8 local days.
  std::optional<NextRun> next_run(const SlotConfig *cfg, size_t n) const {
    if (!this->have_prev_ || !this->master_)
      return std::nullopt;
    if (n > MAX_SLOTS)
      n = MAX_SLOTS;
    const LocalTime &now = this->prev_.local;
    std::optional<NextRun> best;
    for (int offset = 0; offset < 8; offset++) {
      const int32_t day = now.day + offset;
      for (size_t i = 0; i < n; i++) {
        if (!runs_on_(cfg[i], day))
          continue;
        if (this->handled_(i, cfg[i], day))
          continue;
        if (offset == 0 && cfg[i].start_minute * 60 <= now.minute * 60 + now.second)
          continue;
        if (!best.has_value() || cfg[i].start_minute < best->start_minute)
          best = NextRun{static_cast<uint8_t>(i), day, cfg[i].start_minute};
      }
      if (best.has_value())
        return best;
    }
    return best;
  }

  /// The slots that run on the local day `now + offset`, sorted by start time, with their state.
  std::vector<DayRun> day_runs(int offset, const SlotConfig *cfg, size_t n) const {
    std::vector<DayRun> out;
    if (!this->have_prev_ || !this->master_)
      return out;
    if (n > MAX_SLOTS)
      n = MAX_SLOTS;
    const int32_t day = this->prev_.local.day + offset;
    for (size_t i = 0; i < n; i++) {
      if (!runs_on_(cfg[i], day))
        continue;
      DayRun run;
      run.slot = static_cast<uint8_t>(i);
      run.start_minute = cfg[i].start_minute;
      const SlotState &st = this->states_[i];
      if (this->handled_(i, cfg[i], day)) {
        run.state = st.result == Result::MISSED ? DayRunState::MISSED
                    : st.result == Result::SKIPPED ? DayRunState::SKIPPED
                    : st.result == Result::STOPPED ? DayRunState::STOPPED
                                                   : DayRunState::FIRED;
      }
      size_t at = out.size();
      while (at > 0 && out[at - 1].start_minute > run.start_minute)
        at--;
      out.insert(out.begin() + static_cast<std::ptrdiff_t>(at), run);
    }
    return out;
  }

 protected:
  static bool runs_on_(const SlotConfig &c, int32_t day) {
    return c.enabled && c.zone_mask != 0 && (c.days_mask & (1u << weekday_of(day))) != 0;
  }

  /// True when slot `i` already ran (or was missed / skipped) on `day` with its current start.
  bool handled_(size_t i, const SlotConfig &c, int32_t day) const {
    const SlotState &st = this->states_[i];
    return st.last_fired_day == day && (st.last_fired_minute == c.start_minute || st.last_fired_minute == ANY_MINUTE);
  }

  void fire_(size_t i, const SlotConfig &c, int32_t day, bool catch_up, uint32_t mask, Events &out) {
    SlotState &st = this->states_[i];
    st.last_fired_day = day;
    st.last_fired_minute = c.start_minute;
    st.pending = mask;
    st.result = catch_up ? Result::CATCH_UP : Result::RAN;
    out.fires.push_back(Fire{static_cast<uint8_t>(i), mask, effective_pct(c.pct, this->global_pct_), catch_up});
    out.state_changed = true;
  }

  void crossing_(const Tick &t, const SlotConfig *cfg, size_t n, Events &out) {
    const int64_t before = this->prev_.local.linear();
    const int64_t after = t.local.linear();
    int32_t last_day = t.local.day;
    if (last_day > this->prev_.local.day + 2)
      last_day = this->prev_.local.day + 2;
    for (int32_t day = this->prev_.local.day; day <= last_day; day++) {
      for (size_t i = 0; i < n; i++) {
        if (!runs_on_(cfg[i], day) || this->handled_(i, cfg[i], day))
          continue;
        const int64_t start = static_cast<int64_t>(day) * 86400 + cfg[i].start_minute * 60;
        if (before < start && start <= after)
          this->fire_(i, cfg[i], day, false, cfg[i].zone_mask, out);
      }
    }
  }

  void catch_up_(const Tick &t, const SlotConfig *cfg, size_t n, bool resume, Events &out) {
    const int32_t today = t.local.day;
    const int64_t now_s = t.local.minute * 60 + t.local.second;
    for (size_t i = 0; i < n; i++) {
      if (!runs_on_(cfg[i], today))
        continue;
      SlotState &st = this->states_[i];
      // zones still pending from a run with another start (the start was moved while the device was off) are dropped
      if (resume && st.last_fired_day == today && st.pending != 0 && !this->handled_(i, cfg[i], today)) {
        st.pending = 0;
        out.dropped.push_back(static_cast<uint8_t>(i));
        out.state_changed = true;
      }
      const int64_t start_s = cfg[i].start_minute * 60;
      if (start_s > now_s)
        continue;
      const int64_t late = now_s - start_s;
      const uint32_t late_min = static_cast<uint32_t>(late / 60);
      if (this->handled_(i, cfg[i], today)) {
        // Pending zones resume only on the first valid tick after boot; a later clock jump never re-fires or
        // "misses" a slot that was already handled (it may still be running).
        if (!resume || st.pending == 0)
          continue;
        if (late <= this->catch_up_s_) {
          st.result = Result::CATCH_UP;
          out.fires.push_back(Fire{static_cast<uint8_t>(i), st.pending, effective_pct(cfg[i].pct, this->global_pct_), true});
        } else {
          out.missed.push_back(Missed{static_cast<uint8_t>(i), late_min, st.pending});
          st.pending = 0;
          st.result = Result::MISSED;
          out.state_changed = true;
        }
        continue;
      }
      if (late <= this->catch_up_s_) {
        this->fire_(i, cfg[i], today, true, cfg[i].zone_mask, out);
      } else {
        out.missed.push_back(Missed{static_cast<uint8_t>(i), late_min, cfg[i].zone_mask});
        st.last_fired_day = today;
        st.last_fired_minute = cfg[i].start_minute;
        st.pending = 0;
        st.result = Result::MISSED;
        out.state_changed = true;
      }
    }
  }

  SlotState states_[MAX_SLOTS];
  Tick prev_;
  bool have_prev_{false};
  bool resumed_{false};  ///< the first valid tick after boot has been seen (pending zones resume only then)
  bool master_{true};
  int64_t catch_up_s_{3600};
  uint8_t global_pct_{100};
};

}  // namespace esphome::garden_schedule
