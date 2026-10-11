// Unit tests for components/garden_schedule/schedule_core.h (host compiler, no ESPHome headers, fake clock).
#include "minitest.h"

#include <string>

#include "garden_schedule/schedule_core.h"
namespace gs = esphome::garden_schedule;

namespace {

const int32_t MON = gs::days_from_civil(2026, 10, 12);  // a Monday
const uint8_t MON_WED_FRI = 0x01 | 0x04 | 0x10;

gs::SlotConfig slot(unsigned hour, unsigned minute, uint32_t zones = 0x3, uint8_t days = gs::ALL_DAYS, bool enabled = true,
                    uint8_t pct = 100) {
  gs::SlotConfig c;
  c.enabled = enabled;
  c.start_minute = static_cast<uint16_t>(hour * 60 + minute);
  c.days_mask = days;
  c.zone_mask = zones;
  c.pct = pct;
  return c;
}

/// A scheduler with a fake clock: `at()` moves the clock like real time (UTC = local), `jump()` like a sync.
struct Fx {
  gs::Scheduler s;
  gs::SlotConfig cfg[gs::MAX_SLOTS];
  size_t n{1};
  int64_t epoch{0};
  uint32_t mono{0};
  bool started{false};

  gs::Events at(int32_t day, unsigned h, unsigned m, unsigned sec, bool jump = false) {
    const int64_t lin = static_cast<int64_t>(day) * 86400 + h * 3600 + m * 60 + sec;
    if (started)
      mono += jump ? 1000u : static_cast<uint32_t>((lin - epoch) * 1000);
    epoch = lin;
    started = true;
    return raw(day, static_cast<uint16_t>(h * 60 + m), static_cast<uint8_t>(sec), epoch, mono);
  }
  gs::Events jump(int32_t day, unsigned h, unsigned m, unsigned sec) { return at(day, h, m, sec, true); }
  gs::Events raw(int32_t day, uint16_t minute, uint8_t sec, int64_t ep, uint32_t mo) {
    gs::Tick t;
    t.valid = true;
    t.epoch = ep;
    t.mono_ms = mo;
    t.local.day = day;
    t.local.minute = minute;
    t.local.second = sec;
    gs::Events e;
    s.tick(t, cfg, n, e);
    return e;
  }
  gs::Events invalid() {
    gs::Tick t;
    gs::Events e;
    s.tick(t, cfg, n, e);
    return e;
  }
};

}  // namespace

TEST_CASE("calendar_helpers") {
  CHECK(gs::weekday_of(MON) == 0);
  CHECK(gs::weekday_of(MON + 6) == 6);
  CHECK(gs::weekday_of(0) == 3);  // 1970-01-01 was a Thursday
  CHECK(gs::weekday_of(-1) == 2);
  for (int32_t d : {-800, -1, 0, 59, 60, 365, 11000, 20373, 20500}) {
    int y;
    unsigned m, dd;
    gs::civil_from_days(d, y, m, dd);
    CHECK(gs::days_from_civil(y, m, dd) == d);
  }
  CHECK(gs::format_iso(MON, 6 * 60, 7200) == "2026-10-12T06:00:00+02:00");
  CHECK(gs::format_iso(MON, 23 * 60 + 5, -(5 * 3600 + 1800)) == "2026-10-12T23:05:00-05:30");
  CHECK(gs::format_time(7 * 60 + 5) == "07:05");
  CHECK(std::string(gs::weekday_name(1)) == "Tue");
}

TEST_CASE("parse_zones") {
  bool dropped = true;
  CHECK(gs::parse_zones("all", 3, &dropped) == 0x7u);
  CHECK(!dropped);
  CHECK(gs::parse_zones("1 3", 3, &dropped) == 0x5u);
  CHECK(!dropped);
  CHECK(gs::parse_zones("  2   2 ", 3) == 0x2u);  // extra spaces and duplicates are fine
  CHECK(gs::parse_zones("1 0", 3, &dropped) == 0x1u);
  CHECK(dropped);
  CHECK(gs::parse_zones("2 17", 3, &dropped) == 0x2u);
  CHECK(dropped);
  CHECK(!gs::parse_zones("17", 3, &dropped).has_value());  // nothing left
  CHECK(dropped);
  CHECK(!gs::parse_zones("", 3).has_value());
  CHECK(!gs::parse_zones("   ", 3).has_value());
  CHECK(!gs::parse_zones("1,3", 3).has_value());
  CHECK(!gs::parse_zones("x", 3).has_value());
  CHECK(!gs::parse_zones("100", 3).has_value());
  CHECK(!gs::parse_zones("all", 0).has_value());
  CHECK(gs::parse_zones("all", 32) == 0xFFFFFFFFu);
}

