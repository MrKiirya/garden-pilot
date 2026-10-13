// gp — ESPHome glue: hub, groups, actions, conditions, triggers, zone switch.
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// Contract: components/gp/README.md. The model itself is pure C++ (zone_model.h, alerts.h, history.h, format.h);
// this file connects it to ESPHome (loop, preferences, time, actions) and to one engine adapter per group.
#pragma once

#include <cstdio>
#include <memory>
#include <string>
#include <vector>

#include "esphome/components/switch/switch.h"
#include "esphome/components/time/real_time_clock.h"
#include "esphome/core/application.h"
#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "esphome/core/preferences.h"
#include "esphome/core/time.h"

#include "alerts.h"
#include "deferred_start.h"
#include "engine.h"
#include "format.h"
#include "format_history.h"
#include "history.h"
#include "limits.h"
#include "zone_model.h"

namespace esphome::gp {

inline constexpr const char *TAG = "gp";

class GpHub;

/// One group of zones (for example the greenhouse) served by one engine adapter.
class GpGroup {
 public:
  GpGroup(std::string key, std::string name, Engine *engine)
      : key_(std::move(key)), name_(std::move(name)), engine_(engine) {}

  const std::string &key() const { return this->key_; }
  const std::string &name() const { return this->name_; }
  void set_hub(GpHub *hub) { this->hub_ = hub; }

  // ---- read model (polled by the pollers; see the README) ----
  const ZoneView &zone(size_t index) const { return this->model_.zone(index); }
  const GroupSummary &summary() const { return this->model_.summary(); }
  const GroupModel &model() const { return this->model_; }
  const History<HISTORY_LENGTH> &history() const { return this->blob_.history; }

  /// True when an entry was added since the count stored in `seen` (a RAM counter, not part of the flash blob);
  /// stores the current count. For the History page poller.
  bool history_changed_since(uint32_t &seen) const {
    const bool changed = seen != this->history_pushes_;
    seen = this->history_pushes_;
    return changed;
  }
  /// Text of row `row` (0-based) of History page `page`, newest entry first; empty past the end.
  std::string history_row(int page, size_t row) const {
    const size_t index = static_cast<size_t>(fmt::history_clamp_page(this->blob_.history.size(), page)) * fmt::HISTORY_ROWS + row;
    if (index >= this->blob_.history.size())
      return "";
    const HistoryEntry entry = this->blob_.history.at(index);
    fmt::LocalTime when;
    if (entry.epoch != 0) {
      const ESPTime t = ESPTime::from_epoch_local(entry.epoch);
      when = fmt::LocalTime{t.is_valid(), static_cast<uint8_t>(t.day_of_month), static_cast<uint8_t>(t.month),
                            static_cast<uint8_t>(t.hour), static_cast<uint8_t>(t.minute)};
    }
    return fmt::history_row(entry, when);
  }
  /// "1-6 of 37" for History page `page`.
  std::string history_pager(int page) const { return fmt::history_pager(this->blob_.history.size(), page); }
  /// `page` limited to the existing History pages.
  int history_clamp_page(int page) const { return fmt::history_clamp_page(this->blob_.history.size(), page); }

  /// True when something visible changed since the revision stored in `seen`; stores the current revision.
  bool changed_since(uint32_t &seen) const {
    const uint32_t revision = this->model_.summary().revision;
    const bool changed = seen != revision;
    seen = revision;
    return changed;
  }

  /// The Home Assistant status text when it changed since the last call, else nothing.
  optional<std::string> status_text_changed() {
    std::string text = fmt::ha_status(this->model_.summary());
    if (text == this->last_status_)
      return {};
    this->last_status_ = text;
    return text;
  }

  bool zone_running(size_t index) const { return this->model_.zone(index).state == ZoneState::RUNNING; }

  /// One stable line for tests: "B1:IDLE B2:RUN(5) B3:QUEUED(0) q=1 a=<top alert key or ->".
  std::string debug_line() const;

  // ---- actions ----
  /// Returns false when the run was refused (no such zone, locked by the watchdog).
  bool run_zone(size_t zone, optional<uint32_t> seconds, Source source = Source::MANUAL) {
    if (!this->check_zone_("run_zone", zone))
      return false;
    if (this->inhibited_ && source != Source::SERVICE) {
      ESP_LOGW(TAG, "%s: run_zone refused: service mode is on", this->name_.c_str());
      return false;
    }
    if (this->engine_->zone_locked(zone)) {
      ESP_LOGW(TAG, "%s: run_zone refused: zone %u is locked by the watchdog (reset it first)", this->name_.c_str(),
               (unsigned) (zone + 1));
      return false;
    }
    seconds = this->clamp_(zone, seconds);
    ESP_LOGI(TAG, "%s: run zone %u%s", this->name_.c_str(), (unsigned) (zone + 1), seconds.has_value() ? " (timed)" : "");
    this->intent_[zone] = source;
    this->intent_ms_[zone] = millis();
    this->engine_->run_zone(zone, seconds);
    return true;
  }

