// gp — duration limits (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
#pragma once

#include <cstdint>
#include <optional>

namespace esphome::gp {

inline constexpr uint32_t API_MAX_SECONDS = 86400;  ///< 24 h: the longest run a Home Assistant call can ask for

/// Minutes of a Home Assistant action to seconds: <= 0 = 0 (the zone's configured duration), above 24 h = 24 h.
inline uint32_t api_seconds(int minutes) {
  if (minutes <= 0)
    return 0;
  if (minutes > 1440)
    return API_MAX_SECONDS;
  return static_cast<uint32_t>(minutes) * 60u;
}

/// A requested run cut to the zone's maximum; `max` 0 = unknown (no cut).
inline std::optional<uint32_t> clamp_run(std::optional<uint32_t> seconds, uint32_t max) {
  if (seconds.has_value() && max > 0 && *seconds > max)
    return max;
  return seconds;
}

}  // namespace esphome::gp
