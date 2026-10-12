// garden_zones — watchdog core (new file, not part of upstream ESPHome).
// Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
//
// Pure, header-only, ESPHome-free: only the C++ standard library (C++17). Unit tested on the host compiler
// (tests/cpp/test_watchdog.cpp). The guard looks only at the REAL on/off state of the raw valve and pump switches and
// at the time; it knows nothing about the sprinkler state machine. It returns commands; watchdog.h executes them.
// Nothing here is persisted: a reboot clears every latch (the actuators come up off).
#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

namespace esphome::garden_zones::watchdog {

enum class Reason : uint8_t { MAX_ON_TIME, PUMP_MAX_ON_TIME, PUMP_IDLE, LOCKED_OUT, STILL_ON };

/// A forced-off command is repeated at most once per this time while the actuator is still on.
constexpr uint32_t RETRY_MS = 1000;

/// A zone limit of `DISABLED` (`max_on_time: never`) never trips. (Pump limits use an empty optional.)
constexpr uint32_t DISABLED = UINT32_MAX;

/// Continuous on-time since the last off->on edge seen. Wrap-safe (`now - since` in uint32_t).
class OnTimer {
 public:
  /// Returns true on an off->on edge (an actuator seen on at the first update counts as an edge).
  bool update(bool on, uint32_t now) {
    const bool rising = on && !this->on_;
    if (rising)
      this->since_ = now;
    this->on_ = on;
    return rising;
  }
  bool on() const { return this->on_; }
  uint32_t on_for(uint32_t now) const { return this->on_ ? now - this->since_ : 0; }
  /// Times an actuator that is still on from `now`.
  void restart(uint32_t now) {
    if (this->on_)
      this->since_ = now;
  }

 private:
  bool on_{false};
  uint32_t since_{0};
};

struct Command {
  enum Kind { FORCE_OFF_ZONE, FORCE_OFF_PUMP, SHUTDOWN_LANE_OF_ZONE, SHUTDOWN_GROUP };
  Kind kind;
  int zone;  ///< zone number, -1 for the pump / the whole group
  Reason reason;
  bool new_trip;  ///< true only on the first command of a trip
};

class GroupGuard {
 public:
  GroupGuard(std::vector<uint32_t> zone_max_ms, std::optional<uint32_t> pump_max_ms, std::optional<uint32_t> pump_idle_ms)
      : zone_max_ms_(std::move(zone_max_ms)), pump_max_ms_(pump_max_ms), pump_idle_ms_(pump_idle_ms) {
    this->zones_.resize(this->zone_max_ms_.size());
    this->rising_.assign(this->zones_.size(), false);
    this->commands_.reserve(2 * this->zones_.size() + 4);
  }