  void enqueue_zone(size_t zone, optional<uint32_t> seconds) {
    if (!this->check_zone_("enqueue_zone", zone))
      return;
    if (this->inhibited_) {
      ESP_LOGW(TAG, "%s: enqueue_zone refused: service mode is on", this->name_.c_str());
      return;
    }
    seconds = this->clamp_(zone, seconds);
    if (this->run_blocks_queue_(false)) {
      if (this->deferred_enq_.size() >= MAX_DEFERRED) {
        ESP_LOGW(TAG, "%s: enqueue_zone: too many deferred requests, dropped", this->name_.c_str());
        return;
      }
      ESP_LOGI(TAG, "%s: enqueue_zone deferred: a run that is not a queue run is active, the zone queues after it",
               this->name_.c_str());
      this->deferred_enq_.push_back(DeferredEnqueue{0, 0, zone, seconds, true});
      this->deferred_.request(millis());
      return;
    }
    this->queue_now_(zone, seconds);
  }

  /// Queues every zone of the bit mask (bit n = zone n, 0-based) in zone order, each for its configured run duration
  /// times `pct` percent (cut to the zone's maximum). Zones that are already queued or running are not queued again;
  /// bits beyond the group's zones are ignored. Never starts anything.
  void enqueue_zones(uint32_t mask, uint8_t pct) {
    if (this->inhibited_) {
      ESP_LOGW(TAG, "%s: enqueue_zones refused: service mode is on", this->name_.c_str());
      return;
    }
    if (this->run_blocks_queue_(false)) {
      // The engine picks queued zones at the next zone change, also in the middle of a cycle: hold them back here
      // and queue them after the run has ended (refresh()).
      if (this->deferred_enq_.size() >= MAX_DEFERRED) {
        ESP_LOGW(TAG, "%s: enqueue_zones: too many deferred requests, dropped", this->name_.c_str());
        return;
      }
      ESP_LOGI(TAG, "%s: enqueue_zones deferred: a run that is not a queue run is active, the zones queue after it",
               this->name_.c_str());
      this->deferred_enq_.push_back(DeferredEnqueue{mask, pct, 0, {}, false});
      this->deferred_.request(millis());
      return;
    }
    this->engine_->read(this->input_);  // fresh state: two calls in one tick must not queue a zone twice
    for (size_t zone = 0; zone < 32; zone++) {
      if (!(mask & (1u << zone)))
        continue;
      if (zone >= this->zone_count_ || zone >= MAX_ZONES) {
        ESP_LOGW(TAG, "%s: enqueue_zones: no zone %u, ignored", this->name_.c_str(), (unsigned) (zone + 1));
        continue;
      }
      const ZoneInput &in = this->input_.zones[zone];
      if (in.running || in.paused || in.queued) {
        ESP_LOGI(TAG, "%s: zone %u is already %s, not queued again", this->name_.c_str(), (unsigned) (zone + 1),
                 in.queued ? "queued" : "running");
        continue;
      }
      optional<uint32_t> seconds;
      if (in.run_duration > 0)
        seconds = static_cast<uint32_t>((static_cast<uint64_t>(in.run_duration) * pct + 50) / 100);
      this->queue_now_(zone, this->clamp_(zone, seconds));
    }
  }

  void dequeue_zone(size_t zone) {
    if (!this->check_zone_("dequeue_zone", zone))
      return;
    ESP_LOGI(TAG, "%s: dequeue zone %u", this->name_.c_str(), (unsigned) (zone + 1));
    this->engine_->remove_queued_zone(zone);
  }

  void start_queue() {
    if (this->inhibited_) {
      ESP_LOGW(TAG, "%s: start_queue refused: service mode is on", this->name_.c_str());
      return;
    }
    if (this->run_blocks_queue_(true)) {
      // A manual full cycle (or any run that is not a queue run) is not cut short, and the engine loses a start while
      // it is stopping: the queue starts after that run / the stop has ended (refresh()).
      ESP_LOGI(TAG, "%s: start_queue deferred: %s", this->name_.c_str(), this->block_reason_());
      this->deferred_start_ = true;
      this->deferred_cycle_ = false;
      this->deferred_.request(millis());
      return;
    }
    this->apply_deferred_();
    this->deferred_.cancel();
    this->deferred_start_ = false;
    this->deferred_cycle_ = false;
    this->cycle_run_ = false;
    ESP_LOGI(TAG, "%s: start queue", this->name_.c_str());
    this->queue_run_ = true;
    this->queue_idle_ms_ = millis();
    this->engine_->start_queue();
  }

