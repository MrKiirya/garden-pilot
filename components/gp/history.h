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
/// have a zero byte and read as UNKNOWN (rendered like DONE), so the blob size and magic did not change.
/// OPEN = the zone started and has not ended yet (the entry is closed in place when the run ends); INTERRUPTED = an
/// OPEN entry found after a reboot (the end was never seen).
enum class Result : uint8_t {
  UNKNOWN = 0,
  DONE = 1,
  STOPPED = 2,
  SKIPPED_WET = 3,
  SKIPPED = 4,
  OPEN = 5,
  INTERRUPTED = 6
};

/// "Nothing known" value of HistoryEntry::detail for a wet skip (the zone's threshold could not be read).
inline constexpr uint8_t DETAIL_UNKNOWN = 255;

struct HistoryEntry {
  uint32_t epoch;     ///< start of the run, Unix seconds; 0 = the clock was not valid when it started
  uint32_t duration;  ///< OPEN / INTERRUPTED: planned seconds (0 = unknown); closed: seconds the valve was open
                      ///< (a pause inside the run is not counted); 0 for a skip
  uint8_t zone;       ///< 0-based zone index in the group
  uint8_t source;     ///< gp::Source
  uint8_t result;     ///< gp::Result
  uint8_t detail;     ///< schedule run: slot 1..8 (0 = none); SKIPPED_WET: the zone's threshold 0..100 (255 = unknown)
};
static_assert(sizeof(HistoryEntry) == 12, "HistoryEntry is part of the flash blob: do not change its size");

/// The entry's result; an unknown byte reads as UNKNOWN.
inline Result result_of(const HistoryEntry &entry) {
  return entry.result <= static_cast<uint8_t>(Result::INTERRUPTED) ? static_cast<Result>(entry.result) : Result::UNKNOWN;
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
  /// Like at(), but the entry can be changed; nullptr when out of range.
  HistoryEntry *mutable_at(size_t index) {
    if (index >= this->count)
      return nullptr;
    return &this->entries[(this->head + N - 1 - index) % N];
  }
  bool consistent() const { return this->head < N && this->count <= N; }

  HistoryEntry entries[N]{};
  uint16_t head{0};
  uint16_t count{0};
};

/// What closes an open entry (see HistoryBook::close).
struct CloseInfo {
  uint8_t zone{0};
  uint32_t start_epoch{0};  ///< start of the run as the tracker saw it (0 = clock not valid then)
  uint32_t end_epoch{0};    ///< now, when the end was seen (0 = clock not valid)
  uint32_t seconds{0};      ///< valve-open seconds
  uint8_t source{0};
  uint8_t detail{0};
  Result result{Result::DONE};
};

/// The entry life cycle on a History ring. Every function returns true when the ring changed (the caller saves it).
/// A run is ONE entry: pushed OPEN at the start (duration = planned seconds), closed in place at the end.
namespace book {

/// Age index (0 = newest) of the newest OPEN entry of `zone`, or -1. At most one entry per zone is open.
template<size_t N> int find_open(const History<N> &history, uint8_t zone) {
  for (size_t i = 0; i < history.size(); i++) {
    const HistoryEntry e = history.at(i);
    if (e.zone == zone && e.result == static_cast<uint8_t>(Result::OPEN))
      return static_cast<int>(i);
  }
  return -1;
}

template<size_t N>
bool open(History<N> &history, uint32_t epoch, uint32_t planned, uint8_t zone, uint8_t source, uint8_t detail) {
  history.push(HistoryEntry{epoch, planned, zone, source, static_cast<uint8_t>(Result::OPEN), detail});
  return true;
}

/// Closes the zone's OPEN entry in place; when it has been overwritten (100 newer pushes) a closed entry is pushed.
/// A start epoch of 0 (clock not valid at the start) is back-filled as `end_epoch - seconds` once the clock is valid.
template<size_t N> bool close(History<N> &history, const CloseInfo &info) {
  uint32_t start = info.start_epoch;
  const int age = find_open(history, info.zone);
  if (age >= 0)
    start = history.at(static_cast<size_t>(age)).epoch;
  if (start == 0 && info.end_epoch >= info.seconds && info.end_epoch != 0)
    start = info.end_epoch - info.seconds;
  if (age < 0) {
    history.push(HistoryEntry{start, info.seconds, info.zone, info.source, static_cast<uint8_t>(info.result), info.detail});
    return true;
  }
  HistoryEntry *entry = history.mutable_at(static_cast<size_t>(age));
  entry->epoch = start;
  entry->duration = info.seconds;
  entry->result = static_cast<uint8_t>(info.result);
  return true;
}

/// After a boot no run is open: every OPEN entry becomes INTERRUPTED (its duration stays the planned time).
template<size_t N> bool recover_after_boot(History<N> &history) {
  bool changed = false;
  for (size_t i = 0; i < history.size(); i++) {
    HistoryEntry *entry = history.mutable_at(i);
    if (entry->result == static_cast<uint8_t>(Result::OPEN)) {
      entry->result = static_cast<uint8_t>(Result::INTERRUPTED);
      changed = true;
    }
  }
  return changed;
}

}  // namespace book

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