TEST_CASE("fires_once_on_crossing") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x5, gs::ALL_DAYS, true, 120);
  CHECK(fx.at(MON, 5, 59, 50).fires.empty());  // first tick: nothing is due
  CHECK(fx.at(MON, 5, 59, 59).fires.empty());
  gs::Events e = fx.at(MON, 6, 0, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].slot == 0);
  CHECK(e.fires[0].zone_mask == 0x5u);
  CHECK(e.fires[0].pct == 120);
  CHECK(!e.fires[0].catch_up);
  CHECK(e.state_changed);
  CHECK(fx.s.state(0).last_fired_day == MON);
  CHECK(fx.s.state(0).pending == 0x5u);
  for (unsigned s = 1; s <= 300; s += 7)
    CHECK(fx.at(MON, 6, s / 60, s % 60).fires.empty());
  CHECK(fx.at(MON + 1, 5, 59, 59).fires.empty());
  CHECK(fx.at(MON + 1, 6, 0, 0).fires.size() == 1);
}

TEST_CASE("weekday_mask_respected") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x3, MON_WED_FRI);
  fx.at(MON + 1, 5, 59, 59);
  CHECK(fx.at(MON + 1, 6, 0, 0).fires.empty());  // Tuesday
  fx.at(MON + 1, 7, 0, 0);
  auto next = fx.s.next_run(fx.cfg, fx.n);
  REQUIRE(next.has_value());
  CHECK(next->day == MON + 2);  // Wednesday
  CHECK(next->start_minute == 360);
  CHECK(next->slot == 0);
  fx.at(MON + 2, 5, 59, 59);
  CHECK(fx.at(MON + 2, 6, 0, 0).fires.size() == 1);
}

TEST_CASE("disabled_and_master_off") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x3, gs::ALL_DAYS, false);
  fx.at(MON, 5, 59, 59);
  gs::Events e = fx.at(MON, 6, 0, 0);
  CHECK(e.fires.empty());
  CHECK(e.missed.empty());
  CHECK(fx.s.state(0).last_fired_day == gs::NEVER);
  CHECK(!fx.s.next_run(fx.cfg, fx.n).has_value());
  fx.cfg[0].enabled = true;
  fx.s.set_master(false);
  fx.at(MON + 1, 5, 59, 59);
  CHECK(fx.at(MON + 1, 6, 0, 0).fires.empty());
  CHECK(fx.s.state(0).last_fired_day == gs::NEVER);
  CHECK(!fx.s.next_run(fx.cfg, fx.n).has_value());
  CHECK(fx.s.day_runs(0, fx.cfg, fx.n).empty());
  // a boot with the master off: no catch-up, no missed
  Fx boot;
  boot.cfg[0] = slot(6, 0);
  boot.s.set_master(false);
  gs::Events b = boot.at(MON, 6, 20, 0);
  CHECK(b.fires.empty());
  CHECK(b.missed.empty());
}

TEST_CASE("same_minute_slots_fire_in_order") {
  Fx fx;
  fx.n = 3;
  fx.cfg[0] = slot(6, 0, 0x1);
  fx.cfg[1] = slot(7, 0, 0x2);
  fx.cfg[2] = slot(6, 0, 0x4);
  fx.at(MON, 5, 59, 59);
  gs::Events e = fx.at(MON, 6, 0, 0);
  REQUIRE(e.fires.size() == 2);
  CHECK(e.fires[0].slot == 0);
  CHECK(e.fires[1].slot == 2);
}

