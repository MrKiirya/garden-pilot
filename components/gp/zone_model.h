// gp — per-zone read model and group summary (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The glue (gp.h) fills a GroupInput from the engine adapter every few hundred milliseconds; GroupModel turns it into
// the contract of components/gp/README.md: one ZoneView per zone index, a GroupSummary with a revision counter, the
// bookkeeping of the last watering (start, duration, source) and the completed-run records for the history.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <optional>

#include "history.h"

namespace esphome::gp {

/// A skip record stays visible this long (or until the zone runs / is queued again).
inline constexpr uint32_t SKIP_VISIBLE_MS = 12UL * 3600UL * 1000UL;
inline constexpr size_t SKIP_TEXT_LEN = 48;

/// Declaration order is not the precedence: see resolve_state().
enum class ZoneState : uint8_t { IDLE, SKIPPED, QUEUED, DISABLED, PAUSED, RUNNING, LOCKED };

/// Where a run came from (stored in the history).
enum class Source : uint8_t { UNKNOWN = 0, MANUAL = 1, QUEUE = 2, SERVICE = 3 };

inline const char *state_word(ZoneState state) {
  switch (state) {
    case ZoneState::IDLE: return "IDLE";
    case ZoneState::SKIPPED: return "SKIPPED";
    case ZoneState::QUEUED: return "QUEUED";
    case ZoneState::DISABLED: return "OFF";
    case ZoneState::PAUSED: return "PAUSED";
    case ZoneState::RUNNING: return "RUN";
    case ZoneState::LOCKED: return "LOCKED";
  }
  return "?";
}

inline const char *source_word(Source source) {
  switch (source) {
    case Source::MANUAL: return "manual";
    case Source::QUEUE: return "queue";
    case Source::SERVICE: return "service";
    default: return "other";
  }
}

/// What the engine reports for one zone.
struct ZoneInput {
  bool locked{false};
  bool running{false};
  bool paused{false};
  bool enabled{true};
  bool queued{false};
  int queue_pos{-1};
  bool has_time_left{false};
  uint32_t time_left{0};
  uint32_t run_duration{0};
  bool has_skip{false};
  uint32_t skip_stamp{0};  ///< millis() of the engine's last skip of this zone
  const char *skip_text{""};
  bool skip_wet{false};  ///< the skip was "soil too wet" (the adapter knows its engine's reasons); else a generic skip
  bool has_soil{false};
  float soil{0};  ///< soil moisture in percent, valid when has_soil
  const char *name{""};
};

/// Precedence LOCKED > RUNNING > PAUSED > DISABLED > QUEUED > SKIPPED > IDLE.
inline ZoneState resolve_state(const ZoneInput &in, bool skipped) {
  if (in.locked)
    return ZoneState::LOCKED;
  if (in.running)
    return ZoneState::RUNNING;
  if (in.paused)
    return ZoneState::PAUSED;
  if (!in.enabled)
    return ZoneState::DISABLED;
  if (in.queued)
    return ZoneState::QUEUED;
  if (skipped)
    return ZoneState::SKIPPED;
  return ZoneState::IDLE;
}

struct ZoneView {
  bool present{false};
  const char *name{""};
  char short_name[8]{"B?"};
  ZoneState state{ZoneState::IDLE};
  const char *skip_reason{""};
  std::optional<uint32_t> time_left;
  uint32_t run_duration{0};
  std::optional<uint8_t> queue_position;
  uint32_t run_total{0};  ///< seconds left at the first sample of the current run (progress bar), 0 = not running / unknown
  std::optional<float> soil;
  std::optional<uint32_t> last_start_epoch;
  std::optional<uint32_t> last_start_uptime;
  std::optional<uint32_t> last_duration;
};

/// A completed run or a skip (for the history). A run carries Result::DONE (the glue turns it into STOPPED inside the
/// stop window); a skip carries SKIPPED_WET / SKIPPED, duration 0 and Source::UNKNOWN.
struct RunRecord {
  uint32_t epoch{0};
  uint32_t duration{0};
  uint8_t zone{0};
  Source source{Source::UNKNOWN};
  Result result{Result::DONE};
  bool is_skip() const { return this->result == Result::SKIPPED_WET || this->result == Result::SKIPPED; }
};

/// Per-zone bookkeeping between refreshes: SKIPPED visibility and the last watering.
///
/// A run is "open" from the first RUNNING sample to the first sample that is neither RUNNING nor PAUSED. A PAUSED gap
/// inside it (008 semantics: a manual run interrupts the lane's current zone, which resumes afterwards) belongs to the
/// same run; the duration is the time the valve was open, the pause is not counted.
class ZoneTracker {
 public:
  void restore(uint32_t epoch, uint32_t duration) {
    if (epoch != 0 || duration != 0) {
      this->last_epoch_ = epoch;
      this->has_last_epoch_ = epoch != 0;
      this->last_duration_ = duration;
      this->has_last_duration_ = true;
    }
  }

