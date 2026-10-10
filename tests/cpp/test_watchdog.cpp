// Unit tests for components/garden_zones/watchdog_core.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <optional>
#include <vector>

#include "garden_zones/watchdog_core.h"

namespace wd = esphome::garden_zones::watchdog;
using wd::Command;
using wd::Reason;
using K = wd::Command::Kind;

namespace {

const Command *find(const std::vector<Command> &commands, K kind, int zone) {
  for (const Command &command : commands) {
    if (command.kind == kind && command.zone == zone)
      return &command;
  }
  return nullptr;
}

size_t count(const std::vector<Command> &commands, K kind) {
  size_t n = 0;
  for (const Command &command : commands)
    n += command.kind == kind ? 1 : 0;
  return n;
}

using Zones = std::vector<bool>;
constexpr std::optional<bool> NO_PUMP = std::nullopt;

}  // namespace

TEST_CASE("OnTimer continuous on-time") {
  wd::OnTimer timer;
  timer.update(false, 0);
  CHECK_FALSE(timer.on());
  CHECK(timer.on_for(500) == 0);
  timer.update(true, 100);
  CHECK(timer.on());
  CHECK(timer.on_for(1100) == 1000);
  timer.update(true, 900);  // still on: the start is not moved
  CHECK(timer.on_for(1100) == 1000);
  timer.update(false, 1200);
  CHECK(timer.on_for(1300) == 0);
  timer.update(true, 1300);
  CHECK(timer.on_for(1400) == 100);

  wd::OnTimer first;
  first.update(true, 500);  // seen on at the first update: timed from that update
  CHECK(first.on_for(1500) == 1000);
}

TEST_CASE("OnTimer millis wrap") {
  wd::OnTimer timer;
  timer.update(true, 0xFFFFFC18u);
  CHECK(timer.on_for(1000) == 2000);
}

TEST_CASE("zone trips strictly after max_on_time") {
  wd::GroupGuard guard({3000, 5000}, NO_PUMP, NO_PUMP);
  CHECK(guard.update(Zones{true, true}, NO_PUMP, 0).empty());
  CHECK(guard.update(Zones{true, true}, NO_PUMP, 3000).empty());
  auto commands = guard.update(Zones{true, true}, NO_PUMP, 3001);
  const Command *shutdown = find(commands, K::SHUTDOWN_LANE_OF_ZONE, 0);
  const Command *force = find(commands, K::FORCE_OFF_ZONE, 0);
  REQUIRE(shutdown != nullptr);
  REQUIRE(force != nullptr);
  CHECK(force->reason == Reason::MAX_ON_TIME);
  CHECK(shutdown->reason == Reason::MAX_ON_TIME);
  CHECK(shutdown->new_trip);
  CHECK(commands.front().new_trip);
  CHECK(find(commands, K::FORCE_OFF_ZONE, 1) == nullptr);
  CHECK(commands.size() == 2);
  CHECK(guard.zone_locked(0));
  CHECK_FALSE(guard.zone_locked(1));
  CHECK_FALSE(guard.pump_locked());
  CHECK(guard.tripped());
}

TEST_CASE("trip fires once, then lockout and retries") {
  wd::GroupGuard guard({3000}, NO_PUMP, NO_PUMP);
  guard.update(Zones{true}, NO_PUMP, 0);
  auto trip = guard.update(Zones{true}, NO_PUMP, 3001);
  REQUIRE(find(trip, K::FORCE_OFF_ZONE, 0) != nullptr);
  CHECK(guard.update(Zones{true}, NO_PUMP, 3100).empty());  // inside 1000 ms
  auto retry = guard.update(Zones{true}, NO_PUMP, 4002);
  const Command *force = find(retry, K::FORCE_OFF_ZONE, 0);
  REQUIRE(force != nullptr);
  CHECK(force->reason == Reason::STILL_ON);
  CHECK_FALSE(force->new_trip);
  CHECK(count(retry, K::SHUTDOWN_LANE_OF_ZONE) == 0);
  CHECK(guard.update(Zones{false}, NO_PUMP, 4100).empty());
  auto again = guard.update(Zones{true}, NO_PUMP, 4200);
  const Command *locked = find(again, K::FORCE_OFF_ZONE, 0);
  REQUIRE(locked != nullptr);
  CHECK(locked->reason == Reason::LOCKED_OUT);
  CHECK_FALSE(locked->new_trip);
  const Command *shutdown = find(again, K::SHUTDOWN_LANE_OF_ZONE, 0);
  REQUIRE(shutdown != nullptr);
  CHECK(shutdown->reason == Reason::LOCKED_OUT);
}

