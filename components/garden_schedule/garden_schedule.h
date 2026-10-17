// garden_schedule — ESPHome glue: the hub reads the slot entities every second, runs the pure core
// (schedule_core.h), persists the marks, publishes the next run and fires `on_run` for each due slot.
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The hub knows nothing about irrigation: `on_run` hands (zone_mask, multiplier_pct, slot) to the YAML, which routes it
// to the gp_* layer. A zone's completion comes back through the `garden_schedule.zone_done` action.
#pragma once

#include <array>
#include <cstdio>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "esphome/components/datetime/time_entity.h"
#include "esphome/components/number/number.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/text/text.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/time/real_time_clock.h"
#include "esphome/core/application.h"
#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "esphome/core/preferences.h"

#include "schedule_core.h"
#include "schedule_format.h"
#include "schedule_ui.h"

namespace esphome::garden_schedule {

inline constexpr const char *TAG = "garden_schedule";

/// The entities of one slot (all owned by ESPHome; the hub only reads them).
struct SlotEntities {
  uint8_t number{0};  ///< 1-based, as shown in the entity names
  switch_::Switch *enabled{nullptr};
  datetime::TimeEntity *start{nullptr};
  std::array<switch_::Switch *, 7> days{};  ///< Monday .. Sunday
  text::Text *zones{nullptr};
  number::Number *multiplier{nullptr};
};

/// Persisted marks (version 2): the local day and start minute of each slot's last run and the zones of that run
/// still to do. Stored under the key "garden_schedule2:<hub id>"; a blob of another size never loads (ESPHome checks the
/// stored length: esp32/preferences.cpp load(), host/preferences.h load()).
struct PersistBlob {
  uint8_t version{2};
  int32_t last_fired_day[MAX_SLOTS]{NEVER, NEVER, NEVER, NEVER, NEVER, NEVER, NEVER, NEVER};
  uint16_t last_fired_minute[MAX_SLOTS]{ANY_MINUTE, ANY_MINUTE, ANY_MINUTE, ANY_MINUTE,
                                        ANY_MINUTE, ANY_MINUTE, ANY_MINUTE, ANY_MINUTE};
  uint32_t pending[MAX_SLOTS]{};
};

/// The version 1 blob (no start minute), key "garden_schedule:<hub id>"; read once to migrate the marks.
struct PersistBlobV1 {
  uint8_t version{1};
  int32_t last_fired_day[MAX_SLOTS]{};
  uint32_t pending[MAX_SLOTS]{};
};

class GardenSchedule : public Component {
 public:
  void set_time(time::RealTimeClock *time) { this->time_ = time; }
  void set_key(const std::string &key) { this->key_ = key; }
  void set_catch_up_window(uint32_t minutes) { this->core_.set_catch_up_minutes(minutes); }
  void set_zone_count(size_t count) { this->zone_count_ = count; }
  void set_master_switch(switch_::Switch *sw) { this->master_ = sw; }
  void set_next_run_sensor(text_sensor::TextSensor *s) { this->next_run_ = s; }
  void set_next_run_text_sensor(text_sensor::TextSensor *s) { this->next_text_ = s; }
  void set_last_result_sensor(text_sensor::TextSensor *s) { this->last_result_ = s; }
  void add_skip(Condition<> *condition, const std::string &reason) { this->skips_.push_back({condition, reason}); }
  void add_slot(uint8_t number, switch_::Switch *enabled, datetime::TimeEntity *start, text::Text *zones,
                number::Number *multiplier, std::array<switch_::Switch *, 7> days) {
    if (this->slots_.size() >= MAX_SLOTS)
      return;
    SlotEntities slot;
    slot.number = number;
    slot.enabled = enabled;
    slot.start = start;
    slot.zones = zones;
    slot.multiplier = multiplier;
    slot.days = days;
    this->slots_.push_back(slot);
  }
  void add_on_run_callback(std::function<void(uint32_t, uint8_t, uint8_t)> &&callback) {
    this->run_cb_.add(std::move(callback));
  }

  float get_setup_priority() const override { return setup_priority::LATE; }

