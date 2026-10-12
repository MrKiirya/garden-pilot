// Unit tests for components/garden_zones/soil_skip.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <cmath>
#include <limits>

#include "garden_zones/soil_skip.h"

namespace soil = esphome::garden_zones::soil;
using soil::Verdict;
using soil::WhenUnavailable;

TEST_CASE("soil threshold") {
  const auto water = WhenUnavailable::WATER;
  CHECK(soil::decide(true, 60.0f, 0, 60.0f, 3000, water) == Verdict::RUN);
  CHECK(soil::decide(true, 60.1f, 0, 60.0f, 3000, water) == Verdict::SKIP_WET);
  CHECK(soil::decide(true, 10.0f, 0, 60.0f, 3000, water) == Verdict::RUN);
}

TEST_CASE("soil unavailable") {
  const float nan = std::numeric_limits<float>::quiet_NaN();
  const auto water = WhenUnavailable::WATER;
  const auto skip = WhenUnavailable::SKIP;
  CHECK(soil::decide(false, 10.0f, 0, 60.0f, 3000, water) == Verdict::RUN_UNAVAILABLE);
  CHECK(soil::decide(false, 10.0f, 0, 60.0f, 3000, skip) == Verdict::SKIP_UNAVAILABLE);
  CHECK(soil::decide(true, nan, 0, 60.0f, 3000, water) == Verdict::RUN_UNAVAILABLE);
  CHECK(soil::decide(true, nan, 0, 60.0f, 3000, skip) == Verdict::SKIP_UNAVAILABLE);
  CHECK(soil::decide(true, 72.0f, 3001, 60.0f, 3000, water) == Verdict::RUN_UNAVAILABLE);  // stale, even if wet
  CHECK(soil::decide(true, 72.0f, 3001, 60.0f, 3000, skip) == Verdict::SKIP_UNAVAILABLE);
  CHECK(soil::decide(true, 72.0f, 3000, 60.0f, 3000, water) == Verdict::SKIP_WET);  // == max_age is fresh
  CHECK(soil::age_ms(1000, 0xFFFFFC18u) == 2000);
  CHECK(soil::age_ms(5000, 5000) == 0);
}