TEST_CASE("midnight_crossing") {
  Fx fx;
  fx.cfg[0] = slot(0, 0, 0x3, 0x02);  // Tuesday only
  fx.at(MON, 23, 59, 59);
  gs::Events e = fx.at(MON + 1, 0, 0, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(fx.s.state(0).last_fired_day == MON + 1);
  // a skipped second (the loop stalled over midnight) still crosses
  Fx fx2;
  fx2.cfg[0] = slot(0, 0);
  fx2.at(MON, 23, 59, 58);
  CHECK(fx2.at(MON + 1, 0, 0, 2).fires.size() == 1);
}

TEST_CASE("dst_spring_gap") {
  Fx fx;
  fx.n = 2;
  fx.cfg[0] = slot(2, 30);
  fx.cfg[1] = slot(3, 30);
  fx.raw(MON, 1 * 60 + 59, 59, 1000, 5000);
  // local jumps 01:59:59 -> 03:00:00 while UTC advances one second
  gs::Events e = fx.raw(MON, 3 * 60, 0, 1001, 6000);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].slot == 0);
  CHECK(fx.raw(MON, 3 * 60, 1, 1002, 7000).fires.empty());
  e = fx.raw(MON, 3 * 60 + 30, 0, 1001 + 1800, 6000 + 1800000);
  // (that tick is 1800 s later in UTC and in mono: continuous)
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].slot == 1);
}

TEST_CASE("dst_fall_back_no_double") {
  Fx fx;
  fx.cfg[0] = slot(2, 30);
  fx.raw(MON, 2 * 60 + 29, 59, 1000, 5000);
  CHECK(fx.raw(MON, 2 * 60 + 30, 0, 1001, 6000).fires.size() == 1);
  // 02:59:59 -> 02:00:00 (the hour repeats), then 02:30 is crossed again
  CHECK(fx.raw(MON, 2 * 60 + 59, 59, 1000 + 1799, 6000 + 1799000).fires.empty());
  CHECK(fx.raw(MON, 2 * 60, 0, 1000 + 1800, 6000 + 1800000).fires.empty());
  CHECK(fx.raw(MON, 2 * 60 + 29, 59, 1000 + 3599, 6000 + 3599000).fires.empty());
  CHECK(fx.raw(MON, 2 * 60 + 30, 0, 1000 + 3600, 6000 + 3600000).fires.empty());
  CHECK(fx.s.state(0).last_fired_day == MON);
}

TEST_CASE("boot_catch_up_inside_window") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x3);
  gs::Events e = fx.at(MON, 6, 20, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].catch_up);
  CHECK(e.fires[0].zone_mask == 0x3u);
  CHECK(fx.s.state(0).last_fired_day == MON);
  CHECK(e.missed.empty());
  CHECK(fx.at(MON, 6, 21, 0).fires.empty());
  // exactly at the end of the window
  Fx edge;
  edge.cfg[0] = slot(6, 0);
  CHECK(edge.at(MON, 7, 0, 0).fires.size() == 1);
  Fx over;
  over.cfg[0] = slot(6, 0);
  CHECK(over.at(MON, 7, 0, 1).fires.empty());
}

TEST_CASE("boot_missed_outside_window") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  gs::Events e = fx.at(MON, 7, 30, 0);
  CHECK(e.fires.empty());
  REQUIRE(e.missed.size() == 1);
  CHECK(e.missed[0].slot == 0);
  CHECK(e.missed[0].minutes_late == 90);
  CHECK(e.state_changed);
  CHECK(fx.s.state(0).last_fired_day == MON);
  CHECK(fx.s.state(0).result == gs::Result::MISSED);
  CHECK(fx.at(MON, 7, 31, 0).fires.empty());
  CHECK(fx.at(MON, 7, 31, 1).missed.empty());
  fx.at(MON + 1, 5, 59, 59);
  CHECK(fx.at(MON + 1, 6, 0, 0).fires.size() == 1);
  // window 0: a minute late is missed
  Fx zero;
  zero.s.set_catch_up_minutes(0);
  zero.cfg[0] = slot(6, 0);
  gs::Events z = zero.at(MON, 6, 1, 0);
  CHECK(z.fires.empty());
  REQUIRE(z.missed.size() == 1);
  CHECK(z.missed[0].minutes_late == 1);
  // slots of earlier days are never caught up
  Fx next;
  next.cfg[0] = slot(23, 50);
  gs::Events n = next.at(MON + 1, 0, 5, 0);
  CHECK(n.fires.empty());
  CHECK(n.missed.empty());
  // a slot whose start is still ahead is untouched
  Fx ahead;
  ahead.cfg[0] = slot(6, 0);
  CHECK(ahead.at(MON, 5, 0, 0).missed.empty());
}