  void full_cycle() {
    if (this->inhibited_) {
      ESP_LOGW(TAG, "%s: full_cycle refused: service mode is on", this->name_.c_str());
      return;
    }
    if (this->engine_->stopping()) {
      ESP_LOGI(TAG, "%s: full_cycle deferred: the group is still stopping, the cycle starts after it",
               this->name_.c_str());
      this->deferred_cycle_ = true;
      this->deferred_start_ = false;
      this->deferred_.request(millis());
      return;
    }
    this->deferred_cycle_ = false;
    ESP_LOGI(TAG, "%s: full cycle", this->name_.c_str());
    this->cycle_run_ = true;
    this->queue_run_ = true;
    this->queue_idle_ms_ = millis();
    this->engine_->start_cycle();
  }

  /// Service mode: while set, only SERVICE runs (the valve test) are accepted; stops are always allowed.
  void set_inhibit(bool inhibit) {
    this->inhibited_ = inhibit;
    ESP_LOGI(TAG, "%s: starts %s", this->name_.c_str(), inhibit ? "inhibited (service mode)" : "allowed");
    if (inhibit) {  // entering service mode settles the schedules like a STOP
      this->cancel_deferred_();
      this->stop_cb_.call();
    }
  }
  bool inhibited() const { return this->inhibited_; }

  void stop_all(bool clear_queue) {
    ESP_LOGI(TAG, "%s: stop all%s", this->name_.c_str(), clear_queue ? " (queue cleared)" : "");
    this->queue_run_ = false;
    this->cycle_run_ = false;
    this->stop_ms_ = millis() == 0 ? 1 : millis();
    this->cancel_deferred_();
    this->engine_->shutdown(clear_queue);
    this->stop_cb_.call();
  }

  /// Drops every queued zone of the group (a running zone keeps running) and any deferred queue start.
  void clear_queue() {
    this->engine_->read(this->input_);
    for (size_t zone = 0; zone < this->input_.zone_count && zone < MAX_ZONES; zone++) {
      if (this->input_.zones[zone].queued)
        this->engine_->remove_queued_zone(zone);
    }
    this->cancel_deferred_();
    ESP_LOGI(TAG, "%s: queue cleared", this->name_.c_str());
  }

  void reset_watchdog() {
    ESP_LOGI(TAG, "%s: reset watchdog", this->name_.c_str());
    this->engine_->reset_watchdog();
  }

  // ---- hub interface ----
  void setup() {
    this->zone_count_ = this->engine_->zone_count();
    if (this->zone_count_ > MAX_ZONES)
      ESP_LOGW(TAG, "%s: %u zones, only the first %u are modelled", this->name_.c_str(), (unsigned) this->zone_count_,
               (unsigned) MAX_ZONES);
    this->pref_ = global_preferences->make_preference<PersistBlob>(fnv1_hash("gp_history:" + this->key_));
    PersistBlob loaded;
    if (this->pref_.load(&loaded) && loaded.valid()) {
      this->blob_ = loaded;
      for (size_t i = 0; i < MAX_ZONES; i++)
        this->model_.restore_last(i, this->blob_.last[i].epoch, this->blob_.last[i].duration);
      ESP_LOGI(TAG, "%s: restored %u history entries", this->name_.c_str(), (unsigned) this->blob_.history.size());
    }
  }

