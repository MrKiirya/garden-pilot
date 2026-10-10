// garden_zones — group watchdog (new file, not part of upstream ESPHome).
// Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
//
// One watchdog per group. It polls the REAL state of the raw valve switches and the pump switch in its own loop()
// (never disabled), independent of the sprinkler state machine and its run durations, and forces an actuator off when
// watchdog_core.h says so. A trip locks the zone (or the whole group for a pump trip) until reset(). Nothing is
// persisted: after a reboot the actuators come up off and the latches are clear.
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "esphome/components/switch/switch.h"
#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "sprinkler.h"
#include "watchdog_core.h"

namespace esphome::garden_zones {

inline constexpr const char *WATCHDOG_TAG = "garden_zones.watchdog";
/// LOCKED_OUT / STILL_ON are logged at most this often per actuator.
inline constexpr uint32_t WATCHDOG_LOG_INTERVAL_MS = 10000;

class GroupWatchdog : public Component {
 public:
  explicit GroupWatchdog(std::string group_name) : group_(std::move(group_name)) {}

  /// Zones are registered in group order (zone number = call order).
  void add_zone(switch_::Switch *valve, Sprinkler *lane, std::string label, uint32_t max_on_ms) {
    this->zones_.push_back(Zone{valve, lane, std::move(label), max_on_ms, 0, false});
  }
  void set_pump(switch_::Switch *pump, uint32_t max_on_ms, uint32_t idle_ms) {
    this->pump_ = pump;
    this->pump_max_ms_ = max_on_ms;
    this->pump_idle_ms_ = idle_ms;
  }
  void add_on_trip_callback(std::function<void(int, const std::string &)> &&callback) {
    this->trip_callbacks_.push_back(std::move(callback));
  }

  float get_setup_priority() const override { return setup_priority::DATA; }

  void setup() override {
    std::vector<uint32_t> limits;
    for (Zone &zone : this->zones_) {
      limits.push_back(zone.max_on_ms);
      zone.valve->turn_off();
    }
    std::optional<uint32_t> pump_max, pump_idle;
    if (this->pump_ != nullptr) {
      if (this->pump_max_ms_ != watchdog::DISABLED)
        pump_max = this->pump_max_ms_;
      if (this->pump_idle_ms_ != watchdog::DISABLED)
        pump_idle = this->pump_idle_ms_;
      this->pump_->turn_off();
    }
    this->guard_.emplace(std::move(limits), pump_max, pump_idle);
  }

  void dump_config() override {
    ESP_LOGCONFIG(WATCHDOG_TAG, "Watchdog of group '%s': %zu zones%s", this->group_.c_str(), this->zones_.size(),
                  this->pump_ != nullptr ? ", pump" : "");
    for (size_t i = 0; i < this->zones_.size(); i++) {
      if (this->zones_[i].max_on_ms == watchdog::DISABLED)
        ESP_LOGW(WATCHDOG_TAG, "group '%s' zone %zu ('%s'): max_on_time never - watchdog disabled by config",
                 this->group_.c_str(), i, this->zones_[i].label.c_str());
      else
        ESP_LOGCONFIG(WATCHDOG_TAG, "  zone %zu max_on_time: %" PRIu32 " s", i, this->zones_[i].max_on_ms / 1000);
    }
    if (this->pump_ != nullptr) {
      if (this->pump_max_ms_ == watchdog::DISABLED)
        ESP_LOGW(WATCHDOG_TAG, "group '%s' pump: pump_max_on_time never - watchdog disabled by config",
                 this->group_.c_str());
      else
        ESP_LOGCONFIG(WATCHDOG_TAG, "  pump_max_on_time: %" PRIu32 " s", this->pump_max_ms_ / 1000);
      if (this->pump_idle_ms_ == watchdog::DISABLED)
        ESP_LOGW(WATCHDOG_TAG, "group '%s' pump: pump_idle_timeout never - watchdog disabled by config",
                 this->group_.c_str());
      else
        ESP_LOGCONFIG(WATCHDOG_TAG, "  pump_idle_timeout: %" PRIu32 " s", this->pump_idle_ms_ / 1000);
    }
  }

  void loop() override {
    if (!this->guard_.has_value())
      return;
    const uint32_t now = millis();
    this->zones_on_.resize(this->zones_.size());
    for (size_t i = 0; i < this->zones_.size(); i++)
      this->zones_on_[i] = this->zones_[i].valve->state;
    std::optional<bool> pump_on;
    if (this->pump_ != nullptr)
      pump_on = this->pump_->state;
    for (const watchdog::Command &command : this->guard_->update(this->zones_on_, pump_on, now))
      this->execute_(command, now);
  }

  bool zone_locked(size_t zone) const { return this->guard_.has_value() && this->guard_->zone_locked(zone); }
  bool tripped() const { return this->guard_.has_value() && this->guard_->tripped(); }

  /// Clears every latch of the group (the actuators that are still on are timed from now).
  void reset() {
    if (this->guard_.has_value())
      this->guard_->reset(millis());
    ESP_LOGI(WATCHDOG_TAG, "group '%s': watchdog reset, lockouts cleared", this->group_.c_str());
  }

 protected:
  struct Zone {
    switch_::Switch *valve;
    Sprinkler *lane;
    std::string label;
    uint32_t max_on_ms;
    uint32_t last_log;
    bool logged;
  };

