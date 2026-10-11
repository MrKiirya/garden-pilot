// gp — deferred queue start (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// A scheduled start (`gp.start_queue`) that arrives while a manual full cycle (or any other run that is not a queue run)
// is active must not cut that run short: the zones stay queued and the queue starts after the run has ended. The run
// counts as ended after GRACE_MS without any zone running (a cycle has short gaps between its zones).
#pragma once

#include <cstdint>

namespace esphome::gp {

/// True when starting the queue now would interrupt a running cycle / manual run.
inline bool start_must_wait(bool busy, bool cycle_run, bool queue_run) { return busy && (cycle_run || !queue_run); }

class DeferredStart {
 public:
  static constexpr uint32_t GRACE_MS = 5000;

  /// A queue start was asked for while a non-queue run is active.
  void request(uint32_t now_ms) {
    this->pending_ = true;
    this->busy_ms_ = now_ms;
  }
  /// Drops the request (a STOP or service mode settled the zones).
  void cancel() { this->pending_ = false; }
  bool pending() const { return this->pending_; }

  /// Call on every model refresh. Returns true once, when the queue must be started now.
  bool update(bool running, uint32_t now_ms) {
    if (!this->pending_)
      return false;
    if (running) {
      this->busy_ms_ = now_ms;
      return false;
    }
    if (static_cast<uint32_t>(now_ms - this->busy_ms_) < GRACE_MS)
      return false;
    this->pending_ = false;
    return true;
  }

 protected:
  bool pending_{false};
  uint32_t busy_ms_{0};
};

}  // namespace esphome::gp