TEST_CASE("boot_already_fired_today") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  fx.s.restore(0, MON, 0);
  gs::Events e = fx.at(MON, 6, 20, 0);
  CHECK(e.fires.empty());
  CHECK(e.missed.empty());
}

TEST_CASE("sync_jump_forward") {
  Fx fx;
  fx.n = 2;
  fx.cfg[0] = slot(6, 0);
  fx.cfg[1] = slot(5, 10);
  fx.at(MON, 5, 0, 0);
  // epoch +5400 s, monotonic +1 s
  gs::Events e = fx.jump(MON, 6, 30, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].slot == 0);
  CHECK(e.fires[0].catch_up);
  REQUIRE(e.missed.size() == 1);
  CHECK(e.missed[0].slot == 1);
  CHECK(e.missed[0].minutes_late == 80);
}

TEST_CASE("sync_jump_backward") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  fx.at(MON, 5, 59, 59);
  CHECK(fx.at(MON, 6, 0, 0).fires.size() == 1);
  CHECK(fx.jump(MON, 5, 50, 0).fires.empty());
  CHECK(fx.at(MON, 5, 59, 59).fires.empty());
  CHECK(fx.at(MON, 6, 0, 0).fires.empty());  // fired today
  CHECK(fx.at(MON + 1, 6, 0, 0, true).fires.size() == 1);  // a jump to the next day inside the window: catch-up
}

TEST_CASE("future_mark_cleared") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  fx.s.restore(0, MON + 30, 0x3);
  gs::Events e = fx.at(MON, 5, 0, 0);
  CHECK(e.future_cleared);
  CHECK(e.state_changed);
  CHECK(fx.s.state(0).last_fired_day == gs::NEVER);
  CHECK(fx.s.state(0).pending == 0u);
  fx.at(MON, 5, 59, 59);
  CHECK(fx.at(MON, 6, 0, 0).fires.size() == 1);
  // tomorrow's mark (clock a day ahead when it fired) is kept
  Fx keep;
  keep.cfg[0] = slot(6, 0);
  keep.s.restore(0, MON + 1, 0);
  CHECK(!keep.at(MON, 5, 0, 0).future_cleared);
}

TEST_CASE("invalid_clock") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  gs::Events e = fx.invalid();
  CHECK(e.fires.empty());
  CHECK(!fx.s.clock_valid());
  CHECK(!fx.s.next_run(fx.cfg, fx.n).has_value());
  fx.invalid();
  CHECK(fx.s.state(0).last_fired_day == gs::NEVER);
  // the clock becomes valid after the start: boot rules apply
  gs::Events v = fx.at(MON, 6, 10, 0);
  CHECK(v.clock_became_valid);
  REQUIRE(v.fires.size() == 1);
  CHECK(v.fires[0].catch_up);
  // an invalid tick in between resets continuity
  fx.at(MON, 6, 11, 0);
  fx.invalid();
  CHECK(fx.at(MON + 1, 5, 0, 0, true).clock_became_valid);
  CHECK(fx.s.next_run(fx.cfg, fx.n).has_value());
}

TEST_CASE("mono_wraps") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  fx.mono = 0xFFFFFF00u;
  fx.at(MON, 5, 59, 59);
  gs::Events e = fx.at(MON, 6, 0, 0);  // mono wraps to 0x000000E8 here
  REQUIRE(e.fires.size() == 1);
  CHECK(!e.fires[0].catch_up);  // continuous: fired by crossing
}