  void setup() override {
    this->pref_ = global_preferences->make_preference<PersistBlob>(fnv1_hash("garden_schedule2:" + this->key_));
    PersistBlob blob;
    if (this->pref_.load(&blob) && blob.version == 2) {
      this->blob_ = blob;
    } else {
      // an upgrade from version 1: the old marks match any start minute, so the upgrade day behaves as before
      ESPPreferenceObject old =
          global_preferences->make_preference<PersistBlobV1>(fnv1_hash("garden_schedule:" + this->key_));
      PersistBlobV1 v1;
      if (!old.load(&v1) || v1.version != 1)
        return;
      for (size_t k = 0; k < MAX_SLOTS; k++) {
        this->blob_.last_fired_day[k] = v1.last_fired_day[k];
        this->blob_.last_fired_minute[k] = ANY_MINUTE;
        this->blob_.pending[k] = v1.pending[k];
      }
      ESP_LOGI(TAG, "migrated the run marks from version 1");
    }
    // marks are keyed by the slot NUMBER (1..8), so reordering or removing an include never moves them
    for (size_t i = 0; i < this->slots_.size() && i < MAX_SLOTS; i++) {
      const size_t k = this->slots_[i].number - 1u;
      if (k < MAX_SLOTS)
        this->core_.restore(i, this->blob_.last_fired_day[k], this->blob_.last_fired_minute[k], this->blob_.pending[k]);
    }
    ESP_LOGI(TAG, "restored the run marks of %u slot(s)", (unsigned) this->slots_.size());
  }

  void dump_config() override {
    ESP_LOGCONFIG(TAG, "garden_schedule: %u slot(s), %u zone(s), clock %s", (unsigned) this->slots_.size(),
                  (unsigned) this->zone_count_, this->time_ != nullptr ? "yes" : "no");
  }

  void loop() override {
    const uint32_t now = millis();
    if (this->started_ && (uint32_t) (now - this->last_tick_) < TICK_MS)
      return;
    this->started_ = true;
    this->last_tick_ = now;
    this->evaluate_(now);
  }

  /// A zone's watering completed (called by the `garden_schedule.zone_done` action; 0-based zone).
  void zone_done(size_t zone) {
    if (this->core_.zone_done(zone)) {
      ESP_LOGI(TAG, "zone %u done", (unsigned) (zone + 1));
      this->save_();
    }
  }

  /// A user STOP or entering service mode (called by `garden_schedule.cancel_pending`): today's pending zones of every
  /// slot are settled ("stopped"), so nothing resumes after a restart.
  void cancel_pending() {
    const std::vector<uint8_t> stopped = this->core_.stop_pending();
    if (stopped.empty())
      return;
    for (uint8_t slot : stopped) {
      ESP_LOGI(TAG, "slot %u stopped: its remaining zones are cancelled", (unsigned) this->slots_[slot].number);
      this->publish_result_(slot, "stopped");
    }
    this->save_();
  }

  // ---- data for the screens (stage 9) ----
  optional<NextRun> next_run() const {
    auto next = this->core_.next_run(this->cfg_, this->slots_.size());
    if (!next.has_value())
      return {};
    return *next;
  }
  std::vector<DayRun> day_runs(int day_offset) const {
    return this->core_.day_runs(day_offset, this->cfg_, this->slots_.size());
  }
  const std::string &next_run_text() const { return this->next_text_value_; }
  uint8_t slot_number(size_t index) const { return index < this->slots_.size() ? this->slots_[index].number : 0; }
  // ---- data for the screens (task 026; the texts are the pure helpers of schedule_format.h) ----
  size_t slot_count() const { return this->slots_.size(); }
  bool master_on() const { return this->core_.master(); }
  /// What a screen shows about slot `index` (0-based, include order); a default view when out of range.
  SlotView slot_view(size_t index) const {
    SlotView v;
    if (index >= this->slots_.size())
      return v;
    const SlotConfig &c = this->cfg_[index];
    v.number = this->slots_[index].number;
    v.enabled = c.enabled;
    v.start_minute = c.start_minute;
    v.days_mask = c.days_mask;
    v.zone_mask = c.zone_mask;
    v.pct = c.pct;
    v.today = this->today_(index);
    return v;
  }
  size_t zone_count() const { return this->zone_count_; }
  /// The zone run durations the list captions use ("5 min each"), set once from the YAML (the hub never reads `gp`).
  void set_zone_seconds(std::function<uint32_t(size_t)> &&provider) { this->zone_seconds_ = std::move(provider); }

