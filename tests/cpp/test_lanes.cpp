// Unit tests for components/garden_zones/lanes.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <optional>
#include <vector>

#include "garden_zones/lanes.h"

namespace ln = esphome::garden_zones::lanes;

namespace {
using Order = std::vector<size_t>;
// zones 0 and 2 in lane 0 (valves 0, 1), zone 1 in lane 1 (valve 0)
ln::LaneMap sample_map() { return ln::LaneMap({{0, 0}, {1, 0}, {0, 1}}); }
}  // namespace

TEST_CASE("LaneMap routing") {
  ln::LaneMap map = sample_map();
  CHECK(map.lane_count() == 2);
  CHECK(map.zone_count() == 3);
  for (size_t zone = 0; zone < 3; zone++) {
    auto ref = map.route(zone);
    REQUIRE(ref.has_value());
    CHECK(ref->lane == (zone == 1 ? 1u : 0u));
    CHECK(ref->valve == (zone == 2 ? 1u : 0u));
  }
  CHECK(!map.route(3).has_value());
  REQUIRE(map.zone_of(0, 1).has_value());
  CHECK(*map.zone_of(0, 1) == 2);
  CHECK(!map.zone_of(1, 1).has_value());
  CHECK(!map.zone_of(2, 0).has_value());
}

TEST_CASE("LaneMap validation") {
  using T = std::vector<ln::ZoneRef>;
  CHECK(ln::LaneMap::valid(T{{0, 0}, {1, 0}, {0, 1}}));
  CHECK(ln::LaneMap::valid(T{{0, 0}, {0, 1}, {0, 2}}));  // one lane
  CHECK(ln::LaneMap::valid(T{{0, 0}, {1, 0}, {2, 0}}));  // one lane per zone
  CHECK_FALSE(ln::LaneMap::valid(T{{0, 0}, {0, 0}}));    // duplicate pair
  CHECK_FALSE(ln::LaneMap::valid(T{{0, 0}, {0, 2}}));    // gap in a lane
  CHECK_FALSE(ln::LaneMap::valid(T{{0, 0}, {2, 0}}));    // unused lane between used lanes
  CHECK_FALSE(ln::LaneMap::valid(T{}));
}

TEST_CASE("round_order") {
  ln::LaneMap map = sample_map();
  CHECK(ln::round_order(std::vector<Order>{{0, 1}, {0}}, map) == (Order{0, 1, 2}));
  CHECK(ln::round_order(std::vector<Order>{{1}, {0}}, map) == (Order{2, 1}));
  CHECK(ln::round_order(std::vector<Order>{{}, {0}}, map) == (Order{1}));
  CHECK(ln::round_order(std::vector<Order>{{}, {}}, map).empty());
}

TEST_CASE("lanes_to_start / active_zones") {
  CHECK(ln::lanes_to_start(std::vector<size_t>{0, 2, 0, 1}) == (Order{1, 3}));
  CHECK(ln::lanes_to_start(std::vector<size_t>{0, 0}).empty());
  ln::LaneMap map = sample_map();
  using Active = std::vector<std::optional<size_t>>;
  CHECK(ln::active_zones(Active{1, std::nullopt}, map) == (Order{2}));
  CHECK(ln::active_zones(Active{0, 0}, map) == (Order{0, 1}));
  CHECK(ln::active_zones(Active{1, 0}, map) == (Order{1, 2}));
  CHECK(ln::active_zones(Active{std::nullopt, std::nullopt}, map).empty());
}
