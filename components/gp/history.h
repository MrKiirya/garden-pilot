// gp — watering history ring and the flash blob (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The last HISTORY_LENGTH completed runs of a group plus the last run of every zone, as one fixed-size POD blob that the
// hub stores with the ESPHome preferences (one write per completed run; ESPHome batches the flash writes).
#pragma once

#include <cstddef>
#include <cstdint>

namespace esphome::gp {

inline constexpr size_t MAX_ZONES = 16;
inline constexpr size_t HISTORY_LENGTH = 100;

struct HistoryEntry {
  uint32_t epoch;     ///< start of the run, Unix seconds; 0 = the clock was not valid
  uint32_t duration;  ///< seconds the valve was open (a pause inside the run is not counted)
  uint8_t zone;       ///< 0-based zone index in the group
  uint8_t source;     ///< gp::Source
  uint16_t reserved;
};

template<size_t N> class History {
 public:
  void push(const HistoryEntry &entry) {
    this->entries[this->head] = entry;
    this->head = static_cast<uint16_t>((this->head + 1) % N);
    if (this->count < N)
      this->count++;
  }
  size_t size() const { return this->count; }
  /// 0 = the newest entry; out of range returns a zeroed entry.
  HistoryEntry at(size_t index) const {
    if (index >= this->count)
      return HistoryEntry{0, 0, 0, 0, 0};
    return this->entries[(this->head + N - 1 - index) % N];
  }
  bool consistent() const { return this->head < N && this->count <= N; }

  HistoryEntry entries[N]{};
  uint16_t head{0};
  uint16_t count{0};
};

struct LastRun {
  uint32_t epoch;
  uint32_t duration;
};

struct PersistBlob {
  static constexpr uint32_t MAGIC = 0x47503031;  // "GP01"
  uint32_t magic{MAGIC};
  History<HISTORY_LENGTH> history;
  LastRun last[MAX_ZONES]{};
  bool valid() const { return this->magic == MAGIC && this->history.consistent(); }
};

}  // namespace esphome::gp