  // ---- the D08 list rows (the texts come from schedule_ui.h; they read the 1 s copy of the slot entities) ----
  std::string row_time(size_t index) const {
    if (index >= this->slots_.size())
      return std::string();
    return ::esphome::garden_schedule::row_time(this->cfg_[index].enabled, this->cfg_[index].start_minute);
  }
  std::string row_label(size_t index, const char *group, const char *noun) const {
    if (index >= this->slots_.size())
      return std::string();
    const SlotConfig &c = this->cfg_[index];
    if (!c.enabled)
      return "Slot " + std::to_string(this->slots_[index].number);
    return zones_label(group, noun, c.zone_mask, this->zone_count_);
  }
  std::string row_caption(size_t index) const {
    if (index >= this->slots_.size())
      return std::string();
    const SlotConfig &c = this->cfg_[index];
    return ::esphome::garden_schedule::row_caption(
        c.enabled, c.days_mask, duration_text(c.zone_mask, this->zone_count_, this->zone_seconds_, c.pct));
  }
  StatusWord row_status(size_t index) const {
    if (index >= this->slots_.size())
      return StatusWord{};
    const optional<NextRun> next = this->next_run();
    DayRunState state = DayRunState::PENDING;
    for (const DayRun &run : this->core_.day_runs(0, this->cfg_, this->slots_.size())) {
      if (run.slot == index)
        state = run.state;
    }
    return status_word(this->cfg_[index].enabled, this->core_.master(), state, this->core_.state(index).pending != 0,
                       next.has_value() && next->slot == index);
  }
  std::string row_status_text(size_t index) const { return this->row_status(index).text; }
  uint32_t row_status_color(size_t index) const { return this->row_status(index).color; }
  uint32_t row_text_color(size_t index) const {
    return index < this->slots_.size() && this->cfg_[index].enabled ? TONE_TEXT : TONE_DIM;
  }
  /// Home "next": "06:00" / "Tue 06:00" / "--:--".
  std::string next_run_short() const {
    const optional<NextRun> next = this->next_run();
    return next_short(next.has_value(), next.has_value() ? next->day : 0, next.has_value() ? next->start_minute : 0,
                      this->core_.today());
  }
  /// True when anything a schedule screen shows changed since `seen` (updated); `seen == 0` always redraws.
  bool changed_since(uint32_t &seen) const {
    std::vector<SlotView> views;
    for (size_t i = 0; i < this->slots_.size(); i++)
      views.push_back(this->slot_view(i));
    uint32_t seconds = 2166136261u;  // the captions show the zone durations
    if (this->zone_seconds_) {
      for (size_t z = 0; z < this->zone_count_; z++)
        seconds = (seconds ^ this->zone_seconds_(z)) * 16777619u;
    }
    const uint32_t hash = view_hash(views, this->core_.master(), this->next_run_short(), seconds);
    if (hash == seen)
      return false;
    seen = hash;
    return true;
  }