  void update(uint32_t now_ms, uint32_t now_epoch, size_t index, const ZoneInput &in, Source start_source,
              ZoneView &out) {
    // skip record: a new stamp makes it current; running or queueing the zone, or 12 h, clears it
    if (in.has_skip && (!this->skip_seen_ || in.skip_stamp != this->skip_stamp_)) {
      this->skip_seen_ = true;
      this->skip_stamp_ = in.skip_stamp;
      this->skip_active_ = true;
      this->skip_since_ = now_ms;
      this->skip_pending_ = true;  // one history entry per engine skip stamp
      this->skip_wet_ = in.skip_wet;
      this->skip_epoch_ = now_epoch;
      this->index_ = static_cast<uint8_t>(index);
      std::snprintf(this->skip_text_, sizeof(this->skip_text_), "%s", in.skip_text != nullptr ? in.skip_text : "");
    }
    if (in.running || in.queued)
      this->skip_active_ = false;
    if (this->skip_active_ && static_cast<uint32_t>(now_ms - this->skip_since_) >= SKIP_VISIBLE_MS)
      this->skip_active_ = false;

    // run bookkeeping
    const bool in_run = in.running || in.paused;
    if (in_run && !this->run_open_) {
      this->run_open_ = true;
      this->open_ms_ = 0;
      this->seg_open_ = false;
      this->run_total_ = 0;
      this->run_epoch_ = now_epoch;
      this->run_source_ = start_source;
      // a service run (valve test) is in the history but is not the "last watering" of the zone
      if (start_source != Source::SERVICE) {
        this->last_start_uptime_ = now_ms / 1000U;
        this->has_last_uptime_ = true;
        this->last_epoch_ = now_epoch;
        this->has_last_epoch_ = now_epoch != 0;
      }
    }
    if (this->run_open_) {
      if (in.running && this->run_total_ == 0 && in.has_time_left)
        this->run_total_ = in.time_left;
      if (in.running && !this->seg_open_) {
        this->seg_open_ = true;
        this->seg_start_ = now_ms;
      } else if (!in.running && this->seg_open_) {
        this->open_ms_ += static_cast<uint32_t>(now_ms - this->seg_start_);
        this->seg_open_ = false;
      }
      if (!in_run) {
        this->run_open_ = false;
        this->run_total_ = 0;
        const uint32_t seconds = (this->open_ms_ + 500U) / 1000U;
        if (this->run_source_ != Source::SERVICE) {
          this->last_duration_ = seconds;
          this->has_last_duration_ = true;
        }
        this->done_ = true;
        this->record_.epoch = this->run_epoch_;
        this->record_.duration = seconds;
        this->record_.zone = static_cast<uint8_t>(index);
        this->record_.source = this->run_source_;
      }
    }

    out.present = true;
    out.name = in.name != nullptr ? in.name : "";
    std::snprintf(out.short_name, sizeof(out.short_name), "B%u", static_cast<unsigned>(index + 1));
    out.state = resolve_state(in, this->skip_active_);
    out.skip_reason = this->skip_active_ ? this->skip_text_ : "";
    out.time_left.reset();
    if (in.has_time_left && (in.running || in.paused))
      out.time_left = in.time_left;
    out.run_duration = in.run_duration;
    out.run_total = this->run_open_ ? this->run_total_ : 0;
    out.soil.reset();
    if (in.has_soil)
      out.soil = in.soil;
    out.queue_position.reset();
    if (in.queued && in.queue_pos >= 0)
      out.queue_position = static_cast<uint8_t>(in.queue_pos);
    out.last_start_epoch.reset();
    if (this->has_last_epoch_)
      out.last_start_epoch = this->last_epoch_;
    out.last_start_uptime.reset();
    if (this->has_last_uptime_)
      out.last_start_uptime = this->last_start_uptime_;
    out.last_duration.reset();
    if (this->has_last_duration_)
      out.last_duration = this->last_duration_;
  }

