// gp — watering history ring and the flash blob (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The last HISTORY_LENGTH completed runs and skips of a group plus the last run of every zone, as one fixed-size POD blob that the
// hub stores with the ESPHome preferences (one write per completed run; ESPHome batches the flash writes).
#pragma once

#include <cstddef>
#include <cstdint>

namespace esphome::gp {

inline constexpr size_t MAX_ZONES = 16;
inline constexpr size_t HISTORY_LENGTH = 100;

/// How an entry ended. Stored as one byte taken from the former `reserved` field: entries written before it existed
/// have a zero byte and read as UNKNOWN (shown as "-"), so the blob size and magic did not change.
enum class Result : uint8_t { UNKNOWN = 0, DONE = 1, STOPPED = 2, SKIPPED_WET = 3, SKIPPED = 4 };

struct HistoryEntry {
  uint32_t epoch;     ///< start of the run, Unix seconds; 0 = the clock was not valid
  uint32_t duration;  ///< seconds the valve was open (a pause inside the run is not counted); 0 for a skip
  uint8_t zone;       ///< 0-based zone index in the group
  uint8_t source;     ///< gp::Source
  uint8_t result;     ///< gp::Result
  uint8_t reserved;   ///< keep zero
};
static_assert(sizeof(HistoryEntry) == 12, "HistoryEntry is part of the flash blob: do not change its size");

/// The entry's result; an unknown byte reads as UNKNOWN.
inline Result result_of(const HistoryEntry &entry) {
  return entry.result <= static_cast<uint8_t>(Result::SKIPPED) ? static_cast<Result>(entry.result) : Result::UNKNOWN;
}

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
      return HistoryEntry{0, 0, 0, 0, 0, 0};
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
static_assert(sizeof(PersistBlob) == 1336, "PersistBlob size is the flash layout: do not change it");

}  // namespace esphome::gp