  static const char *reason_name_(watchdog::Reason reason) {
    switch (reason) {
      case watchdog::Reason::MAX_ON_TIME:
        return "max_on_time";
      case watchdog::Reason::PUMP_MAX_ON_TIME:
        return "pump_max_on_time";
      case watchdog::Reason::PUMP_IDLE:
        return "pump_idle";
      case watchdog::Reason::LOCKED_OUT:
        return "locked_out";
      case watchdog::Reason::STILL_ON:
        return "still_on";
    }
    return "unknown";
  }

  bool may_log_(Zone &zone, uint32_t now) {
    if (zone.logged && now - zone.last_log < WATCHDOG_LOG_INTERVAL_MS)
      return false;
    zone.logged = true;
    zone.last_log = now;
    return true;
  }
  bool may_log_pump_(uint32_t now) {
    if (this->pump_logged_ && now - this->pump_last_log_ < WATCHDOG_LOG_INTERVAL_MS)
      return false;
    this->pump_logged_ = true;
    this->pump_last_log_ = now;
    return true;
  }

  void fire_(int zone, watchdog::Reason reason) {
    const std::string name = reason_name_(reason);
    for (auto &callback : this->trip_callbacks_)
      callback(zone, name);
  }

  void execute_(const watchdog::Command &command, uint32_t now) {
    using Kind = watchdog::Command::Kind;
    switch (command.kind) {
      case Kind::SHUTDOWN_LANE_OF_ZONE: {
        Zone &zone = this->zones_[command.zone];
        if (command.new_trip) {
          ESP_LOGE(WATCHDOG_TAG,
                   "group '%s' zone %d ('%s') on for %" PRIu32 " s > max_on_time %" PRIu32 " s: forced off, zone locked",
                   this->group_.c_str(), command.zone, zone.label.c_str(),
                   this->guard_->zone_on_for(command.zone, now) / 1000, zone.max_on_ms / 1000);
          this->fire_(command.zone, command.reason);
        }
        zone.lane->shutdown(false);  // the queue is kept; nothing restarts by itself
        break;
      }
      case Kind::SHUTDOWN_GROUP: {
        if (command.new_trip) {
          if (command.reason == watchdog::Reason::PUMP_IDLE)
            ESP_LOGE(WATCHDOG_TAG,
                     "group '%s' pump on for %" PRIu32 " s with no open valve > pump_idle_timeout %" PRIu32
                     " s: group shut down, pump and zones locked",
                     this->group_.c_str(), this->guard_->pump_on_for(now) / 1000, this->pump_idle_ms_ / 1000);
          else
            ESP_LOGE(WATCHDOG_TAG,
                     "group '%s' pump on for %" PRIu32 " s > pump_max_on_time %" PRIu32
                     " s: group shut down, pump and zones locked",
                     this->group_.c_str(), this->guard_->pump_on_for(now) / 1000, this->pump_max_ms_ / 1000);
          this->fire_(-1, command.reason);
        }
        for (Zone &zone : this->zones_)
          zone.lane->shutdown(false);
        break;
      }
      case Kind::FORCE_OFF_ZONE: {
        Zone &zone = this->zones_[command.zone];
        if (command.reason == watchdog::Reason::LOCKED_OUT) {
          if (this->may_log_(zone, now))
            ESP_LOGW(WATCHDOG_TAG, "group '%s' zone %d ('%s') is locked by the watchdog: forced off",
                     this->group_.c_str(), command.zone, zone.label.c_str());
        } else if (command.reason == watchdog::Reason::STILL_ON) {
          if (this->may_log_(zone, now))
            ESP_LOGE(WATCHDOG_TAG, "group '%s' zone %d ('%s') still ON after a forced off: stuck relay?",
                     this->group_.c_str(), command.zone, zone.label.c_str());
        }
        zone.valve->turn_off();
        break;
      }
      case Kind::FORCE_OFF_PUMP: {
        if (command.reason == watchdog::Reason::LOCKED_OUT) {
          if (this->may_log_pump_(now))
            ESP_LOGW(WATCHDOG_TAG, "group '%s' pump is locked by the watchdog: forced off", this->group_.c_str());
        } else if (command.reason == watchdog::Reason::STILL_ON) {
          if (this->may_log_pump_(now))
            ESP_LOGE(WATCHDOG_TAG, "group '%s' pump still ON after a forced off: stuck relay?", this->group_.c_str());
        }
        this->pump_->turn_off();
        break;
      }
    }
  }

  std::string group_;
  std::vector<Zone> zones_;
  switch_::Switch *pump_{nullptr};
  uint32_t pump_max_ms_{0};
  uint32_t pump_idle_ms_{0};
  std::optional<watchdog::GroupGuard> guard_;
  std::vector<bool> zones_on_;  // reused every loop() so the poll does not allocate
  std::vector<std::function<void(int, const std::string &)>> trip_callbacks_;
  uint32_t pump_last_log_{0};
  bool pump_logged_{false};
};

class WatchdogTripTrigger : public Trigger<int, std::string> {
 public:
  explicit WatchdogTripTrigger(GroupWatchdog *watchdog) {
    watchdog->add_on_trip_callback([this](int zone, const std::string &reason) { this->trigger(zone, reason); });
  }
};

}  // namespace esphome::garden_zones