  // ---- the editor (Schedule N page): a RAM draft, the entities are written only by save_edit() ----
  /// Starts editing slot `index` (0-based, include order) from the entities (not the 1 s copy); out of range: WARN, no-op.
  void begin_edit(size_t index) {
    if (index >= this->slots_.size()) {
      ESP_LOGW(TAG, "begin_edit: no slot at index %u", (unsigned) index);
      return;
    }
    const SlotEntities &e = this->slots_[index];
    ScheduleDraft d;
    d.index = static_cast<uint8_t>(index);
    d.enabled = e.enabled != nullptr && e.enabled->state;
    d.hour = static_cast<uint8_t>(e.start->hour % 24);
    d.minute = static_cast<uint8_t>(e.start->minute % 60);
    uint8_t days = 0;
    for (size_t k = 0; k < 7; k++) {
      if (e.days[k] != nullptr && e.days[k]->state)
        days |= static_cast<uint8_t>(1u << k);
    }
    d.days_mask = days;
    const optional<uint32_t> mask = parse_zones(e.zones != nullptr ? e.zones->state : std::string(), this->zone_count_);
    d.zone_mask = mask.has_value() ? *mask : 0;
    float m = e.multiplier != nullptr ? e.multiplier->state : 100.0f;
    if (m != m)
      m = 100.0f;
    m = m < 10.0f ? 10.0f : m > 200.0f ? 200.0f : m;
    d.pct = static_cast<uint8_t>(m + 0.5f);
    this->original_ = d;
    this->draft_ = d;
    this->editing_ = true;
  }
  ScheduleDraft &draft() { return this->draft_; }
  bool editing() const { return this->editing_; }
  std::string edit_title() const { return "Schedule " + std::to_string(this->slot_number(this->draft_.index)); }
  // one-line helpers of the editor buttons (day 0..6 = Mon..Sun, zone 0-based)
  void edit_toggle_day(size_t day) { this->draft_.toggle_day(static_cast<uint8_t>(day)); }
  void edit_toggle_zone(size_t zone) { this->draft_.toggle_zone(zone, this->zone_count_); }
  bool edit_day_on(size_t day) const { return day < 7 && (this->draft_.days_mask & (1u << day)) != 0; }
  bool edit_zone_on(size_t zone) const { return zone < 32 && (this->draft_.zone_mask & (1u << zone)) != 0; }
  bool edit_day_visible(size_t day) const { return day < 7; }
  bool edit_zone_visible(size_t zone) const { return zone < this->zone_count_; }
  bool can_save() const { return this->editing_ && this->draft_.can_save(); }
  /// Writes the changed fields of the draft to the slot entities (the ones Home Assistant edits) and closes the editor.
  /// Returns false, writing nothing, when no edit is open or the draft cannot be saved. Fields the user did not change
  /// are not written, so a change made from Home Assistant meanwhile survives.
  bool save_edit() {
    if (!this->editing_ || this->draft_.index >= this->slots_.size() || !this->draft_.can_save())
      return false;
    const SlotEntities &e = this->slots_[this->draft_.index];
    const Diff diff = this->draft_.diff(this->original_);
    if (diff.enabled && e.enabled != nullptr) {
      if (this->draft_.enabled)
        e.enabled->turn_on();
      else
        e.enabled->turn_off();
    }
    if (diff.start && e.start != nullptr)
      e.start->make_call().set_time(this->draft_.hour, this->draft_.minute, 0).perform();
    for (size_t k = 0; k < 7; k++) {
      if ((diff.days & (1u << k)) == 0 || e.days[k] == nullptr)
        continue;
      if ((this->draft_.days_mask & (1u << k)) != 0)
        e.days[k]->turn_on();
      else
        e.days[k]->turn_off();
    }
    const std::string zones = this->draft_.zones_text(this->zone_count_);
    if (diff.zones && !zones.empty() && e.zones != nullptr)
      e.zones->make_call().set_value(zones).perform();
    if (diff.pct && e.multiplier != nullptr)
      e.multiplier->make_call().set_value(static_cast<float>(this->draft_.pct)).perform();
    ESP_LOGI(TAG, "slot %u saved from the screen%s", (unsigned) e.number, diff.any() ? "" : " (no change)");
    this->editing_ = false;
    this->read_config_();  // the list shows the saved values at once, not after the next 1 s tick
    return true;
  }
  void cancel_edit() { this->editing_ = false; }
  /// Sets the global run-time factor in percent (100 = unchanged); slot multipliers are scaled by it.
  void set_global_pct(uint8_t pct) { this->core_.set_global_pct(pct); }

 protected:
  static constexpr uint32_t TICK_MS = 1000;

  struct Skip {
    Condition<> *condition;
    std::string reason;
  };

  Today today_(size_t index) const {
    for (const DayRun &run : this->core_.day_runs(0, this->cfg_, this->slots_.size())) {
      if (run.slot != index)
        continue;
      switch (run.state) {
        case DayRunState::FIRED:
          return this->core_.state(index).pending != 0 ? Today::RUNNING : Today::DONE;
        case DayRunState::MISSED:
          return Today::MISSED;
        case DayRunState::SKIPPED:
          return Today::SKIPPED;
        case DayRunState::STOPPED:
          return Today::STOPPED;
        default:
          return Today::NONE;
      }
    }
    return Today::NONE;
  }

  Tick read_clock_(uint32_t now_ms) const {
    Tick t;
    t.mono_ms = now_ms;
    if (this->time_ == nullptr)
      return t;
    ESPTime now = this->time_->now();
    if (!now.is_valid())
      return t;
    t.valid = true;
    t.epoch = static_cast<int64_t>(now.timestamp);
    t.local.day = days_from_civil(now.year, now.month, now.day_of_month);
    t.local.minute = static_cast<uint16_t>(now.hour * 60 + now.minute);
    t.local.second = now.second > 59 ? 59 : now.second;
    return t;
  }

