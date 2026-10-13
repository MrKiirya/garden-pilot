// garden_zones — adapter that serves a group to the `gp` layer (new file, not part of upstream ESPHome).
// Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
//
// Implements gp::Engine (components/gp/engine.h, MIT) over a GardenZonesGroup. The file is compiled only when the gp
// component is part of the build; the gp component never includes anything from this directory.
#pragma once

#if __has_include("esphome/components/gp/engine.h")

#include <algorithm>
#include <cstring>

#include "esphome/components/gp/engine.h"
#include "group.h"

namespace esphome::garden_zones {

class GardenZonesEngine final : public gp::Engine {
 public:
  explicit GardenZonesEngine(GardenZonesGroup *group) : group_(group) {}

  size_t zone_count() const override { return this->group_->zone_count(); }

  bool zone_locked(size_t zone) const override { return this->group_->zone_locked(zone); }

  void read(gp::GroupInput &in) override {
    const size_t count = std::min(this->group_->zone_count(), gp::MAX_ZONES);
    in.zone_count = count;
    const std::vector<size_t> active = this->group_->active_zones();
    const std::vector<size_t> queued = this->group_->queued_zones();
    for (size_t zone = 0; zone < count; zone++) {
      gp::ZoneInput &z = in.zones[zone];
      z = gp::ZoneInput{};
      z.name = this->group_->zone_name(zone);
      z.locked = this->group_->zone_locked(zone);
      z.running = std::find(active.begin(), active.end(), zone) != active.end();
      z.paused = this->group_->zone_paused(zone);
      z.enabled = this->group_->zone_enabled(zone);
      z.run_duration = this->group_->zone_run_duration(zone);
      auto left = this->group_->time_remaining_zone(zone);
      z.has_time_left = left.has_value();
      z.time_left = left.value_or(0);
      uint32_t stamp = 0;
      const char *text = "";
      z.has_skip = this->group_->last_skip(zone, stamp, text);
      z.skip_stamp = stamp;
      z.skip_text = text;
      // the engine's own reason texts: "soil moisture X > Y" = too wet, "soil sensor unavailable" = a generic skip
      z.skip_wet = z.has_skip && std::strncmp(text, "soil moisture", 13) == 0;
    }
    in.active_count = 0;
    for (size_t zone : active) {
      if (zone < count && in.active_count < gp::MAX_ZONES)
        in.active[in.active_count++] = zone;
    }
    in.queue_count = 0;
    for (size_t zone : queued) {
      if (zone >= count || in.queue_count >= gp::MAX_ZONES)
        continue;
      in.zones[zone].queued = true;
      in.zones[zone].queue_pos = static_cast<int>(in.queue_count);
      in.queue[in.queue_count++] = zone;
    }
    in.queue_time = this->group_->queue_time();
    in.auto_advance = this->group_->auto_advance();
    in.watchdog_tripped = this->group_->watchdog_tripped();
    auto total = this->group_->time_remaining();
    in.has_total_left = total.has_value();
    in.total_left = total.value_or(0);
  }

  uint32_t max_run_seconds(size_t zone) const override { return this->group_->zone_max_run(zone); }

  bool stopping() const override { return this->group_->any_lane_stopping(); }

  void run_zone(size_t zone, std::optional<uint32_t> seconds) override { this->group_->run_zone(zone, seconds); }
  void queue_zone(size_t zone, std::optional<uint32_t> seconds) override { this->group_->queue_zone(zone, seconds); }
  void remove_queued_zone(size_t zone) override { this->group_->remove_queued_zone(zone); }
  void start_queue() override { this->group_->start_queue(); }
  void start_cycle() override { this->group_->start_cycle(); }
  void shutdown(bool clear_queue) override {
    this->group_->shutdown();
    if (clear_queue)
      this->group_->clear_queue();
  }
  void reset_watchdog() override { this->group_->reset_watchdog(); }

 protected:
  GardenZonesGroup *group_;
};

}  // namespace esphome::garden_zones

#endif  // __has_include gp
