// garden_zones — lane helpers (new file, not part of upstream ESPHome).
// Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
//
// Pure, header-only, ESPHome-free: only the C++ standard library (C++17). Unit tested on the host compiler
// (tests/cpp/test_lanes.cpp). A group of zones is served by one or more "lanes" (one controller each); a zone
// is addressed by its number inside the group and routed to (lane, valve index inside that lane).
#pragma once

#include <algorithm>
#include <cstddef>
#include <optional>
#include <utility>
#include <vector>

namespace esphome::garden_zones::lanes {

struct ZoneRef {
  size_t lane;
  size_t valve;
};

class LaneMap {
 public:
  LaneMap() = default;
  explicit LaneMap(std::vector<ZoneRef> zones) : zones_(std::move(zones)) {
    for (const ZoneRef &ref : this->zones_)
      this->lane_count_ = std::max(this->lane_count_, ref.lane + 1);
  }

  size_t zone_count() const { return this->zones_.size(); }
  size_t lane_count() const { return this->lane_count_; }

  std::optional<ZoneRef> route(size_t zone) const {
    if (zone >= this->zones_.size())
      return std::nullopt;
    return this->zones_[zone];
  }

  std::optional<size_t> zone_of(size_t lane, size_t valve) const {
    for (size_t zone = 0; zone < this->zones_.size(); zone++) {
      if (this->zones_[zone].lane == lane && this->zones_[zone].valve == valve)
        return zone;
    }
    return std::nullopt;
  }

  /// Every lane's valves are exactly 0..k-1 (no duplicate, no gap), no unused lane between used lanes, not empty.
  static bool valid(const std::vector<ZoneRef> &table) {
    if (table.empty())
      return false;
    size_t lanes = 0;
    for (const ZoneRef &ref : table)
      lanes = std::max(lanes, ref.lane + 1);
    for (size_t lane = 0; lane < lanes; lane++) {
      std::vector<bool> seen;
      for (const ZoneRef &ref : table) {
        if (ref.lane != lane)
          continue;
        if (ref.valve >= table.size())
          return false;
        if (seen.size() <= ref.valve)
          seen.resize(ref.valve + 1, false);
        if (seen[ref.valve])
          return false;
        seen[ref.valve] = true;
      }
      if (seen.empty())
        return false;
      if (!std::all_of(seen.begin(), seen.end(), [](bool b) { return b; }))
        return false;
    }
    return true;
  }

 private:
  std::vector<ZoneRef> zones_;
  size_t lane_count_{0};
};

/// Interleaves the lanes' queues: entry 0 of every lane (lane index ascending), then entry 1, ...
/// `per_lane_run_orders[lane]` holds valve indices in run order; the result is zone numbers.
inline std::vector<size_t> round_order(const std::vector<std::vector<size_t>> &per_lane_run_orders,
                                       const LaneMap &map) {
  std::vector<size_t> result;
  size_t longest = 0;
  for (const auto &order : per_lane_run_orders)
    longest = std::max(longest, order.size());
  for (size_t position = 0; position < longest; position++) {
    for (size_t lane = 0; lane < per_lane_run_orders.size(); lane++) {
      if (position >= per_lane_run_orders[lane].size())
        continue;
      auto zone = map.zone_of(lane, per_lane_run_orders[lane][position]);
      if (zone.has_value())
        result.push_back(*zone);
    }
  }
  return result;
}

/// Lane indices whose queue is not empty.
inline std::vector<size_t> lanes_to_start(const std::vector<size_t> &per_lane_queue_sizes) {
  std::vector<size_t> result;
  for (size_t lane = 0; lane < per_lane_queue_sizes.size(); lane++) {
    if (per_lane_queue_sizes[lane] > 0)
      result.push_back(lane);
  }
  return result;
}

/// Zone numbers whose valve is active (`per_lane_active_valve[lane]` = active valve index or none), ascending.
inline std::vector<size_t> active_zones(const std::vector<std::optional<size_t>> &per_lane_active_valve,
                                        const LaneMap &map) {
  std::vector<size_t> result;
  for (size_t lane = 0; lane < per_lane_active_valve.size(); lane++) {
    if (!per_lane_active_valve[lane].has_value())
      continue;
    auto zone = map.zone_of(lane, *per_lane_active_valve[lane]);
    if (zone.has_value())
      result.push_back(*zone);
  }
  std::sort(result.begin(), result.end());
  return result;
}

}  // namespace esphome::garden_zones::lanes