  /// The finished run first, then the pending skip (each once).
  bool take_completed(RunRecord &record) {
    if (this->done_) {
      this->done_ = false;
      record = this->record_;
      return true;
    }
    if (this->skip_pending_) {
      this->skip_pending_ = false;
      record = RunRecord{this->skip_epoch_, 0, this->index_, Source::UNKNOWN,
                         this->skip_wet_ ? Result::SKIPPED_WET : Result::SKIPPED};
      return true;
    }
    return false;
  }

 protected:
  bool skip_seen_{false}, skip_active_{false}, skip_pending_{false}, skip_wet_{false};
  uint32_t skip_epoch_{0};
  uint8_t index_{0};
  uint32_t run_total_{0};
  uint32_t skip_stamp_{0}, skip_since_{0};
  char skip_text_[SKIP_TEXT_LEN]{};
  bool run_open_{false}, seg_open_{false}, done_{false};
  uint32_t open_ms_{0}, seg_start_{0}, run_epoch_{0};
  Source run_source_{Source::UNKNOWN};
  RunRecord record_{};
  uint32_t last_epoch_{0}, last_start_uptime_{0}, last_duration_{0};
  bool has_last_epoch_{false}, has_last_uptime_{false}, has_last_duration_{false};
};

/// What the engine reports for the whole group.
struct GroupInput {
  size_t zone_count{0};
  ZoneInput zones[MAX_ZONES];
  Source start_source[MAX_ZONES]{};
  size_t active[MAX_ZONES]{};
  size_t active_count{0};
  size_t queue[MAX_ZONES]{};
  size_t queue_count{0};
  uint32_t queue_time{0};
  bool auto_advance{false};
  bool watchdog_tripped{false};
  bool has_total_left{false};
  uint32_t total_left{0};
};

struct GroupSummary {
  size_t zone_count{0};
  bool running{false};
  size_t active_count{0};
  size_t active[MAX_ZONES]{};
  size_t queue_length{0};
  uint32_t queue_time{0};
  bool auto_advance{false};
  bool watchdog_tripped{false};
  int now_zone{-1};  ///< first active zone, -1 = none
  bool has_now_left{false};
  uint32_t now_left{0};
  int next_zone{-1};  ///< first queued zone, -1 = none (schedules extend this later)
  bool has_zone_left{false};
  uint32_t zone_left{0};  ///< smallest time left over the active zones
  bool has_total_left{false};
  uint32_t total_left{0};
  uint32_t revision{1};
};

class GroupModel {
 public:
  GroupModel() { this->views_[0] = ZoneView{}; }

  void refresh(uint32_t now_ms, uint32_t now_epoch, const GroupInput &in) {
    const size_t count = in.zone_count < MAX_ZONES ? in.zone_count : MAX_ZONES;
    this->summary_.zone_count = count;
    for (size_t i = 0; i < count; i++)
      this->trackers_[i].update(now_ms, now_epoch, i, in.zones[i], in.start_source[i], this->views_[i]);
    for (size_t i = count; i < MAX_ZONES; i++)
      this->views_[i] = ZoneView{};

    GroupSummary &s = this->summary_;
    s.active_count = 0;
    s.now_zone = -1;
    s.has_now_left = false;
    s.has_zone_left = false;
    for (size_t i = 0; i < in.active_count && s.active_count < MAX_ZONES; i++) {
      if (in.active[i] >= count)
        continue;
      s.active[s.active_count++] = in.active[i];
      const ZoneView &v = this->views_[in.active[i]];
      if (v.time_left.has_value() && (!s.has_zone_left || *v.time_left < s.zone_left)) {
        s.has_zone_left = true;
        s.zone_left = *v.time_left;
      }
    }
    s.running = s.active_count > 0;
    if (s.running) {
      s.now_zone = static_cast<int>(s.active[0]);
      const ZoneView &v = this->views_[s.active[0]];
      s.has_now_left = v.time_left.has_value();
      s.now_left = s.has_now_left ? *v.time_left : 0;
    }
    s.queue_length = in.queue_count;
    s.next_zone = in.queue_count > 0 && in.queue[0] < count ? static_cast<int>(in.queue[0]) : -1;
    s.queue_time = in.queue_time;
    s.auto_advance = in.auto_advance;
    s.watchdog_tripped = in.watchdog_tripped;
    s.has_total_left = in.has_total_left;
    s.total_left = in.has_total_left ? in.total_left : 0;

    const uint32_t hash = this->hash_(count);
    if (!this->hashed_ || hash != this->hash_value_) {
      if (this->hashed_)
        s.revision++;
      this->hash_value_ = hash;
      this->hashed_ = true;
    }
  }