TEST_CASE("edit_after_fire") {
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  fx.at(MON, 5, 59, 59);
  CHECK(fx.at(MON, 6, 0, 0).fires.size() == 1);
  fx.cfg[0].start_minute = 8 * 60;
  fx.at(MON, 7, 59, 59);
  CHECK(fx.at(MON, 8, 0, 0).fires.empty());
  fx.at(MON + 1, 7, 59, 59);
  CHECK(fx.at(MON + 1, 8, 0, 0).fires.size() == 1);
}

TEST_CASE("multiplier_hook") {
  CHECK(gs::effective_pct(150, 100) == 150);
  CHECK(gs::effective_pct(150, 200) == 200);
  CHECK(gs::effective_pct(10, 50) == 10);
  CHECK(gs::effective_pct(100, 100) == 100);
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x3, gs::ALL_DAYS, true, 150);
  fx.s.set_global_pct(50);
  fx.at(MON, 5, 59, 59);
  gs::Events e = fx.at(MON, 6, 0, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].pct == 75);
}

TEST_CASE("next_run_and_day_runs") {
  Fx fx;
  fx.n = 3;
  fx.cfg[0] = slot(6, 0, 0x3, gs::ALL_DAYS);
  fx.cfg[1] = slot(18, 30, 0x3, 0x01);  // Mondays
  fx.cfg[2] = slot(12, 0, 0x3, gs::ALL_DAYS, false);
  fx.at(MON, 5, 0, 0);
  auto next = fx.s.next_run(fx.cfg, fx.n);
  REQUIRE(next.has_value());
  CHECK(next->slot == 0);
  CHECK(next->day == MON);
  // after the 06:00 run: the 18:30 slot is next today
  fx.at(MON, 5, 59, 59);
  fx.at(MON, 6, 0, 0);
  fx.at(MON, 6, 0, 5);
  next = fx.s.next_run(fx.cfg, fx.n);
  REQUIRE(next.has_value());
  CHECK(next->slot == 1);
  CHECK(next->start_minute == 18 * 60 + 30);
  std::vector<gs::DayRun> runs = fx.s.day_runs(0, fx.cfg, fx.n);
  REQUIRE(runs.size() == 2);
  CHECK(runs[0].slot == 0);
  CHECK(runs[0].state == gs::DayRunState::FIRED);
  CHECK(runs[1].slot == 1);
  CHECK(runs[1].state == gs::DayRunState::PENDING);
  // late evening on Monday: tomorrow 06:00 (the Monday-only slot is a week away)
  fx.at(MON, 20, 0, 0);
  next = fx.s.next_run(fx.cfg, fx.n);
  REQUIRE(next.has_value());
  CHECK(next->day == MON + 1);
  CHECK(next->slot == 0);
  // only the Monday slot is left: week wrap
  fx.cfg[0].enabled = false;
  next = fx.s.next_run(fx.cfg, fx.n);
  REQUIRE(next.has_value());
  CHECK(next->day == MON + 7);
  CHECK(next->slot == 1);
  // none
  fx.cfg[1].enabled = false;
  CHECK(!fx.s.next_run(fx.cfg, fx.n).has_value());
  // a missed and a skipped slot show as such, sorted by start
  Fx two;
  two.n = 3;
  two.cfg[0] = slot(9, 0);
  two.cfg[1] = slot(6, 0);
  two.cfg[2] = slot(7, 0);
  two.at(MON, 8, 0, 0);  // slot 1 and 2 missed (window 60: 06:00 is 120 late; 07:00 is 60 late -> catch-up)
  two.s.mark_skipped(2);
  std::vector<gs::DayRun> r = two.s.day_runs(0, two.cfg, two.n);
  REQUIRE(r.size() == 3);
  CHECK(r[0].slot == 1);
  CHECK(r[0].state == gs::DayRunState::MISSED);
  CHECK(r[1].slot == 2);
  CHECK(r[1].state == gs::DayRunState::SKIPPED);
  CHECK(r[2].slot == 0);
  CHECK(r[2].state == gs::DayRunState::PENDING);
  CHECK(two.s.day_runs(1, two.cfg, two.n).size() == 3);
  CHECK(two.s.day_runs(1, two.cfg, two.n)[0].state == gs::DayRunState::PENDING);
}

