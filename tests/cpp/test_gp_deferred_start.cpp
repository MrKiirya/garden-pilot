// Unit tests for components/gp/deferred_start.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include "gp/deferred_start.h"
namespace gp = esphome::gp;

TEST_CASE("deferral_needed_only_for_a_running_non_queue_run") {
  CHECK(gp::start_must_wait(true, true, true));    // a full cycle (queue_run is set by full_cycle too)
  CHECK(gp::start_must_wait(true, false, false));  // a manual run or a cycle started outside gp
  CHECK_FALSE(gp::start_must_wait(true, false, true));   // a queue run picks the new zones up by itself
  CHECK_FALSE(gp::start_must_wait(false, true, false));  // nothing running: start at once
  CHECK_FALSE(gp::start_must_wait(false, false, false));
}

TEST_CASE("deferred_start_waits_for_the_end_of_the_run_plus_a_grace_time") {
  gp::DeferredStart d;
  CHECK_FALSE(d.pending());
  CHECK_FALSE(d.update(false, 1000));  // nothing requested: never starts
  d.request(10000);
  CHECK(d.pending());
  CHECK_FALSE(d.update(true, 11000));   // the cycle runs
  CHECK_FALSE(d.update(true, 70000));
  CHECK_FALSE(d.update(false, 72000));  // gap between two zones of the cycle: still waiting
  CHECK_FALSE(d.update(true, 74000));   // next zone started: the grace time restarts
  CHECK_FALSE(d.update(false, 76000));
  CHECK_FALSE(d.update(false, 78000));
  CHECK(d.update(false, 79000));  // 5 s idle after the last zone: start the queue now
  CHECK_FALSE(d.pending());
  CHECK_FALSE(d.update(false, 90000));  // consumed: starts only once
}

TEST_CASE("deferred_start_cancel_and_millis_wrap") {
  gp::DeferredStart d;
  d.request(1000);
  d.cancel();  // a STOP / service mode settles the slot: nothing starts later
  CHECK_FALSE(d.pending());
  CHECK_FALSE(d.update(false, 60000));
  d.request(0xFFFFF000u);  // millis() wraps while waiting
  CHECK_FALSE(d.update(false, 0xFFFFF800u));
  CHECK(d.update(false, 0x00001000u));
}