  /// Copies the entity states into the core's slot configuration; a slot with an unusable zone list is disabled.
  void read_config_() {
    for (size_t i = 0; i < this->slots_.size(); i++) {
      const SlotEntities &e = this->slots_[i];
      SlotConfig &c = this->cfg_[i];
      c.enabled = e.enabled != nullptr && e.enabled->state;
      c.start_minute = static_cast<uint16_t>(e.start->hour * 60 + e.start->minute);
      uint8_t days = 0;
      for (size_t d = 0; d < 7; d++) {
        if (e.days[d] != nullptr && e.days[d]->state)
          days |= static_cast<uint8_t>(1u << d);
      }
      c.days_mask = days;
      float m = e.multiplier != nullptr ? e.multiplier->state : 100.0f;
      if (m != m || m < 10.0f)  // NaN or below the range
        m = m != m ? 100.0f : 10.0f;
      if (m > 200.0f)
        m = 200.0f;
      c.pct = static_cast<uint8_t>(m + 0.5f);
      bool dropped = false;
      const optional<uint32_t> mask = parse_zones(e.zones != nullptr ? e.zones->state : std::string(), this->zone_count_, &dropped);
      if (dropped && !this->warned_zones_[i]) {
        this->warned_zones_[i] = true;
        ESP_LOGW(TAG, "slot %u: zone numbers outside 1..%u are ignored", (unsigned) e.number, (unsigned) this->zone_count_);
      }
      if (!dropped)
        this->warned_zones_[i] = false;
      if (!mask.has_value()) {
        if (c.enabled && !this->warned_invalid_[i]) {
          this->warned_invalid_[i] = true;
          ESP_LOGW(TAG, "slot %u: the zone list '%s' is invalid, the slot does not run", (unsigned) e.number,
                   e.zones != nullptr ? e.zones->state.c_str() : "");
        }
        c.zone_mask = 0;
      } else {
        this->warned_invalid_[i] = false;
        c.zone_mask = *mask;
      }
    }
  }

  void evaluate_(uint32_t now_ms) {
    this->read_config_();
    this->core_.set_master(this->master_ == nullptr || this->master_->state);
    Events events;
    const bool was_valid = this->core_.clock_valid();
    this->core_.tick(this->read_clock_(now_ms), this->cfg_, this->slots_.size(), events);
    if (events.clock_became_valid)
      ESP_LOGI(TAG, "clock valid, schedules active");
    else if (was_valid && !this->core_.clock_valid())
      ESP_LOGW(TAG, "clock lost, schedules paused");
    if (events.future_cleared)
      ESP_LOGW(TAG, "a run mark from the future was cleared (the clock was wrong when it was written)");
    for (const Missed &m : events.missed) {
      ESP_LOGW(TAG, "slot %u missed: %u min late, not run", (unsigned) this->slots_[m.slot].number, (unsigned) m.minutes_late);
      char note[32];
      std::snprintf(note, sizeof(note), "missed (%u min late)", (unsigned) m.minutes_late);
      this->publish_result_(m.slot, note);
    }
    for (uint8_t slot : events.dropped)
      ESP_LOGI(TAG, "slot %u: its start changed while it was pending, the old zones are dropped",
               (unsigned) this->slots_[slot].number);
    for (const Fire &f : events.fires)
      this->handle_fire_(f);
    if (events.state_changed || !events.fires.empty() || !events.missed.empty())
      this->save_();
    this->publish_next_();
  }

  void handle_fire_(const Fire &f) {
    const unsigned number = this->slots_[f.slot].number;
    for (const Skip &skip : this->skips_) {
      if (skip.condition->check()) {
        ESP_LOGI(TAG, "slot %u skipped: %s", number, skip.reason.c_str());
        this->core_.mark_skipped(f.slot);
        this->publish_result_(f.slot, ("skipped: " + skip.reason).c_str());
        return;
      }
    }
    ESP_LOGI(TAG, "slot %u runs zones 0x%X at %u %%%s", number, (unsigned) f.zone_mask, (unsigned) f.pct,
             f.catch_up ? " (catch-up)" : "");
    this->publish_result_(f.slot, f.catch_up ? "ran (catch-up)" : "ran");
    this->run_cb_.call(f.zone_mask, f.pct, static_cast<uint8_t>(number));
  }

  void publish_result_(size_t index, const char *note) {
    char buf[96];
    std::snprintf(buf, sizeof(buf), "%s #%u %s", format_time(this->cfg_[index].start_minute).c_str(),
                  (unsigned) this->slots_[index].number, note);
    if (this->last_result_ != nullptr)
      this->last_result_->publish_state(buf);
  }