TEST_CASE("reset clears latches and restarts timers") {
  wd::GroupGuard guard({3000}, NO_PUMP, NO_PUMP);
  guard.update(Zones{true}, NO_PUMP, 0);
  guard.update(Zones{true}, NO_PUMP, 3001);
  CHECK(guard.tripped());
  guard.reset(5000);
  CHECK_FALSE(guard.tripped());
  CHECK_FALSE(guard.zone_locked(0));
  CHECK(guard.update(Zones{true}, NO_PUMP, 5000).empty());
  CHECK(guard.update(Zones{true}, NO_PUMP, 8000).empty());
  auto commands = guard.update(Zones{true}, NO_PUMP, 8001);
  const Command *force = find(commands, K::FORCE_OFF_ZONE, 0);
  REQUIRE(force != nullptr);
  CHECK(force->reason == Reason::MAX_ON_TIME);
  CHECK(force->new_trip || commands.front().new_trip);
}

TEST_CASE("pump idle") {
  {
    wd::GroupGuard guard({10000}, std::optional<uint32_t>(60000), std::optional<uint32_t>(2000));
    CHECK(guard.update(Zones{false}, std::optional<bool>(true), 0).empty());
    CHECK(guard.update(Zones{false}, std::optional<bool>(true), 2000).empty());
    auto commands = guard.update(Zones{false}, std::optional<bool>(true), 2001);
    const Command *shutdown = find(commands, K::SHUTDOWN_GROUP, -1);
    const Command *pump = find(commands, K::FORCE_OFF_PUMP, -1);
    REQUIRE(shutdown != nullptr);
    REQUIRE(pump != nullptr);
    CHECK(shutdown->reason == Reason::PUMP_IDLE);
    CHECK(shutdown->new_trip);
    CHECK(count(commands, K::FORCE_OFF_ZONE) == 0);
    CHECK(guard.pump_locked());
    CHECK(guard.zone_locked(0));  // a pump trip locks the whole group
  }
  {
    wd::GroupGuard guard({60000}, std::optional<uint32_t>(600000), std::optional<uint32_t>(2000));
    // pump + zone on: never idle
    for (uint32_t t = 0; t <= 5000; t += 500)
      CHECK(guard.update(Zones{true}, std::optional<bool>(true), t).empty());
    // zone off at 5000 with the pump still on: idle from 5000
    CHECK(guard.update(Zones{false}, std::optional<bool>(true), 5000).empty());
    CHECK(guard.update(Zones{false}, std::optional<bool>(true), 7000).empty());
    auto commands = guard.update(Zones{false}, std::optional<bool>(true), 7001);
    REQUIRE(find(commands, K::FORCE_OFF_PUMP, -1) != nullptr);
    CHECK(find(commands, K::FORCE_OFF_PUMP, -1)->reason == Reason::PUMP_IDLE);
  }
}

TEST_CASE("pump max on-time across alternating zones") {
  wd::GroupGuard guard({3000, 3000}, std::optional<uint32_t>(5000), std::optional<uint32_t>(2000));
  std::vector<Command> commands;
  // zones alternate every 1500 ms: A 0-1500, B 1500-3000, A 3000-4500, B 4500-6000
  for (uint32_t t = 0; t <= 5000; t += 100) {
    const uint32_t slot = (t / 1500) % 2;
    CHECK(guard.update(Zones{slot == 0, slot == 1}, std::optional<bool>(true), t).empty());
  }
  commands = guard.update(Zones{false, true}, std::optional<bool>(true), 5001);
  const Command *shutdown = find(commands, K::SHUTDOWN_GROUP, -1);
  REQUIRE(shutdown != nullptr);
  CHECK(shutdown->reason == Reason::PUMP_MAX_ON_TIME);
  CHECK(shutdown->new_trip);
  CHECK(find(commands, K::FORCE_OFF_PUMP, -1) != nullptr);
  CHECK(find(commands, K::FORCE_OFF_ZONE, 1) != nullptr);  // zone B is on at 5001
  CHECK(find(commands, K::FORCE_OFF_ZONE, 0) == nullptr);
  CHECK(count(commands, K::SHUTDOWN_LANE_OF_ZONE) == 0);  // no zone trip
  CHECK(guard.zone_locked(0));
  CHECK(guard.zone_locked(1));
  CHECK(guard.pump_locked());
}