  /// Reads the engine and updates the model; persists completed runs.
  void refresh(uint32_t now_ms, uint32_t now_epoch) {
    this->engine_->read(this->input_);
    for (size_t i = 0; i < this->input_.zone_count; i++)
      this->input_.start_source[i] = this->source_for_(i, now_ms);
    this->model_.refresh(now_ms, now_epoch, this->input_);
    const GroupSummary &s = this->model_.summary();
    if (s.running || s.queue_length > 0)
      this->queue_idle_ms_ = now_ms;
    else if (this->queue_run_ && (uint32_t) (now_ms - this->queue_idle_ms_) > QUEUE_RUN_GRACE_MS)
      this->queue_run_ = this->cycle_run_ = false;
    RunRecord record;
    bool changed = false;
    while (this->model_.take_completed(record)) {
      const bool stopped = this->stop_ms_ != 0 && (uint32_t) (now_ms - this->stop_ms_) < STOP_WINDOW_MS;
      changed = true;
      this->history_pushes_++;
      if (record.is_skip()) {  // a skip is a history entry only: not a "last watering", not a finished run
        this->blob_.history.push(HistoryEntry{record.epoch, 0, record.zone, static_cast<uint8_t>(Source::UNKNOWN),
                                              static_cast<uint8_t>(record.result), 0});
        ESP_LOGI(TAG, "%s: zone %u skipped%s", this->name_.c_str(), (unsigned) (record.zone + 1),
                 record.result == Result::SKIPPED_WET ? " (too wet)" : "");
        continue;
      }
      // a run ended by STOP inside the window reads "stopped"; a watchdog-ended run counts as done, like `completed`
      record.result = stopped ? Result::STOPPED : Result::DONE;
      this->blob_.history.push(HistoryEntry{record.epoch, record.duration, record.zone,
                                            static_cast<uint8_t>(record.source), static_cast<uint8_t>(record.result), 0});
      if (record.zone < MAX_ZONES && record.source != Source::SERVICE) {
        this->blob_.last[record.zone].epoch = record.epoch;
        this->blob_.last[record.zone].duration = record.duration;
      }
      ESP_LOGI(TAG, "%s: zone %u finished: %u s (%s)", this->name_.c_str(), (unsigned) (record.zone + 1),
               (unsigned) record.duration, source_word(record.source));
      this->finished_cb_.call(record.zone, record.source == Source::QUEUE && !stopped);
    }
    if (changed && !this->pref_.save(&this->blob_))
      ESP_LOGW(TAG, "%s: saving the history failed", this->name_.c_str());
    if (this->deferred_.update(s.running, now_ms)) {
      ESP_LOGI(TAG, "%s: the run has ended, queueing the deferred zones", this->name_.c_str());
      const bool start = this->deferred_start_;
      const bool cycle = this->deferred_cycle_;
      this->deferred_start_ = false;
      this->deferred_cycle_ = false;
      this->apply_deferred_();
      if (cycle)
        this->full_cycle();
      else if (start)
        this->start_queue();
    }
  }

  size_t zone_count() const { return this->zone_count_; }

  /// True while a `start_queue` waits for a running cycle / manual run to end (tests, debugging).
  bool start_deferred() const { return this->deferred_.pending(); }
  /// Number of enqueue requests waiting for the end of a run (tests, debugging).
  size_t deferred_enqueues() const { return this->deferred_enq_.size(); }

  /// Fires on every `stop_all` and when service mode is entered: schedules settle their pending zones.
  void add_on_stop_callback(std::function<void()> &&callback) { this->stop_cb_.add(std::move(callback)); }

  /// Fires when a zone's run ends: (0-based zone, completed). `completed` = a queue run (not manual / service) that
  /// ran to its end, not stopped by `stop_all` (schedules use it for their per-zone "done" marks).
  void add_on_zone_finished_callback(std::function<void(uint8_t, bool)> &&callback) {
    this->finished_cb_.add(std::move(callback));
  }

 protected:
  static constexpr uint32_t STOP_WINDOW_MS = 3000;
  static constexpr uint32_t INTENT_MS = 15000;
  static constexpr uint32_t QUEUE_RUN_GRACE_MS = 5000;

  /// A held-back enqueue: a zone mask + percent (`single` false) or one zone + seconds (`single` true).
  struct DeferredEnqueue {
    uint32_t mask;
    uint8_t pct;
    size_t zone;
    optional<uint32_t> seconds;
    bool single;
  };
  static constexpr size_t MAX_DEFERRED = 16;

  /// True when queueing / starting now would mix into a running cycle or a manual run (reads the engine). With
  /// `start` set, an engine that is still stopping also blocks (it would lose the start).
  bool run_blocks_queue_(bool start) {
    this->engine_->read(this->input_);
    bool busy = false;
    for (size_t i = 0; i < this->input_.zone_count && i < MAX_ZONES; i++)
      busy = busy || this->input_.zones[i].running;
    const bool stopping = start && this->engine_->stopping();
    this->block_stopping_ = stopping;
    return start_must_wait(busy, stopping, this->cycle_run_, this->queue_run_);
  }
  const char *block_reason_() const {
    return this->block_stopping_ ? "the group is still stopping, the queue starts after it"
                                 : "a run that is not a queue run is active, the queue starts after it";
  }

  void queue_now_(size_t zone, optional<uint32_t> seconds) {
    ESP_LOGI(TAG, "%s: enqueue zone %u", this->name_.c_str(), (unsigned) (zone + 1));
    this->engine_->queue_zone(zone, seconds);
  }

  /// Queues the held-back enqueue requests (in arrival order); nothing is started.
  void apply_deferred_() {
    std::vector<DeferredEnqueue> list;
    list.swap(this->deferred_enq_);
    for (const DeferredEnqueue &request : list) {
      if (request.single)
        this->enqueue_zone(request.zone, request.seconds);
      else
        this->enqueue_zones(request.mask, request.pct);
    }
  }

