// gp - geometry of the bed cards (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// The greenhouse page has six card slots of one template (packages/lvgl/card_bed.yaml). Which slots show and where is a
// function of the group zone count, so it is decided at run time by the card scripts, not in the YAML:
//   1-3 zones: full cards in one row (304, 149 or 97 px wide, 120 px high);
//   4-6 zones: compact cards, 3 columns x 2 rows (97 x 57 px); a tap opens the bed detail page.
// The cards area is x 8..312, y 48..168 (between the stats strip and the transport row), gap space-3 = 6 px.
#pragma once

#include <cstddef>
#include <cstdint>

namespace esphome::gp::layout {

inline constexpr size_t MAX_CARDS = 6;
inline constexpr int16_t AREA_X = 8;
inline constexpr int16_t AREA_Y = 48;
inline constexpr int16_t AREA_W = 304;
inline constexpr int16_t AREA_H = 120;
inline constexpr int16_t GAP = 6;
inline constexpr size_t MAX_FULL = 3;

struct CardRect {
  bool visible{false};
  bool compact{false};
  int16_t x{0}, y{0}, w{0}, h{0};
};

/// The rectangle of card `slot` (0-based) for a group of `count` zones; slots past the zone count are invisible.
inline CardRect bed_card(size_t count, size_t slot) {
  CardRect r;
  if (count == 0 || slot >= count || slot >= MAX_CARDS)
    return r;
  r.visible = true;
  if (count <= MAX_FULL) {
    const int16_t n = static_cast<int16_t>(count);
    r.w = static_cast<int16_t>((AREA_W - GAP * (n - 1)) / n);
    r.h = AREA_H;
    r.x = static_cast<int16_t>(AREA_X + static_cast<int16_t>(slot) * (r.w + GAP));
    r.y = AREA_Y;
    return r;
  }
  r.compact = true;
  r.w = static_cast<int16_t>((AREA_W - GAP * 2) / 3);
  r.h = static_cast<int16_t>((AREA_H - GAP) / 2);
  r.x = static_cast<int16_t>(AREA_X + static_cast<int16_t>(slot % 3) * (r.w + GAP));
  r.y = static_cast<int16_t>(AREA_Y + static_cast<int16_t>(slot / 3) * (r.h + GAP));
  return r;
}

}  // namespace esphome::gp::layout
