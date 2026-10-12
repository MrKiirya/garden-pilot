// Unit tests for components/gp/limits.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <climits>
#include <optional>

#include "gp/limits.h"
namespace gp = esphome::gp;

TEST_CASE("api_seconds_caps") {
  CHECK(gp::api_seconds(-5) == 0u);
  CHECK(gp::api_seconds(0) == 0u);
  CHECK(gp::api_seconds(1) == 60u);
  CHECK(gp::api_seconds(1440) == 86400u);
  CHECK(gp::api_seconds(1441) == 86400u);
  CHECK(gp::api_seconds(INT_MAX) == 86400u);
}

TEST_CASE("clamp_run_cuts_to_max") {
  CHECK_FALSE(gp::clamp_run(std::nullopt, 3300).has_value());
  CHECK(gp::clamp_run(100u, 3300).value() == 100u);
  CHECK(gp::clamp_run(5000u, 3300).value() == 3300u);
  CHECK(gp::clamp_run(5000u, 0).value() == 5000u);
}