TEST_CASE("zone_done_marks_per_zone") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.at(MON, 5, 59, 59);
  fx.at(MON, 6, 0, 0);
  CHECK(fx.s.state(0).pending == 0x7u);
  CHECK(fx.s.zone_done(0));
  CHECK(fx.s.state(0).pending == 0x6u);
  CHECK(!fx.s.zone_done(0));  // already done
  CHECK(fx.s.zone_done(2));
  CHECK(fx.s.state(0).pending == 0x2u);
  CHECK(fx.s.state(0).last_fired_day == MON);
}

TEST_CASE("restart_reruns_only_pending_zones") {
  // power cut after zone 1 completed: restart inside the window runs zones 2 and 3 only
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.s.restore(0, MON, 0x6);
  gs::Events e = fx.at(MON, 6, 25, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].catch_up);
  CHECK(e.fires[0].zone_mask == 0x6u);
  CHECK(fx.s.state(0).pending == 0x6u);
  // the run completes zone by zone; nothing fires again
  CHECK(fx.at(MON, 6, 26, 0).fires.empty());
  fx.s.zone_done(1);
  fx.s.zone_done(2);
  CHECK(fx.s.state(0).pending == 0u);
  // a later sync jump does not repeat it
  CHECK(fx.jump(MON, 6, 40, 0).fires.empty());
}

TEST_CASE("restart_after_window_drops_pending") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.s.restore(0, MON, 0x4);
  gs::Events e = fx.at(MON, 8, 0, 0);
  CHECK(e.fires.empty());
  REQUIRE(e.missed.size() == 1);
  CHECK(e.missed[0].zone_mask == 0x4u);
  CHECK(fx.s.state(0).pending == 0u);
  CHECK(e.state_changed);
  // a mark from yesterday never resumes
  Fx old;
  old.cfg[0] = slot(6, 0, 0x7);
  old.s.restore(0, MON - 1, 0x4);
  gs::Events o = old.at(MON, 6, 10, 0);
  REQUIRE(o.fires.size() == 1);
  CHECK(o.fires[0].zone_mask == 0x7u);  // today's slot is a fresh run
}

TEST_CASE("mark_skipped_clears_pending") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x3);
  fx.at(MON, 5, 59, 59);
  fx.at(MON, 6, 0, 0);
  fx.s.mark_skipped(0);
  CHECK(fx.s.state(0).pending == 0u);
  CHECK(fx.s.state(0).result == gs::Result::SKIPPED);
  CHECK(fx.s.state(0).last_fired_day == MON);
  CHECK(fx.at(MON, 6, 5, 0).fires.empty());
}

TEST_CASE("clock_jump_while_running_does_not_refire") {
  // pending zones resume only on the first valid tick after boot, never on a later clock jump
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.at(MON, 5, 59, 59);
  CHECK(fx.at(MON, 6, 0, 0).fires.size() == 1);
  CHECK(fx.s.state(0).pending == 0x7u);
  gs::Events a = fx.jump(MON, 6, 20, 0);  // inside the window
  CHECK(a.fires.empty());
  CHECK(a.missed.empty());
  CHECK(fx.s.state(0).pending == 0x7u);
  gs::Events b = fx.jump(MON, 7, 50, 0);  // past the window: a running slot is not "missed", pending kept
  CHECK(b.fires.empty());
  CHECK(b.missed.empty());
  CHECK(fx.s.state(0).pending == 0x7u);
  CHECK(fx.s.state(0).result == gs::Result::RAN);
}

TEST_CASE("transient_invalid_clock_does_not_resume") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.at(MON, 5, 59, 59);
  CHECK(fx.at(MON, 6, 0, 0).fires.size() == 1);
  fx.invalid();
  gs::Events e = fx.at(MON, 6, 10, 0, true);
  CHECK(e.clock_became_valid);
  CHECK(e.fires.empty());
  CHECK(e.missed.empty());
  CHECK(fx.s.state(0).pending == 0x7u);
}

TEST_CASE("unfired_slot_is_still_caught_up_after_a_later_jump") {
  // Decision 3: a slot not yet fired today is caught up / missed on any discontinuity
  Fx fx;
  fx.cfg[0] = slot(6, 0);
  fx.at(MON, 5, 0, 0);
  gs::Events e = fx.jump(MON, 6, 10, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].catch_up);
}

