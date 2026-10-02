// Unit tests for components/garden_zones/queue_ops.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <cstdint>
#include <type_traits>
#include <vector>

#include "garden_zones/queue_ops.h"

namespace qo = esphome::garden_zones::queue_ops;

namespace {

struct Item {
  size_t valve_number;
  uint32_t run_duration;
};

using Items = std::vector<Item>;
using Order = std::vector<size_t>;

// Upstream storage: queue_valve() inserts at begin(), the next valve to run is back().
void enqueue(Items &items, size_t valve, uint32_t duration = 0) { items.insert(items.begin(), Item{valve, duration}); }

}  // namespace

static_assert(std::is_trivially_copyable<qo::QueueSnapshot>::value, "QueueSnapshot must be a POD for preferences");

TEST_CASE("run_order") {
  Items items;
  CHECK(qo::run_order(items).empty());
  enqueue(items, 4);
  enqueue(items, 1);
  enqueue(items, 4);
  enqueue(items, 2);
  CHECK(qo::run_order(items) == (Order{4, 1, 4, 2}));
  CHECK(items.back().valve_number == 4);  // next to run is back()
}

TEST_CASE("contains / remove_all") {
  Items items;
  enqueue(items, 0, 10);
  enqueue(items, 1, 20);
  enqueue(items, 0, 30);
  enqueue(items, 2, 40);
  CHECK(qo::contains(items, 0));
  CHECK(qo::contains(items, 2));
  CHECK_FALSE(qo::contains(items, 3));

  CHECK(qo::remove_all(items, 3) == 0);
  CHECK(qo::run_order(items) == (Order{0, 1, 0, 2}));

  CHECK(qo::remove_all(items, 0) == 2);
  CHECK(qo::run_order(items) == (Order{1, 2}));
  CHECK_FALSE(qo::contains(items, 0));
  CHECK(items.back().run_duration == 20);
}

TEST_CASE("pop_next_enabled: skips and reports disabled entries") {
  Items items;
  enqueue(items, 1);
  enqueue(items, 2);
  enqueue(items, 0, 7);
  Order asked;
  auto result = qo::pop_next_enabled(items, [&](size_t valve) {
    asked.push_back(valve);
    return valve == 0;
  });
  REQUIRE(result.item.has_value());
  CHECK(result.item->valve_number == 0);
  CHECK(result.item->run_duration == 7);
  CHECK(result.dropped == (Order{1, 2}));
  CHECK(asked == (Order{1, 2, 0}));
  CHECK(items.empty());
}

TEST_CASE("pop_next_enabled: first enabled entry is returned, the rest stays") {
  Items items;
  enqueue(items, 2);
  enqueue(items, 1);
  enqueue(items, 0);
  auto result = qo::pop_next_enabled(items, [](size_t) { return true; });
  REQUIRE(result.item.has_value());
  CHECK(result.item->valve_number == 2);
  CHECK(result.dropped.empty());
  CHECK(qo::run_order(items) == (Order{1, 0}));
}

TEST_CASE("pop_next_enabled: all disabled and empty") {
  Items items;
  enqueue(items, 0);
  enqueue(items, 1);
  auto result = qo::pop_next_enabled(items, [](size_t) { return false; });
  CHECK_FALSE(result.item.has_value());
  CHECK(result.dropped == (Order{0, 1}));
  CHECK(items.empty());

  auto empty_result = qo::pop_next_enabled(items, [](size_t) { return true; });
  CHECK_FALSE(empty_result.item.has_value());
  CHECK(empty_result.dropped.empty());
}

TEST_CASE("snapshot round trip") {
  Items items;
  enqueue(items, 2, 0);  // 0 = use the valve's default duration
  enqueue(items, 1, 90);
  enqueue(items, 0, 15);  // run order 2, 1, 0
  auto snapshot = qo::make_snapshot(items, 3);
  CHECK_FALSE(snapshot.truncated);
  auto restored = qo::restore_snapshot<Item>(snapshot, 3);
  REQUIRE(restored.has_value());
  CHECK(qo::run_order(*restored) == (Order{2, 1, 0}));
  CHECK(restored->back().run_duration == 0);
  CHECK(restored->front().run_duration == 15);
  CHECK((*restored)[1].run_duration == 90);

  Items empty;
  auto empty_restored = qo::restore_snapshot<Item>(qo::make_snapshot(empty, 3), 3);
  REQUIRE(empty_restored.has_value());
  CHECK(empty_restored->empty());
}

TEST_CASE("snapshot validation") {
  Items items;
  enqueue(items, 1, 5);
  enqueue(items, 0, 6);

  auto bad_version = qo::make_snapshot(items, 3);
  bad_version.version = static_cast<uint8_t>(bad_version.version + 1);
  CHECK_FALSE(qo::restore_snapshot<Item>(bad_version, 3).has_value());

  auto snapshot = qo::make_snapshot(items, 3);
  CHECK_FALSE(qo::restore_snapshot<Item>(snapshot, 4).has_value());
  CHECK_FALSE(qo::restore_snapshot<Item>(snapshot, 2).has_value());

  Items bad;
  enqueue(bad, 3, 5);
  CHECK_FALSE(qo::restore_snapshot<Item>(qo::make_snapshot(bad, 3), 3).has_value());

  auto too_many = qo::make_snapshot(items, 3);
  too_many.entry_count = static_cast<uint8_t>(qo::SNAPSHOT_MAX_ENTRIES + 1);
  CHECK_FALSE(qo::restore_snapshot<Item>(too_many, 3).has_value());
}

TEST_CASE("snapshot: more than 32 entries keeps the first 32 in run order") {
  Items many;
  for (size_t i = 0; i < 40; i++)
    enqueue(many, i % 3, static_cast<uint32_t>(i));
  auto snapshot = qo::make_snapshot(many, 3);
  CHECK(snapshot.truncated);
  CHECK(snapshot.entry_count == qo::SNAPSHOT_MAX_ENTRIES);
  auto restored = qo::restore_snapshot<Item>(snapshot, 3);
  REQUIRE(restored.has_value());
  auto order = qo::run_order(*restored);
  auto original = qo::run_order(many);
  REQUIRE(order.size() == qo::SNAPSHOT_MAX_ENTRIES);
  for (size_t i = 0; i < order.size(); i++)
    CHECK(order[i] == original[i]);
  CHECK(restored->back().run_duration == many.back().run_duration);
}

TEST_CASE("after_manual_run") {
  CHECK(qo::after_manual_run(true, false) == qo::AfterManualRun::RESUME_PAUSED);
  CHECK(qo::after_manual_run(false, false) == qo::AfterManualRun::GO_IDLE);
  CHECK(qo::after_manual_run(false, true) == qo::AfterManualRun::GO_IDLE);
  CHECK(qo::after_manual_run(true, true) == qo::AfterManualRun::GO_IDLE);
}

int main() { return gz_test::run_all(); }