TEST_CASE("no pump configured") {
  wd::GroupGuard guard({1000}, NO_PUMP, NO_PUMP);
  CHECK(guard.update(Zones{false}, NO_PUMP, 0).empty());
  CHECK(guard.update(Zones{false}, NO_PUMP, 100000).empty());
  guard.update(Zones{true}, NO_PUMP, 100000);
  auto commands = guard.update(Zones{true}, NO_PUMP, 101001);
  CHECK(find(commands, K::FORCE_OFF_ZONE, 0) != nullptr);
  CHECK(count(commands, K::FORCE_OFF_PUMP) == 0);
  CHECK(count(commands, K::SHUTDOWN_GROUP) == 0);
  CHECK_FALSE(guard.pump_locked());
}

TEST_CASE("pump trip forces a still-on pump again once per second") {
  wd::GroupGuard guard({60000}, std::optional<uint32_t>(600000), std::optional<uint32_t>(1000));
  guard.update(Zones{false}, std::optional<bool>(true), 0);
  auto trip = guard.update(Zones{false}, std::optional<bool>(true), 1001);
  REQUIRE(find(trip, K::FORCE_OFF_PUMP, -1) != nullptr);
  CHECK(guard.update(Zones{false}, std::optional<bool>(true), 1500).empty());
  auto retry = guard.update(Zones{false}, std::optional<bool>(true), 2001);
  REQUIRE(find(retry, K::FORCE_OFF_PUMP, -1) != nullptr);
  CHECK(find(retry, K::FORCE_OFF_PUMP, -1)->reason == Reason::STILL_ON);
  CHECK_FALSE(find(retry, K::FORCE_OFF_PUMP, -1)->new_trip);
}

TEST_CASE("a disabled zone limit (never) does not trip, other zones still do") {
  wd::GroupGuard guard({wd::DISABLED, 3000}, NO_PUMP, NO_PUMP);
  guard.update(Zones{true, true}, NO_PUMP, 0);
  auto commands = guard.update(Zones{true, true}, NO_PUMP, 3001);
  CHECK(find(commands, K::FORCE_OFF_ZONE, 1) != nullptr);
  CHECK(find(commands, K::FORCE_OFF_ZONE, 0) == nullptr);
  CHECK_FALSE(guard.zone_locked(0));
  // 20 days later the disabled zone is still not touched
  const uint32_t later = 20u * 24u * 3600u * 1000u;
  CHECK(guard.update(Zones{true, false}, NO_PUMP, later).empty());
  CHECK_FALSE(guard.zone_locked(0));
}

TEST_CASE("disabled pump limits (never) do not trip, a long limit (6 h) does after 6 h") {
  const uint32_t six_hours = 6u * 3600u * 1000u;
  wd::GroupGuard off({60000}, NO_PUMP, NO_PUMP);  // pump_max_on_time: never, pump_idle_timeout: never
  off.update(Zones{false}, std::optional<bool>(true), 0);
  CHECK(off.update(Zones{false}, std::optional<bool>(true), six_hours + 1).empty());
  CHECK_FALSE(off.pump_locked());

  wd::GroupGuard six({wd::DISABLED}, std::optional<uint32_t>(six_hours), NO_PUMP);
  six.update(Zones{true}, std::optional<bool>(true), 0);
  CHECK(six.update(Zones{true}, std::optional<bool>(true), six_hours).empty());
  auto commands = six.update(Zones{true}, std::optional<bool>(true), six_hours + 1);
  REQUIRE(find(commands, K::FORCE_OFF_PUMP, -1) != nullptr);
  CHECK(find(commands, K::FORCE_OFF_PUMP, -1)->reason == Reason::PUMP_MAX_ON_TIME);
}
