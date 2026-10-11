// gp — the engine interface (pure C++17, no ESPHome includes).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The gp component never includes an engine header: it talks to the irrigation engine only through this interface.
// An adapter implements it over one engine group (today `garden_zones`, see components/garden_zones/gp_engine.h).
// Swapping the engine = writing a new adapter and adding one option to the `gp` group schema. Zones are addressed by
// their 0-based index inside the group.
#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>

#include "zone_model.h"

namespace esphome::gp {

class Engine {
 public:
  virtual ~Engine() = default;

  /// Number of zones of the group.
  virtual size_t zone_count() const = 0;
  /// Fills `in` with the engine's current state (zones, active list, queue in run order, queue time, flags).
  /// Must set `in.zone_count`; the caller sets `in.start_source`.
  virtual void read(GroupInput &in) = 0;
  /// True when the zone is locked by the watchdog (a run would be refused).
  virtual bool zone_locked(size_t zone) const = 0;

  virtual void run_zone(size_t zone, std::optional<uint32_t> seconds) = 0;
  virtual void queue_zone(size_t zone, std::optional<uint32_t> seconds) = 0;
  virtual void remove_queued_zone(size_t zone) = 0;
  virtual void start_queue() = 0;
  virtual void start_cycle() = 0;
  /// Stops every zone of the group (and, with `clear_queue`, drops the queue).
  virtual void shutdown(bool clear_queue) = 0;
  virtual void reset_watchdog() = 0;
};

}  // namespace esphome::gp