  /// The returned list is a member buffer (no heap allocation per call once warmed up): valid until the next update().
  const std::vector<Command> &update(const std::vector<bool> &zones_on, std::optional<bool> pump_on, uint32_t now) {
    std::vector<Command> &commands = this->commands_;
    std::vector<bool> &rising = this->rising_;
    commands.clear();
    bool any_zone_on = false;
    for (size_t i = 0; i < this->zones_.size(); i++) {
      const bool on = i < zones_on.size() && zones_on[i];
      rising[i] = this->zones_[i].timer.update(on, now);
      any_zone_on = any_zone_on || on;
    }
    bool pump_rising = false;
    if (pump_on.has_value()) {
      pump_rising = this->pump_.timer.update(*pump_on, now);
      const bool idle = *pump_on && !any_zone_on;
      if (idle && !this->idle_active_)
        this->idle_since_ = now;
      this->idle_active_ = idle;
    } else {
      this->idle_active_ = false;
    }

    // pump first: a pump trip locks the whole group and covers the zones that are on
    if (pump_on.has_value() && !this->pump_.locked) {
      std::optional<Reason> reason;
      if (this->pump_max_ms_.has_value() && this->pump_.timer.on_for(now) > *this->pump_max_ms_)
        reason = Reason::PUMP_MAX_ON_TIME;
      else if (this->pump_idle_ms_.has_value() && this->idle_active_ && now - this->idle_since_ > *this->pump_idle_ms_)
        reason = Reason::PUMP_IDLE;
      if (reason.has_value()) {
        commands.push_back(Command{Command::SHUTDOWN_GROUP, -1, *reason, true});
        for (size_t i = 0; i < this->zones_.size(); i++) {
          if (this->zones_[i].timer.on()) {
            commands.push_back(Command{Command::FORCE_OFF_ZONE, static_cast<int>(i), *reason, false});
            this->zones_[i].forced = true;
            this->zones_[i].forced_at = now;
          }
          this->zones_[i].locked = true;
        }
        commands.push_back(Command{Command::FORCE_OFF_PUMP, -1, *reason, false});
        this->pump_.locked = true;
        this->pump_.forced = true;
        this->pump_.forced_at = now;
      }
    }

    for (size_t i = 0; i < this->zones_.size(); i++) {
      Actuator &zone = this->zones_[i];
      if (!zone.timer.on())
        continue;
      const int number = static_cast<int>(i);
      if (!zone.locked) {
        if (this->zone_max_ms_[i] != DISABLED && zone.timer.on_for(now) > this->zone_max_ms_[i]) {
          commands.push_back(Command{Command::SHUTDOWN_LANE_OF_ZONE, number, Reason::MAX_ON_TIME, true});
          commands.push_back(Command{Command::FORCE_OFF_ZONE, number, Reason::MAX_ON_TIME, false});
          zone.locked = true;
          zone.forced = true;
          zone.forced_at = now;
        }
      } else if (rising[i] || !zone.forced) {
        commands.push_back(Command{Command::SHUTDOWN_LANE_OF_ZONE, number, Reason::LOCKED_OUT, false});
        commands.push_back(Command{Command::FORCE_OFF_ZONE, number, Reason::LOCKED_OUT, false});
        zone.forced = true;
        zone.forced_at = now;
      } else if (now - zone.forced_at >= RETRY_MS) {
        commands.push_back(Command{Command::FORCE_OFF_ZONE, number, Reason::STILL_ON, false});
        zone.forced_at = now;
      }
    }

    if (pump_on.has_value() && this->pump_.locked && this->pump_.timer.on()) {
      if (pump_rising || !this->pump_.forced) {
        commands.push_back(Command{Command::FORCE_OFF_PUMP, -1, Reason::LOCKED_OUT, false});
        this->pump_.forced = true;
        this->pump_.forced_at = now;
      } else if (now - this->pump_.forced_at >= RETRY_MS) {
        commands.push_back(Command{Command::FORCE_OFF_PUMP, -1, Reason::STILL_ON, false});
        this->pump_.forced_at = now;
      }
    }
    return commands;
  }

  bool zone_locked(size_t zone) const { return zone < this->zones_.size() && this->zones_[zone].locked; }
  bool pump_locked() const { return this->pump_.locked; }
  /// Continuous on-time of an actuator (for log messages); 0 when it is off.
  uint32_t zone_on_for(size_t zone, uint32_t now) const {
    return zone < this->zones_.size() ? this->zones_[zone].timer.on_for(now) : 0;
  }
  uint32_t pump_on_for(uint32_t now) const { return this->pump_.timer.on_for(now); }
  bool tripped() const {
    if (this->pump_.locked)
      return true;
    for (const Actuator &zone : this->zones_) {
      if (zone.locked)
        return true;
    }
    return false;
  }

  /// Clears every latch; actuators that are still on are timed from `now`.
  void reset(uint32_t now) {
    for (Actuator &zone : this->zones_) {
      zone.locked = false;
      zone.forced = false;
      zone.timer.restart(now);
    }
    this->pump_.locked = false;
    this->pump_.forced = false;
    this->pump_.timer.restart(now);
    if (this->idle_active_)
      this->idle_since_ = now;
  }

 private:
  struct Actuator {
    OnTimer timer;
    bool locked{false};
    bool forced{false};  ///< a forced off was issued since the latch was set
    uint32_t forced_at{0};
  };

  std::vector<uint32_t> zone_max_ms_;
  std::optional<uint32_t> pump_max_ms_;
  std::optional<uint32_t> pump_idle_ms_;
  std::vector<Actuator> zones_;
  Actuator pump_;
  bool idle_active_{false};
  uint32_t idle_since_{0};
  std::vector<bool> rising_;
  std::vector<Command> commands_;
};

}  // namespace esphome::garden_zones::watchdog