TEST_CASE("resume_only_on_first_valid_tick_even_with_master_off_at_boot") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.s.restore(0, MON, 0x6);
  fx.s.set_master(false);
  fx.at(MON, 6, 10, 0);
  fx.s.set_master(true);
  gs::Events e = fx.jump(MON, 6, 20, 0);
  CHECK(e.fires.empty());
  CHECK(fx.s.state(0).pending == 0x6u);
}

TEST_CASE("stop_settles_the_slot_and_nothing_resumes_after_a_restart") {
  // Human decision 2026-10-11: a user STOP (or entering service mode) settles today's pending zones of every slot
  // ("stopped", not "missed"); a restart inside the window runs nothing. Only a power cut leaves zones pending.
  Fx fx;
  fx.n = 2;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.cfg[1] = slot(6, 30, 0x3);
  fx.at(MON, 5, 59, 59);
  fx.at(MON, 6, 0, 0);
  fx.s.zone_done(0);  // zone 1 completed; the user then pressed STOP during zone 2
  CHECK(fx.s.state(0).pending == 0x6u);
  const std::vector<uint8_t> stopped = fx.s.stop_pending();
  REQUIRE(stopped.size() == 1);  // slot 2 has not fired yet: nothing to settle
  CHECK(stopped[0] == 0);
  CHECK(fx.s.state(0).pending == 0u);
  CHECK(fx.s.state(0).result == gs::Result::STOPPED);
  CHECK(fx.s.state(0).last_fired_day == MON);  // still "handled today": no catch-up, no second run
  CHECK(fx.s.stop_pending().empty());
  const std::vector<gs::DayRun> runs = fx.s.day_runs(0, fx.cfg, 2);
  REQUIRE(runs.size() == 2);
  CHECK(runs[0].state == gs::DayRunState::STOPPED);
  CHECK(runs[1].state == gs::DayRunState::PENDING);
  Fx rebooted;
  rebooted.n = 2;
  rebooted.cfg[0] = slot(6, 0, 0x7);
  rebooted.cfg[1] = slot(6, 30, 0x3);
  rebooted.s.restore(0, MON, fx.s.state(0).pending);
  gs::Events e = rebooted.at(MON, 6, 10, 0);
  CHECK(e.fires.empty());
  CHECK(e.missed.empty());
}

TEST_CASE("stop_settles_every_slot_with_pending_zones") {
  Fx fx;
  fx.n = 2;
  fx.cfg[0] = slot(6, 0, 0x1);
  fx.cfg[1] = slot(6, 0, 0x2);
  fx.at(MON, 5, 59, 59);
  CHECK(fx.at(MON, 6, 0, 0).fires.size() == 2);  // the second slot's zones wait in the engine queue
  const std::vector<uint8_t> stopped = fx.s.stop_pending();
  REQUIRE(stopped.size() == 2);
  CHECK(fx.s.state(0).pending == 0u);
  CHECK(fx.s.state(1).pending == 0u);
  CHECK(fx.s.state(1).result == gs::Result::STOPPED);
}

TEST_CASE("a_power_cut_without_a_stop_still_resumes_the_pending_zones") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.at(MON, 5, 59, 59);
  fx.at(MON, 6, 0, 0);
  fx.s.zone_done(0);
  Fx rebooted;
  rebooted.cfg[0] = slot(6, 0, 0x7);
  rebooted.s.restore(0, MON, fx.s.state(0).pending);
  gs::Events e = rebooted.at(MON, 6, 10, 0);
  REQUIRE(e.fires.size() == 1);
  CHECK(e.fires[0].zone_mask == 0x6u);
}

TEST_CASE("a_stopped_slot_does_not_fire_again_today_but_fires_tomorrow") {
  Fx fx;
  fx.cfg[0] = slot(6, 0, 0x7);
  fx.at(MON, 5, 59, 59);
  fx.at(MON, 6, 0, 0);
  fx.s.stop_pending();
  CHECK(fx.at(MON, 12, 0, 0).fires.empty());
  fx.at(MON + 1, 5, 59, 59);
  CHECK(fx.at(MON + 1, 6, 0, 0).fires.size() == 1);
}
