// garden_zones — queue helpers (new file, not part of upstream ESPHome).
// Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
//
// Pure, header-only, ESPHome-free: only the C++ standard library (C++17). Unit tested on the host compiler
// (tests/cpp/test_queue_ops.cpp). The functions operate on the upstream queue layout: a vector of items with
// `valve_number` and `run_duration`, stored REVERSED (queue_valve() inserts at begin(); the next valve to run
// is back()).
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <type_traits>
#include <vector>

namespace esphome::garden_zones::queue_ops {

constexpr size_t SNAPSHOT_MAX_ENTRIES = 32;
constexpr uint8_t SNAPSHOT_VERSION = 1;

/// Valve numbers in run order (index 0 runs next).
template<typename Items> std::vector<size_t> run_order(const Items &items) {
  std::vector<size_t> order;
  order.reserve(items.size());
  for (auto it = items.rbegin(); it != items.rend(); ++it)
    order.push_back(it->valve_number);
  return order;
}

template<typename Items> bool contains(const Items &items, size_t valve_number) {
  return std::any_of(items.begin(), items.end(),
                     [valve_number](const typename Items::value_type &i) { return i.valve_number == valve_number; });
}

/// Removes every entry of `valve_number`; returns how many were removed. Order of the rest is kept.
template<typename Items> size_t remove_all(Items &items, size_t valve_number) {
  size_t before = items.size();
  items.erase(std::remove_if(items.begin(), items.end(),
                             [valve_number](const typename Items::value_type &i) { return i.valve_number == valve_number; }),
              items.end());
  return before - items.size();
}

template<typename Item> struct PopResult {
  std::optional<Item> item;       ///< first enabled entry in run order, if any
  std::vector<size_t> dropped;    ///< valve numbers of disabled entries removed on the way
};

/// Pops entries in run order until one whose valve is enabled is found. Disabled entries are removed and reported.
template<typename Items, typename IsEnabled> PopResult<typename Items::value_type> pop_next_enabled(Items &items, IsEnabled is_enabled) {
  PopResult<typename Items::value_type> result;
  while (!items.empty()) {
    typename Items::value_type entry = items.back();
    items.pop_back();
    if (is_enabled(entry.valve_number)) {
      result.item = entry;
      break;
    }
    result.dropped.push_back(entry.valve_number);
  }
  return result;
}

/// Fixed-size, trivially copyable snapshot of the queue for a preference slot. Entries are in run order.
struct QueueSnapshot {
  uint8_t version;
  uint8_t valve_count;
  uint8_t entry_count;
  uint8_t truncated;
  uint8_t valve[SNAPSHOT_MAX_ENTRIES];
  uint32_t duration[SNAPSHOT_MAX_ENTRIES];
};

template<typename Items> QueueSnapshot make_snapshot(const Items &items, size_t valve_count) {
  QueueSnapshot snapshot{};
  snapshot.version = SNAPSHOT_VERSION;
  snapshot.valve_count = static_cast<uint8_t>(valve_count);
  size_t n = 0;
  for (auto it = items.rbegin(); it != items.rend(); ++it) {
    if (n >= SNAPSHOT_MAX_ENTRIES) {
      snapshot.truncated = 1;
      break;
    }
    snapshot.valve[n] = static_cast<uint8_t>(it->valve_number);
    snapshot.duration[n] = static_cast<uint32_t>(it->run_duration);
    n++;
  }
  snapshot.entry_count = static_cast<uint8_t>(n);
  return snapshot;
}

/// Rebuilds the (reversed) queue vector; empty optional when the snapshot is not valid for this controller.
template<typename Item> std::optional<std::vector<Item>> restore_snapshot(const QueueSnapshot &snapshot, size_t valve_count) {
  if (snapshot.version != SNAPSHOT_VERSION || snapshot.valve_count != valve_count ||
      snapshot.entry_count > SNAPSHOT_MAX_ENTRIES)
    return std::nullopt;
  std::vector<Item> items;
  items.reserve(snapshot.entry_count);
  for (size_t i = 0; i < snapshot.entry_count; i++) {
    if (snapshot.valve[i] >= valve_count)
      return std::nullopt;
    // run order index 0 must end up at back(), so insert each next entry at begin()
    items.insert(items.begin(), Item{snapshot.valve[i], snapshot.duration[i]});
  }
  return items;
}

enum class AfterManualRun { RESUME_PAUSED, GO_IDLE };

/// What the controller does when a manual run ends.
inline AfterManualRun after_manual_run(bool resume_pending, bool user_paused) {
  return (resume_pending && !user_paused) ? AfterManualRun::RESUME_PAUSED : AfterManualRun::GO_IDLE;
}

}  // namespace esphome::garden_zones::queue_ops