  /// A STOP / service mode / queue clear drops everything that waits for the end of a run.
  void cancel_deferred_() {
    this->deferred_.cancel();
    this->deferred_enq_.clear();
    this->deferred_start_ = false;
    this->deferred_cycle_ = false;
  }

  bool check_zone_(const char *what, size_t zone) const {
    if (zone < this->zone_count_ && zone < MAX_ZONES)
      return true;
    ESP_LOGW(TAG, "%s: %s: no zone %u (the group has %u)", this->name_.c_str(), what, (unsigned) (zone + 1),
             (unsigned) this->zone_count_);
    return false;
  }

  /// A requested run longer than the zone's maximum (run-duration number max) is cut to it.
  optional<uint32_t> clamp_(size_t zone, optional<uint32_t> seconds) const {
    const uint32_t max = this->engine_->max_run_seconds(zone);
    const optional<uint32_t> cut = clamp_run(seconds, max);
    if (cut != seconds)
      ESP_LOGW(TAG, "%s: zone %u: %u s cut to the maximum %u s", this->name_.c_str(), (unsigned) (zone + 1),
               (unsigned) *seconds, (unsigned) max);
    return cut;
  }

  Source source_for_(size_t zone, uint32_t now_ms) const {
    if (this->intent_[zone] != Source::UNKNOWN && (uint32_t) (now_ms - this->intent_ms_[zone]) < INTENT_MS)
      return this->intent_[zone];
    return this->queue_run_ ? Source::QUEUE : Source::UNKNOWN;
  }

  std::string key_, name_;
  std::unique_ptr<Engine> engine_;
  GpHub *hub_{nullptr};
  size_t zone_count_{0};
  GroupInput input_;
  GroupModel model_;
  PersistBlob blob_;
  uint32_t history_pushes_{0};  ///< entries added since boot (RAM only), for history_changed_since
  ESPPreferenceObject pref_;
  std::string last_status_;
  Source intent_[MAX_ZONES]{};
  uint32_t intent_ms_[MAX_ZONES]{};
  bool queue_run_{false};
  bool cycle_run_{false};  ///< the current run was started by full_cycle (start_queue would drop its rest)
  bool inhibited_{false};
  uint32_t stop_ms_{0};  ///< millis() of the last stop_all (0 = never)
  CallbackManager<void(uint8_t, bool)> finished_cb_;
  CallbackManager<void()> stop_cb_;
  DeferredStart deferred_;
  std::vector<DeferredEnqueue> deferred_enq_;
  bool deferred_start_{false};
  bool deferred_cycle_{false};  ///< a full_cycle waits for the engine to finish stopping
  bool block_stopping_{false};
  uint32_t queue_idle_ms_{0};
};

/// The hub: refreshes the groups, evaluates the built-in alert sources, owns the alert table.
class GpHub : public Component {
 public:
  void add_group(GpGroup *group) {
    group->set_hub(this);
    this->groups_.push_back(group);
  }
  void set_time(time::RealTimeClock *time) { this->time_ = time; }

  GpGroup *find_group(const std::string &key) {
    for (GpGroup *group : this->groups_) {
      if (group->key() == key)
        return group;
    }
    return nullptr;
  }
  size_t group_index(const GpGroup *group) const {
    for (size_t i = 0; i < this->groups_.size(); i++) {
      if (this->groups_[i] == group)
        return i;
    }
    return 0;
  }

  void setup() override {
    for (GpGroup *group : this->groups_)
      group->setup();
  }

  void dump_config() override {
    ESP_LOGCONFIG(TAG, "gp: %u group(s), clock %s", (unsigned) this->groups_.size(), this->time_ != nullptr ? "yes" : "no");
  }

  float get_setup_priority() const override { return setup_priority::LATE; }

  void loop() override {
    const uint32_t now = millis();
    if (this->started_ && (uint32_t) (now - this->last_refresh_) < REFRESH_MS)
      return;
    this->started_ = true;
    this->last_refresh_ = now;
    uint32_t epoch = 0;
    if (this->time_ != nullptr) {
      ESPTime t = this->time_->now();
      if (t.is_valid())
        epoch = static_cast<uint32_t>(t.timestamp);
    }
    for (GpGroup *group : this->groups_)
      group->refresh(now, epoch);
    if (this->started_alerts_ && (uint32_t) (now - this->last_alerts_) < 1000)
      return;
    this->started_alerts_ = true;
    this->last_alerts_ = now;
    this->evaluate_alerts_(now / 1000U, epoch != 0);
  }