  /// Out of range returns the ABSENT view (`present == false`).
  const ZoneView &zone(size_t index) const { return index < this->summary_.zone_count ? this->views_[index] : absent(); }
  const GroupSummary &summary() const { return this->summary_; }

  void restore_last(size_t index, uint32_t epoch, uint32_t duration) {
    if (index < MAX_ZONES)
      this->trackers_[index].restore(epoch, duration);
  }

  bool take_completed(RunRecord &record) {
    for (size_t i = 0; i < MAX_ZONES; i++) {
      if (this->trackers_[i].take_completed(record))
        return true;
    }
    return false;
  }

  static const ZoneView &absent() {
    static const ZoneView ABSENT{};
    return ABSENT;
  }

 protected:
  static void mix_(uint32_t &h, uint32_t v) {
    for (int i = 0; i < 4; i++) {
      h ^= (v >> (8 * i)) & 0xFFU;
      h *= 16777619U;
    }
  }

  /// The whole percent a soil value is shown as, so the revision moves only when the text would change.
  static uint32_t soil_percent_(float soil) { return soil <= 0.0f ? 0U : soil >= 100.0f ? 100U : static_cast<uint32_t>(soil + 0.5f); }

  uint32_t hash_(size_t count) const {
    uint32_t h = 2166136261U;
    const GroupSummary &s = this->summary_;
    mix_(h, static_cast<uint32_t>(count));
    for (size_t i = 0; i < count; i++) {
      const ZoneView &v = this->views_[i];
      mix_(h, static_cast<uint32_t>(v.state));
      mix_(h, v.time_left.has_value() ? *v.time_left + 1U : 0U);
      mix_(h, v.queue_position.has_value() ? *v.queue_position + 1U : 0U);
      mix_(h, v.run_duration);
      mix_(h, v.soil.has_value() ? soil_percent_(*v.soil) + 1U : 0U);
      mix_(h, v.last_start_epoch.value_or(0));
      mix_(h, v.last_start_uptime.has_value() ? *v.last_start_uptime + 1U : 0U);
      mix_(h, v.last_duration.has_value() ? *v.last_duration + 1U : 0U);
      for (const char *c = v.skip_reason; *c != '\0'; c++)
        mix_(h, static_cast<uint32_t>(*c));
      for (const char *c = v.name; *c != '\0'; c++)
        mix_(h, static_cast<uint32_t>(*c));
    }
    mix_(h, static_cast<uint32_t>(s.active_count));
    for (size_t i = 0; i < s.active_count; i++)
      mix_(h, static_cast<uint32_t>(s.active[i]));
    mix_(h, static_cast<uint32_t>(s.queue_length));
    mix_(h, s.queue_time);
    mix_(h, static_cast<uint32_t>(s.next_zone + 1));
    mix_(h, (s.auto_advance ? 1U : 0U) | (s.watchdog_tripped ? 2U : 0U));
    mix_(h, s.has_total_left ? s.total_left + 1U : 0U);
    return h;
  }

  ZoneTracker trackers_[MAX_ZONES];
  ZoneView views_[MAX_ZONES];
  GroupSummary summary_;
  uint32_t hash_value_{0};
  bool hashed_{false};
};

}  // namespace esphome::gp
