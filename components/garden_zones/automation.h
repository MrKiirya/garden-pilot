// garden_zones — modified copy of ESPHome esphome/components/sprinkler (tag 2026.9.1).
// Original: Copyright (c) ESPHome contributors. Modifications: Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
// MODIFIED: see PATCHES.md (regions marked GZ-PATCH-BEGIN/END).

#pragma once

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/components/garden_zones/sprinkler.h"

namespace esphome::garden_zones {

template<typename... Ts> class SetDividerAction final : public Action<Ts...> {
 public:
  explicit SetDividerAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(uint32_t, divider)

  void play(const Ts &...x) override { this->sprinkler_->set_divider(this->divider_.optional_value(x...)); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class SetMultiplierAction final : public Action<Ts...> {
 public:
  explicit SetMultiplierAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(float, multiplier)

  void play(const Ts &...x) override { this->sprinkler_->set_multiplier(this->multiplier_.optional_value(x...)); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class QueueValveAction final : public Action<Ts...> {
 public:
  explicit QueueValveAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(size_t, valve_number)
  TEMPLATABLE_VALUE(uint32_t, valve_run_duration)

  void play(const Ts &...x) override {
    this->sprinkler_->queue_valve(this->valve_number_.optional_value(x...),
                                  this->valve_run_duration_.optional_value(x...));
  }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class ClearQueuedValvesAction final : public Action<Ts...> {
 public:
  explicit ClearQueuedValvesAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->clear_queued_valves(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class SetRepeatAction final : public Action<Ts...> {
 public:
  explicit SetRepeatAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(uint32_t, repeat)

  void play(const Ts &...x) override { this->sprinkler_->set_repeat(this->repeat_.optional_value(x...)); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class SetRunDurationAction final : public Action<Ts...> {
 public:
  explicit SetRunDurationAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(size_t, valve_number)
  TEMPLATABLE_VALUE(uint32_t, valve_run_duration)

  void play(const Ts &...x) override {
    this->sprinkler_->set_valve_run_duration(this->valve_number_.optional_value(x...),
                                             this->valve_run_duration_.optional_value(x...));
  }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class StartFromQueueAction final : public Action<Ts...> {
 public:
  explicit StartFromQueueAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->start_from_queue(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class StartFullCycleAction final : public Action<Ts...> {
 public:
  explicit StartFullCycleAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->start_full_cycle(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class StartSingleValveAction final : public Action<Ts...> {
 public:
  explicit StartSingleValveAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  // TemplatableValue (not TemplatableFn) — also set from C++ with raw values in sprinkler.cpp
  template<typename V> void set_valve_to_start(V valve_to_start) { this->valve_to_start_ = valve_to_start; }
  TEMPLATABLE_VALUE(uint32_t, valve_run_duration)

  void play(const Ts &...x) override {
    this->sprinkler_->start_single_valve(this->valve_to_start_.optional_value(x...),
                                         this->valve_run_duration_.optional_value(x...));
  }

 protected:
  Sprinkler *sprinkler_;
  TemplatableValue<size_t, Ts...> valve_to_start_{};
};

// GZ-PATCH-BEGIN(manual-run)
template<typename... Ts> class RunValveAction final : public Action<Ts...> {
 public:
  explicit RunValveAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(size_t, valve_number)
  TEMPLATABLE_VALUE(uint32_t, valve_run_duration)

  void play(const Ts &...x) override {
    this->sprinkler_->run_valve(this->valve_number_.optional_value(x...),
                                this->valve_run_duration_.optional_value(x...));
  }

 protected:
  Sprinkler *sprinkler_;
};
// GZ-PATCH-END(manual-run)

// GZ-PATCH-BEGIN(queue-api)
template<typename... Ts> class RemoveQueuedValveAction final : public Action<Ts...> {
 public:
  explicit RemoveQueuedValveAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(size_t, valve_number)

  void play(const Ts &...x) override {
    auto valve_number = this->valve_number_.optional_value(x...);
    if (valve_number.has_value()) {
      this->sprinkler_->remove_queued_valve(valve_number.value());
    }
  }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class IsValveQueuedCondition final : public Condition<Ts...> {
 public:
  explicit IsValveQueuedCondition(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  TEMPLATABLE_VALUE(size_t, valve_number)

  bool check(const Ts &...x) override {
    auto valve_number = this->valve_number_.optional_value(x...);
    return valve_number.has_value() && this->sprinkler_->is_valve_queued(valve_number.value());
  }

 protected:
  Sprinkler *sprinkler_;
};
// GZ-PATCH-END(queue-api)

template<typename... Ts> class ShutdownAction final : public Action<Ts...> {
 public:
  explicit ShutdownAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->shutdown(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class NextValveAction final : public Action<Ts...> {
 public:
  explicit NextValveAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->next_valve(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class PreviousValveAction final : public Action<Ts...> {
 public:
  explicit PreviousValveAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->previous_valve(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class PauseAction final : public Action<Ts...> {
 public:
  explicit PauseAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->pause(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class ResumeAction final : public Action<Ts...> {
 public:
  explicit ResumeAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->resume(); }

 protected:
  Sprinkler *sprinkler_;
};

template<typename... Ts> class ResumeOrStartAction final : public Action<Ts...> {
 public:
  explicit ResumeOrStartAction(Sprinkler *a_sprinkler) : sprinkler_(a_sprinkler) {}

  void play(const Ts &...x) override { this->sprinkler_->resume_or_start_full_cycle(); }

 protected:
  Sprinkler *sprinkler_;
};

}  // namespace esphome::garden_zones