  // ---- alerts ----
  void alert_raise(const char *key, Severity severity, const char *text, int group = -1) {
    if (this->alerts_.raise(key, severity, text, millis() / 1000U, group)) {
      ESP_LOGI(TAG, "alert %s: %s", key, text);
      this->changed_cb_.call();
    } else if (this->alerts_.overflow_count() != this->logged_overflow_) {
      this->logged_overflow_ = this->alerts_.overflow_count();
      ESP_LOGW(TAG, "alert table full, '%s' dropped", key);
    }
  }
  void alert_clear(const char *key) {
    if (this->alerts_.clear(key)) {
      ESP_LOGI(TAG, "alert %s cleared", key);
      this->changed_cb_.call();
    }
  }
  bool alert_active(const char *key) const { return this->alerts_.active(key); }
  /// True when the alert table changed since the revision stored in `seen` (for the alert strip poller); stores it.
  bool alerts_changed_since(uint32_t &seen) const {
    const bool changed = seen != this->alerts_.revision();
    seen = this->alerts_.revision();
    return changed;
  }
  const AlertTable &alerts() const { return this->alerts_; }
  /// Top alert text or "".
  std::string top_alert_text() const {
    const Alert *top = this->alerts_.top();
    return top == nullptr ? std::string() : std::string(top->text);
  }
  const char *top_alert_key() const {
    const Alert *top = this->alerts_.top();
    return top == nullptr ? "-" : top->key;
  }
  /// Top alert text when it changed since the last call, else nothing (for the "Alert" text sensor).
  optional<std::string> alert_text_changed() {
    std::string text = this->top_alert_text();
    if (this->alert_text_published_ && text == this->last_alert_text_)
      return {};
    this->alert_text_published_ = true;
    this->last_alert_text_ = text;
    return text;
  }
  void add_on_alert_change_callback(std::function<void()> &&callback) { this->changed_cb_.add(std::move(callback)); }

 protected:
  static constexpr uint32_t REFRESH_MS = 250;
  static constexpr uint32_t CLOCK_ALERT_AFTER_S = 300;

  void evaluate_alerts_(uint32_t now_s, bool clock_valid) {
    for (size_t gi = 0; gi < this->groups_.size(); gi++) {
      GpGroup *group = this->groups_[gi];
      char key[ALERT_KEY_LEN + 1];
      std::snprintf(key, sizeof(key), "wd:%s", group->key().c_str());
      const GroupSummary &s = group->summary();
      if (!s.watchdog_tripped) {
        this->alert_clear(key);
        continue;
      }
      int first = -1;
      size_t locked = 0;
      for (size_t z = 0; z < s.zone_count; z++) {
        if (group->zone(z).state == ZoneState::LOCKED) {
          if (first < 0)
            first = static_cast<int>(z);
          locked++;
        }
      }
      char text[ALERT_TEXT_LEN + 1];
      if (first < 0)
        std::snprintf(text, sizeof(text), "%s: watchdog tripped", group->name().c_str());
      else
        std::snprintf(text, sizeof(text), "%s: watchdog - %s locked%s", group->name().c_str(), group->zone((size_t) first).short_name,
                      locked > 1 ? "+" : "");
      this->alert_raise(key, Severity::ERROR, text, static_cast<int>(gi));
    }
    if (this->time_ != nullptr) {
      if (clock_valid)
        this->alert_clear("clock");
      else if (now_s >= CLOCK_ALERT_AFTER_S)
        this->alert_raise("clock", Severity::INFO, "Clock not set");
    }
  }

