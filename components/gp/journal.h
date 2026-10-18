// gp — the run journal: turns the model's start / end / skip events into history entries (pure C++17, no ESPHome
// includes; unit tested on the host compiler with a fake clock).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// One run = one history entry: pushed OPEN when the zone starts, closed in place when it ends (history.h, `book::`).
// process() returns true when the blob changed; the glue then saves it, so a run costs two save requests and nothing is
// written while it runs (the live time is computed in RAM from the model).
#pragma once

#include <cstdint>

#include "history.h"
#include "zone_model.h"

namespace esphome::gp {

/// A STOP inside this window of the end of a run marks the run "stopped".
inline constexpr uint32_t STOP_WINDOW_MS = 3000;

/// True when a run that ended at `now_ms` was cut by a stop_all at `stop_ms` (0 = never stopped). A watchdog-ended
/// run is not "stopped": it reads done, like `completed`.
inline bool ended_by_stop(uint32_t now_ms, uint32_t stop_ms) {
  return stop_ms != 0 && static_cast<uint32_t>(now_ms - stop_ms) < STOP_WINDOW_MS;
}

class Journal {
 public:
  explicit Journal(PersistBlob &blob) : blob_(blob) {}

  /// Boot: every OPEN entry becomes INTERRUPTED. True when the blob changed (save it).
  bool recover_after_boot() {
    const bool changed = book::recover_after_boot(this->blob_.history);
    if (changed)
      this->pushes++;
    return changed;
  }

  /// Applies the model's pending events. `on_event(record, result)` is called for every finished run (result DONE or
  /// STOPPED) and every skip (SKIPPED_WET / SKIPPED), after the entry was written.
  template<typename F> bool process(GroupModel &model, uint32_t now_ms, uint32_t stop_ms, F &&on_event) {
    bool changed = false;
    RunStart start;
    while (model.take_started(start)) {
      book::open(this->blob_.history, start.epoch, start.planned, start.zone, static_cast<uint8_t>(start.source),
                 start.detail);
      this->pushes++;
      changed = true;
    }
    RunRecord record;
    while (model.take_completed(record)) {
      changed = true;
      this->pushes++;
      if (record.is_skip()) {  // a skip is a history entry only: not a "last watering", not a finished run
        this->blob_.history.push(HistoryEntry{record.epoch, 0, record.zone, static_cast<uint8_t>(record.source),
                                              static_cast<uint8_t>(record.result), record.detail});
        on_event(record, record.result);
        continue;
      }
      const Result result = ended_by_stop(now_ms, stop_ms) ? Result::STOPPED : Result::DONE;
      book::close(this->blob_.history, CloseInfo{record.zone, record.epoch, record.end_epoch, record.duration,
                                                 static_cast<uint8_t>(record.source), record.detail, result});
      if (record.zone < MAX_ZONES && record.source != Source::SERVICE) {
        this->blob_.last[record.zone].epoch = record.epoch;
        this->blob_.last[record.zone].duration = record.duration;
      }
      on_event(record, result);
    }
    return changed;
  }

  uint32_t pushes{0};  ///< history changes since boot (RAM only), for history_changed_since

 protected:
  PersistBlob &blob_;
};

}  // namespace esphome::gp