  void save_() {
    PersistBlob &blob = this->blob_;
    for (size_t i = 0; i < this->slots_.size() && i < MAX_SLOTS; i++) {
      const size_t k = this->slots_[i].number - 1u;
      if (k >= MAX_SLOTS)
        continue;
      blob.last_fired_day[k] = this->core_.state(i).last_fired_day;
      blob.last_fired_minute[k] = this->core_.state(i).last_fired_minute;
      blob.pending[k] = this->core_.state(i).pending;
    }
    if (!this->pref_.save(&blob))
      ESP_LOGW(TAG, "saving the run marks failed");
    global_preferences->sync();  // a completed zone must survive a power cut: do not wait for the 60 s batch
  }

  void publish_next_() {
    std::string iso, text = "--:--";
    const optional<NextRun> next = this->next_run();
    if (next.has_value()) {
      text = std::string(weekday_name(weekday_of(next->day))) + " " + format_time(next->start_minute);
      int y = 0;
      unsigned m = 0, d = 0;
      civil_from_days(next->day, y, m, d);
      ESPTime t{};
      t.year = static_cast<uint16_t>(y);
      t.month = static_cast<uint8_t>(m);
      t.day_of_month = static_cast<uint8_t>(d);
      t.hour = static_cast<uint8_t>(next->start_minute / 60);
      t.minute = static_cast<uint8_t>(next->start_minute % 60);
      t.second = 0;
      t.recalc_timestamp_local();
      const int64_t local = static_cast<int64_t>(next->day) * 86400 + next->start_minute * 60;
      iso = format_iso(next->day, next->start_minute, static_cast<int32_t>(local - static_cast<int64_t>(t.timestamp)));
    }
    if (!this->next_published_ || iso != this->next_iso_value_) {
      this->next_iso_value_ = iso;
      if (this->next_run_ != nullptr)
        this->next_run_->publish_state(iso);
    }
    if (!this->next_published_ || text != this->next_text_value_) {
      this->next_text_value_ = text;
      if (this->next_text_ != nullptr)
        this->next_text_->publish_state(text);
    }
    this->next_published_ = true;
  }

  time::RealTimeClock *time_{nullptr};
  switch_::Switch *master_{nullptr};
  text_sensor::TextSensor *next_run_{nullptr}, *next_text_{nullptr}, *last_result_{nullptr};
  std::vector<SlotEntities> slots_;
  std::vector<Skip> skips_;
  Scheduler core_;
  PersistBlob blob_;  ///< last stored marks by slot number - 1 (slots not configured now keep their old marks)
  SlotConfig cfg_[MAX_SLOTS];
  bool warned_zones_[MAX_SLOTS]{};
  bool warned_invalid_[MAX_SLOTS]{};
  CallbackManager<void(uint32_t, uint8_t, uint8_t)> run_cb_;
  ESPPreferenceObject pref_;
  std::string key_{"hub"};
  std::string next_iso_value_, next_text_value_;
  size_t zone_count_{16};
  std::function<uint32_t(size_t)> zone_seconds_;
  ScheduleDraft draft_, original_;
  bool editing_{false};
  uint32_t last_tick_{0};
  bool started_{false};
  bool next_published_{false};
};

class RunTrigger : public Trigger<uint32_t, uint8_t, uint8_t> {
 public:
  explicit RunTrigger(GardenSchedule *hub) {
    hub->add_on_run_callback([this](uint32_t mask, uint8_t pct, uint8_t slot) { this->trigger(mask, pct, slot); });
  }
};

/// `garden_schedule.zone_done`: a zone's watering completed (0-based zone index).
template<typename... Ts> class ZoneDoneAction : public Action<Ts...> {
 public:
  explicit ZoneDoneAction(GardenSchedule *hub) : hub_(hub) {}
  TEMPLATABLE_VALUE(size_t, zone)
  void play(const Ts &...x) override { this->hub_->zone_done(this->zone_.value(x...)); }

 protected:
  GardenSchedule *hub_;
};

/// `garden_schedule.cancel_pending`: a user STOP settles the pending zones of every slot.
template<typename... Ts> class CancelPendingAction : public Action<Ts...> {
 public:
  explicit CancelPendingAction(GardenSchedule *hub) : hub_(hub) {}
  void play(const Ts &...x) override { this->hub_->cancel_pending(); }

 protected:
  GardenSchedule *hub_;
};

}  // namespace esphome::garden_schedule