  std::vector<GpGroup *> groups_;
  time::RealTimeClock *time_{nullptr};
  AlertTable alerts_;
  CallbackManager<void()> changed_cb_;
  uint32_t last_refresh_{0}, last_alerts_{0}, logged_overflow_{0};
  bool started_{false}, started_alerts_{false};
  std::string last_alert_text_;
  bool alert_text_published_{false};
};

inline std::string GpGroup::debug_line() const {
  std::string out;
  const GroupSummary &s = this->model_.summary();
  for (size_t i = 0; i < s.zone_count; i++) {
    const ZoneView &z = this->model_.zone(i);
    char one[40];
    if (z.state == ZoneState::RUNNING || z.state == ZoneState::PAUSED)
      std::snprintf(one, sizeof(one), "%sB%u:%s(%u)", i == 0 ? "" : " ", (unsigned) (i + 1), state_word(z.state),
                    (unsigned) z.time_left.value_or(0));
    else if (z.state == ZoneState::QUEUED)
      std::snprintf(one, sizeof(one), "%sB%u:%s(%u)", i == 0 ? "" : " ", (unsigned) (i + 1), state_word(z.state),
                    (unsigned) z.queue_position.value_or(0));
    else
      std::snprintf(one, sizeof(one), "%sB%u:%s", i == 0 ? "" : " ", (unsigned) (i + 1), state_word(z.state));
    out += one;
  }
  char tail[48];
  std::snprintf(tail, sizeof(tail), " q=%u a=%s", (unsigned) s.queue_length,
                this->hub_ != nullptr ? this->hub_->top_alert_key() : "-");
  return out + tail;
}

// ------------------------------------------------------------------------------------------------ actions

/// Base of the group actions: the group is either fixed (`id`) or looked up by key at run time (hub + `group:`).
template<typename... Ts> class GroupAction : public Action<Ts...> {
 public:
  void set_group(GpGroup *group) { this->group_ = group; }
  void set_hub(GpHub *hub) { this->hub_ = hub; }
  TEMPLATABLE_VALUE(std::string, group_key)

 protected:
  GpGroup *resolve_(const Ts &...x) {
    if (this->group_ != nullptr)
      return this->group_;
    if (this->hub_ == nullptr)
      return nullptr;
    const std::string key = this->group_key_.value(x...);
    GpGroup *group = this->hub_->find_group(key);
    if (group == nullptr)
      ESP_LOGW(TAG, "no gp group '%s'", key.c_str());
    return group;
  }
  GpGroup *group_{nullptr};
  GpHub *hub_{nullptr};
};

template<typename... Ts> class RunZoneAction final : public GroupAction<Ts...> {
 public:
  TEMPLATABLE_VALUE(size_t, zone)
  TEMPLATABLE_VALUE(uint32_t, duration)  ///< seconds; 0 or unset = the zone's configured run duration
  void set_source(Source source) { this->source_ = source; }
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group == nullptr)
      return;
    optional<uint32_t> seconds;
    if (this->duration_.has_value() && this->duration_.value(x...) > 0)
      seconds = this->duration_.value(x...);
    group->run_zone(this->zone_.value(x...), seconds, this->source_);
  }

 protected:
  Source source_{Source::MANUAL};
};

template<typename... Ts> class EnqueueZoneAction final : public GroupAction<Ts...> {
 public:
  TEMPLATABLE_VALUE(size_t, zone)
  TEMPLATABLE_VALUE(uint32_t, duration)
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group == nullptr)
      return;
    optional<uint32_t> seconds;
    if (this->duration_.has_value() && this->duration_.value(x...) > 0)
      seconds = this->duration_.value(x...);
    group->enqueue_zone(this->zone_.value(x...), seconds);
  }
};

template<typename... Ts> class EnqueueZonesAction final : public GroupAction<Ts...> {
 public:
  TEMPLATABLE_VALUE(uint32_t, mask)
  TEMPLATABLE_VALUE(uint8_t, pct)
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->enqueue_zones(this->mask_.value(x...), this->pct_.has_value() ? this->pct_.value(x...) : 100);
  }
};

template<typename... Ts> class DequeueZoneAction final : public GroupAction<Ts...> {
 public:
  TEMPLATABLE_VALUE(size_t, zone)
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->dequeue_zone(this->zone_.value(x...));
  }
};

template<typename... Ts> class StartQueueAction final : public GroupAction<Ts...> {
 public:
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->start_queue();
  }
};

template<typename... Ts> class FullCycleAction final : public GroupAction<Ts...> {
 public:
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->full_cycle();
  }
};

template<typename... Ts> class ClearQueueAction final : public GroupAction<Ts...> {
 public:
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->clear_queue();
  }
};

template<typename... Ts> class StopAllAction final : public GroupAction<Ts...> {
 public:
  TEMPLATABLE_VALUE(bool, clear_queue)
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->stop_all(this->clear_queue_.has_value() && this->clear_queue_.value(x...));
  }
};

template<typename... Ts> class InhibitAction final : public GroupAction<Ts...> {
 public:
  TEMPLATABLE_VALUE(bool, state)
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->set_inhibit(this->state_.value(x...));
  }
};

template<typename... Ts> class ResetWatchdogAction final : public GroupAction<Ts...> {
 public:
  void play(const Ts &...x) override {
    GpGroup *group = this->resolve_(x...);
    if (group != nullptr)
      group->reset_watchdog();
  }
};

template<typename... Ts> class AlertRaiseAction final : public Action<Ts...> {
 public:
  explicit AlertRaiseAction(GpHub *hub) : hub_(hub) {}
  TEMPLATABLE_VALUE(std::string, key)
  TEMPLATABLE_VALUE(std::string, text)
  void set_severity(Severity severity) { this->severity_ = severity; }
  void play(const Ts &...x) override {
    this->hub_->alert_raise(this->key_.value(x...).c_str(), this->severity_, this->text_.value(x...).c_str());
  }

 protected:
  GpHub *hub_;
  Severity severity_{Severity::WARN};
};

template<typename... Ts> class AlertClearAction final : public Action<Ts...> {
 public:
  explicit AlertClearAction(GpHub *hub) : hub_(hub) {}
  TEMPLATABLE_VALUE(std::string, key)
  void play(const Ts &...x) override { this->hub_->alert_clear(this->key_.value(x...).c_str()); }

 protected:
  GpHub *hub_;
};

