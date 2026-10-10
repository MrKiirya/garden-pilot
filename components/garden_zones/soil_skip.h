// garden_zones — soil moisture verdict (new file, not part of upstream ESPHome).
// Copyright (c) GardenPilot contributors.
// Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
//
// Pure, header-only, ESPHome-free: only the C++ standard library (C++17). Unit tested on the host compiler
// (tests/cpp/test_soil_skip.cpp).
#pragma once

#include <cmath>
#include <cstdint>

namespace esphome::garden_zones::soil {

enum class WhenUnavailable { WATER, SKIP };
enum class Verdict { RUN, SKIP_WET, RUN_UNAVAILABLE, SKIP_UNAVAILABLE };

/// Milliseconds since `last_update` (wrap-safe for one wrap; the glue drops readings older than max_age, so an age
/// never has to stay meaningful across a second wrap).
inline uint32_t age_ms(uint32_t now, uint32_t last_update) { return now - last_update; }

/// Unavailable = no value, NaN, or older than `max_age_ms`. Wet = strictly above `skip_above` (equal waters).
inline Verdict decide(bool has_value, float value, uint32_t age, float skip_above, uint32_t max_age_ms,
                      WhenUnavailable when_unavailable) {
  if (!has_value || std::isnan(value) || age > max_age_ms)
    return when_unavailable == WhenUnavailable::SKIP ? Verdict::SKIP_UNAVAILABLE : Verdict::RUN_UNAVAILABLE;
  return value > skip_above ? Verdict::SKIP_WET : Verdict::RUN;
}

}  // namespace esphome::garden_zones::soil