// ------------------------------------------------------------------------------------------------ conditions

template<typename... Ts> class ZoneRunningCondition final : public Condition<Ts...> {
 public:
  explicit ZoneRunningCondition(GpGroup *group) : group_(group) {}
  TEMPLATABLE_VALUE(size_t, zone)
  bool check(const Ts &...x) override { return this->group_->zone_running(this->zone_.value(x...)); }

 protected:
  GpGroup *group_;
};

template<typename... Ts> class AnyRunningCondition final : public Condition<Ts...> {
 public:
  explicit AnyRunningCondition(GpGroup *group) : group_(group) {}
  bool check(const Ts &...x) override { return this->group_->summary().running; }

 protected:
  GpGroup *group_;
};

template<typename... Ts> class WatchdogTrippedCondition final : public Condition<Ts...> {
 public:
  explicit WatchdogTrippedCondition(GpGroup *group) : group_(group) {}
  bool check(const Ts &...x) override { return this->group_->summary().watchdog_tripped; }

 protected:
  GpGroup *group_;
};

/// True while service mode (`gp.inhibit`) refuses starts: schedules use it to skip a due slot.
template<typename... Ts> class InhibitedCondition final : public Condition<Ts...> {
 public:
  explicit InhibitedCondition(GpGroup *group) : group_(group) {}
  bool check(const Ts &...x) override { return this->group_->inhibited(); }

 protected:
  GpGroup *group_;
};

template<typename... Ts> class AlertActiveCondition final : public Condition<Ts...> {
 public:
  explicit AlertActiveCondition(GpHub *hub) : hub_(hub) {}
  void set_key(const std::string &key) {
    this->key_ = key;
    this->any_ = false;
  }
  bool check(const Ts &...x) override { return this->hub_->alert_active(this->any_ ? nullptr : this->key_.c_str()); }

 protected:
  GpHub *hub_;
  std::string key_;
  bool any_{true};
};

/// `on_zone_finished` of a group: (zone 0-based, completed).
class ZoneFinishedTrigger : public Trigger<uint8_t, bool> {
 public:
  explicit ZoneFinishedTrigger(GpGroup *group) {
    group->add_on_zone_finished_callback([this](uint8_t zone, bool completed) { this->trigger(zone, completed); });
  }
};

/// `on_stop` of a group: a `stop_all` or entering service mode (no arguments).
class StopTrigger : public Trigger<> {
 public:
  explicit StopTrigger(GpGroup *group) {
    group->add_on_stop_callback([this]() { this->trigger(); });
  }
};

class AlertChangeTrigger : public Trigger<> {
 public:
  explicit AlertChangeTrigger(GpHub *hub) {
    hub->add_on_alert_change_callback([this]() { this->trigger(); });
  }
};

// ------------------------------------------------------------------------------------------------ zone switch

/// The per-zone switch in Home Assistant: on = run the zone (its configured duration), off = stop the group.
/// State follows the model; a command shows as ON at once (optimistic) for a few seconds, then the model wins.
class GpZoneSwitch : public switch_::Switch, public Component {
 public:
  void set_group(GpGroup *group) { this->group_ = group; }
  void set_zone(size_t zone) { this->zone_ = zone; }

  void setup() override { this->publish_state(false); }
  float get_setup_priority() const override { return setup_priority::LATE - 1.0f; }

  void loop() override {
    const bool running = this->group_ != nullptr && this->group_->zone_running(this->zone_);
    if (running == this->state)
      return;
    if (!running && (uint32_t) (millis() - this->command_ms_) < OPTIMISTIC_MS && this->state)
      return;  // just commanded on, the valve has not opened yet
    this->publish_state(running);
  }

  void dump_config() override { LOG_SWITCH("", "gp zone switch", this); }

 protected:
  static constexpr uint32_t OPTIMISTIC_MS = 8000;

  void write_state(bool state) override {
    if (this->group_ == nullptr)
      return;
    if (state) {
      this->command_ms_ = millis();
      this->publish_state(this->group_->run_zone(this->zone_, {}));
    } else {
      // always stop when the switch is on or the zone runs: an OFF right after ON (before the model shows RUNNING, or
      // during the engine's switching delay) must not let the valve open anyway
      if (this->state || this->group_->zone(this->zone_).state == ZoneState::RUNNING ||
          this->group_->zone(this->zone_).state == ZoneState::PAUSED)
        this->group_->stop_all(false);
      this->command_ms_ = 0;
      this->publish_state(false);
    }
  }

  GpGroup *group_{nullptr};
  size_t zone_{0};
  uint32_t command_ms_{0};
};

}  // namespace esphome::gp
