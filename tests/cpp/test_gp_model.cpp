// Unit tests for components/gp/{zone_model,history,format}.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <cstring>
#include <string>

#include "gp/format.h"
#include "gp/history.h"
#include "gp/zone_model.h"
namespace gp = esphome::gp;

namespace {

gp::ZoneInput idle() {
  gp::ZoneInput in;
  in.name = "Greenhouse bed 1";
  in.run_duration = 300;
  return in;
}

gp::GroupInput group_of(size_t zones) {
  gp::GroupInput g;
  g.zone_count = zones;
  for (size_t i = 0; i < zones; i++) {
    g.zones[i] = idle();
    g.start_source[i] = gp::Source::MANUAL;
  }
  return g;
}

bool printable_ascii(const std::string &s) {
  for (char c : s) {
    if (c < 0x20 || c > 0x7e)
      return false;
  }
  return true;
}

}  // namespace

TEST_CASE("state_precedence") {
  // table over (locked, running, paused, disabled, queued, skipped): the highest precedence wins
  for (int mask = 0; mask < 64; mask++) {
    gp::ZoneInput in = idle();
    in.locked = mask & 1;
    in.running = mask & 2;
    in.paused = mask & 4;
    in.enabled = !(mask & 8);
    in.queued = mask & 16;
    const bool skipped = mask & 32;
    gp::ZoneState expect = gp::ZoneState::IDLE;
    if (skipped)
      expect = gp::ZoneState::SKIPPED;
    if (in.queued)
      expect = gp::ZoneState::QUEUED;
    if (!in.enabled)
      expect = gp::ZoneState::DISABLED;
    if (in.paused)
      expect = gp::ZoneState::PAUSED;
    if (in.running)
      expect = gp::ZoneState::RUNNING;
    if (in.locked)
      expect = gp::ZoneState::LOCKED;
    CHECK(gp::resolve_state(in, skipped) == expect);
  }
}

TEST_CASE("skipped_expiry") {
  gp::ZoneTracker t;
  gp::ZoneView v;
  gp::ZoneInput in = idle();
  t.update(1000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::IDLE);
  // a skip record appears
  in.has_skip = true;
  in.skip_stamp = 2000;
  in.skip_text = "soil moisture 72.0 > 60.0";
  t.update(2100, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::SKIPPED);
  CHECK(std::strcmp(v.skip_reason, "soil moisture 72.0 > 60.0") == 0);
  // stays until the zone is queued again
  in.queued = true;
  t.update(3000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::QUEUED);
  in.queued = false;
  t.update(4000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::IDLE);
  // a new skip (new stamp), then the zone runs: cleared
  in.skip_stamp = 5000;
  t.update(5100, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::SKIPPED);
  in.running = true;
  t.update(6000, 0, 0, in, gp::Source::MANUAL, v);
  in.running = false;
  t.update(7000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::IDLE);
  // expiry after 12 h
  in.skip_stamp = 8000;
  t.update(8100, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::SKIPPED);
  t.update(8100 + gp::SKIP_VISIBLE_MS - 1, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::SKIPPED);
  t.update(8100 + gp::SKIP_VISIBLE_MS, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::IDLE);
  // millis() wrap: skip seen shortly before 2^32, expiry measured with unsigned arithmetic
  in.skip_stamp = 4294967000u;
  t.update(4294967100u, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::SKIPPED);
  t.update(4294967100u + 1000u, 0, 0, in, gp::Source::MANUAL, v);  // wrapped
  CHECK(v.state == gp::ZoneState::SKIPPED);
  t.update(4294967100u + gp::SKIP_VISIBLE_MS, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.state == gp::ZoneState::IDLE);
}

TEST_CASE("last_watering_edges") {
  gp::ZoneTracker t;
  gp::ZoneView v;
  gp::RunRecord rec;
  gp::ZoneInput in = idle();
  t.update(0, 1000000, 2, in, gp::Source::MANUAL, v);
  CHECK(!v.last_duration.has_value());
  CHECK(!v.last_start_epoch.has_value());
  // run 10 s with a valid clock
  in.running = true;
  t.update(10000, 1000010, 2, in, gp::Source::QUEUE, v);
  REQUIRE(v.last_start_epoch.has_value());
  CHECK(*v.last_start_epoch == 1000010u);
  REQUIRE(v.last_start_uptime.has_value());
  CHECK(*v.last_start_uptime == 10u);
  CHECK(!t.take_completed(rec));  // still running
  t.update(14000, 1000014, 2, in, gp::Source::QUEUE, v);
  // paused for 5 s (008 semantics: the run is interrupted and resumes): one run, the gap is not counted
  in.running = false;
  in.paused = true;
  t.update(14000, 1000014, 2, in, gp::Source::QUEUE, v);
  CHECK(!t.take_completed(rec));
  t.update(19000, 1000019, 2, in, gp::Source::QUEUE, v);
  in.running = true;
  in.paused = false;
  t.update(19000, 1000019, 2, in, gp::Source::QUEUE, v);
  CHECK(*v.last_start_epoch == 1000010u);
  t.update(25000, 1000025, 2, in, gp::Source::QUEUE, v);
  in.running = false;
  t.update(25000, 1000025, 2, in, gp::Source::QUEUE, v);
  REQUIRE(t.take_completed(rec));
  CHECK(rec.zone == 2);
  CHECK(rec.duration == 10u);  // 4 s + 6 s open, 5 s paused not counted
  CHECK(rec.epoch == 1000010u);
  CHECK(rec.source == gp::Source::QUEUE);
  CHECK(!t.take_completed(rec));
  REQUIRE(v.last_duration.has_value());
  CHECK(*v.last_duration == 10u);
  // clock not valid: epoch stays empty, uptime is kept
  in.running = true;
  t.update(30000, 0, 2, in, gp::Source::MANUAL, v);
  REQUIRE(v.last_start_uptime.has_value());
  CHECK(*v.last_start_uptime == 30u);
  CHECK(!v.last_start_epoch.has_value());
  in.running = false;
  t.update(33000, 0, 2, in, gp::Source::MANUAL, v);
  REQUIRE(t.take_completed(rec));
  CHECK(rec.epoch == 0u);
  CHECK(rec.duration == 3u);
  // restored values from flash
  gp::ZoneTracker r;
  r.restore(1234567, 42);
  r.update(5, 0, 0, idle(), gp::Source::MANUAL, v);
  REQUIRE(v.last_start_epoch.has_value());
  CHECK(*v.last_start_epoch == 1234567u);
  CHECK(*v.last_duration == 42u);
  CHECK(!v.last_start_uptime.has_value());
}

TEST_CASE("summary_now_next") {
  gp::GroupModel m;
  gp::GroupInput g = group_of(3);
  m.refresh(1000, 0, g);
  CHECK(m.summary().zone_count == 3);
  CHECK(!m.summary().running);
  CHECK(m.summary().now_zone == -1);
  CHECK(m.summary().next_zone == -1);
  CHECK(m.summary().queue_length == 0);
  const uint32_t rev0 = m.summary().revision;
  // nothing changed: same revision
  m.refresh(2000, 0, g);
  CHECK(m.summary().revision == rev0);
  // queue zones 0 and 2, run zone 1
  g.queue_count = 2;
  g.queue[0] = 0;
  g.queue[1] = 2;
  g.zones[0].queued = true;
  g.zones[0].queue_pos = 0;
  g.zones[2].queued = true;
  g.zones[2].queue_pos = 1;
  g.queue_time = 180;
  m.refresh(3000, 0, g);
  CHECK(m.summary().revision != rev0);
  CHECK(m.summary().next_zone == 0);
  CHECK(m.summary().queue_length == 2);
  CHECK(m.summary().queue_time == 180u);
  CHECK(m.zone(0).state == gp::ZoneState::QUEUED);
  REQUIRE(m.zone(2).queue_position.has_value());
  CHECK(*m.zone(2).queue_position == 1);
  g.active_count = 1;
  g.active[0] = 1;
  g.zones[1].running = true;
  g.zones[1].has_time_left = true;
  g.zones[1].time_left = 120;
  m.refresh(4000, 0, g);
  CHECK(m.summary().running);
  CHECK(m.summary().now_zone == 1);
  CHECK(m.summary().has_now_left);
  CHECK(m.summary().now_left == 120u);
  CHECK(m.zone(1).state == gp::ZoneState::RUNNING);
  CHECK(*m.zone(1).time_left == 120u);
  const uint32_t rev1 = m.summary().revision;
  m.refresh(4100, 0, g);
  CHECK(m.summary().revision == rev1);
  g.zones[1].time_left = 119;  // the countdown bumps the revision once per second
  m.refresh(5000, 0, g);
  CHECK(m.summary().revision != rev1);
  // empty queue again: no next
  g.queue_count = 0;
  g.zones[0].queued = false;
  g.zones[2].queued = false;
  m.refresh(6000, 0, g);
  CHECK(m.summary().next_zone == -1);
}

TEST_CASE("absent_zone") {
  gp::GroupModel m;
  gp::GroupInput g = group_of(3);
  m.refresh(1000, 0, g);
  CHECK(m.zone(2).present);
  for (size_t i = 3; i < 256; i++) {
    CHECK(!m.zone(i).present);
    CHECK(m.zone(i).state == gp::ZoneState::IDLE);
  }
  CHECK(!m.zone(static_cast<size_t>(-1)).present);
}

TEST_CASE("history_ring") {
  gp::History<4> h;
  CHECK(h.size() == 0);
  for (uint32_t i = 1; i <= 6; i++) {
    gp::HistoryEntry e{};
    e.epoch = i;
    e.duration = i * 10;
    e.zone = static_cast<uint8_t>(i);
    h.push(e);
  }
  CHECK(h.size() == 4);
  CHECK(h.at(0).epoch == 6u);  // newest first
  CHECK(h.at(3).epoch == 3u);
  CHECK(h.at(4).epoch == 0u);  // out of range: zeroed entry
}

TEST_CASE("persist_blob_full_ring_round_trip") {
  gp::PersistBlob a;
  for (uint32_t i = 0; i < 130; i++)
    a.history.push(gp::HistoryEntry{1000 + i, 10 + i, static_cast<uint8_t>(i % 4), 1, 0});
  for (size_t z = 0; z < gp::MAX_ZONES; z++)
    a.last[z] = gp::LastRun{5000 + static_cast<uint32_t>(z), 60 + static_cast<uint32_t>(z)};
  gp::PersistBlob b;
  std::memcpy(&b, &a, sizeof(a));  // what the preference layer stores and returns
  CHECK(b.valid());
  CHECK(b.history.size() == 100u);
  CHECK(b.history.at(0).epoch == 1129u);  // newest
  CHECK(b.history.at(99).epoch == 1030u);  // 31st pushed entry (the oldest still kept)
  for (size_t z = 0; z < gp::MAX_ZONES; z++) {
    CHECK(b.last[z].epoch == 5000u + z);
    CHECK(b.last[z].duration == 60u + z);
  }
}

TEST_CASE("persist_blob") {
  gp::PersistBlob b;
  CHECK(b.valid());
  b.history.head = 200;
  CHECK(!b.valid());
  gp::PersistBlob c;
  c.magic = 1;
  CHECK(!c.valid());
  CHECK(gp::HISTORY_LENGTH == 100);
}

TEST_CASE("format_lines") {
  gp::GroupModel m;
  gp::GroupInput g = group_of(3);
  g.zones[0].name = "Greenhouse bed 1";
  m.refresh(1000, 0, g);
  const gp::GroupSummary &idle_summary = m.summary();
  CHECK(gp::fmt::status_line(idle_summary) == "Irrigation: idle");
  CHECK(gp::fmt::modes_line(idle_summary) == "AA:off  Q:0");
  CHECK(gp::fmt::queue_line(idle_summary) == "Queue: (empty)");
  CHECK(gp::fmt::home_status(idle_summary) == "Idle");
  CHECK(gp::fmt::zone_left_line(idle_summary) == "Zone left: --:--:--");
  CHECK(gp::fmt::total_left_line(idle_summary) == "Total left: --:--:--");
  CHECK(gp::fmt::saver_bed(idle_summary).empty());
  CHECK(gp::fmt::durations_line(m) == "Dur: B1 5  B2 5  B3 5 min");
  CHECK(gp::fmt::valve_test_row(m.zone(0)) == "closed");
  CHECK(gp::fmt::valve_test_color(m.zone(0)) == 0xbecab9u);

  // two zones active, auto advance on, queue with a zone
  g.auto_advance = true;
  g.active_count = 2;
  g.active[0] = 0;
  g.active[1] = 2;
  g.zones[0].running = true;
  g.zones[0].has_time_left = true;
  g.zones[0].time_left = 65;
  g.zones[2].running = true;
  g.zones[2].has_time_left = true;
  g.zones[2].time_left = 3725;
  g.queue_count = 1;
  g.queue[0] = 1;
  g.zones[1].queued = true;
  g.zones[1].queue_pos = 0;
  g.queue_time = 125;
  g.has_total_left = true;
  g.total_left = 3725;
  m.refresh(2000, 0, g);
  const gp::GroupSummary &s = m.summary();
  CHECK(gp::fmt::status_line(s) == "Running: B1 B3");
  CHECK(gp::fmt::modes_line(s) == "AA:on  Q:1");
  CHECK(gp::fmt::queue_line(s) == "Queue: 00:02:05 next B2");
  CHECK(gp::fmt::home_status(s) == "Watering");
  CHECK(gp::fmt::zone_left_line(s) == "Zone left: 00:01:05");  // the smallest of the active zones
  CHECK(gp::fmt::total_left_line(s) == "Total left: 01:02:05");
  CHECK(gp::fmt::saver_bed(s) == "Bed 1+");
  CHECK(gp::fmt::valve_test_row(m.zone(0)) == "OPEN - 65 s");
  CHECK(gp::fmt::valve_test_color(m.zone(0)) == 0x78dc77u);
  CHECK(gp::fmt::valve_test_row(m.zone(1)) == "closed");

  // watchdog: status words and a locked row
  g.watchdog_tripped = true;
  g.zones[1].locked = true;
  g.zones[1].queued = false;
  g.queue_count = 0;
  g.queue_time = 0;
  m.refresh(3000, 0, g);
  CHECK(gp::fmt::status_line(m.summary()) == "Watchdog: locked");
  CHECK(gp::fmt::home_status(m.summary()) == "Alarm");
  CHECK(gp::fmt::valve_test_row(m.zone(1)) == "locked");
  CHECK(gp::fmt::valve_test_color(m.zone(1)) == 0xbecab9u);
  CHECK(gp::fmt::ha_status(m.summary()) == "Locked");

  // single active zone
  gp::GroupInput one = group_of(3);
  one.active_count = 1;
  one.active[0] = 1;
  one.zones[1].running = true;
  m.refresh(4000, 0, one);
  CHECK(gp::fmt::saver_bed(m.summary()) == "Bed 2");
  CHECK(gp::fmt::ha_status(m.summary()) == "Watering B2");
  CHECK(gp::fmt::valve_test_row(m.zone(1)) == "OPEN - 0 s");

  // texts are printable ASCII and fit the documented buffers
  CHECK(printable_ascii(gp::fmt::status_line(s)));
  CHECK(printable_ascii(gp::fmt::durations_line(m)));
  CHECK(gp::fmt::status_line(s).size() < gp::fmt::LABEL_MAX);
  gp::GroupInput many = group_of(gp::MAX_ZONES);
  many.active_count = gp::MAX_ZONES;
  for (size_t i = 0; i < gp::MAX_ZONES; i++) {
    many.active[i] = i;
    many.zones[i].running = true;
    many.zones[i].run_duration = 55 * 60;
  }
  m.refresh(5000, 0, many);
  CHECK(gp::fmt::status_line(m.summary()).size() < gp::fmt::LABEL_MAX);
  CHECK(gp::fmt::durations_line(m).size() < gp::fmt::LABEL_MAX);
  CHECK(gp::fmt::ha_status(m.summary()).size() < gp::fmt::LABEL_MAX);
  CHECK(printable_ascii(gp::fmt::durations_line(m)));
}

TEST_CASE("run_source") {
  gp::GroupModel m;
  gp::GroupInput g = group_of(2);
  g.start_source[1] = gp::Source::SERVICE;
  m.refresh(1000, 0, g);
  g.zones[1].running = true;
  g.active_count = 1;
  g.active[0] = 1;
  m.refresh(2000, 0, g);
  g.zones[1].running = false;
  g.active_count = 0;
  m.refresh(5000, 0, g);
  gp::RunRecord rec;
  REQUIRE(m.take_completed(rec));
  CHECK(rec.zone == 1);
  CHECK(rec.source == gp::Source::SERVICE);
  CHECK(rec.duration == 3u);
  CHECK(!m.take_completed(rec));
  // a service run does not become the zone's last watering
  CHECK(!m.zone(1).last_duration.has_value());
  CHECK(!m.zone(1).last_start_uptime.has_value());
}


TEST_CASE("saver_date_formats") {
  // ESPTime: day_of_week 1 = Sunday .. 7 = Saturday.
  CHECK(gp::fmt::saver_date(true, 6, 16, 10) == "Friday - 16 Oct");
  CHECK(gp::fmt::saver_date(true, 1, 6, 1) == "Sunday - 6 Jan");
  CHECK(gp::fmt::saver_date(true, 7, 31, 12) == "Saturday - 31 Dec");
}

TEST_CASE("saver_date_fits_the_label") {
  // longest: Wednesday - 30 Sep
  const std::string longest = gp::fmt::saver_date(true, 4, 30, 9);
  CHECK(longest == "Wednesday - 30 Sep");
  for (int dow = 1; dow <= 7; dow++) {
    for (int month = 1; month <= 12; month++) {
      const std::string s = gp::fmt::saver_date(true, dow, 28, month);
      CHECK(!s.empty());
      CHECK(s.size() < gp::fmt::LABEL_MAX);
      CHECK(printable_ascii(s));
    }
  }
}

TEST_CASE("saver_date_rejects_invalid") {
  CHECK(gp::fmt::saver_date(false, 6, 16, 10).empty());
  CHECK(gp::fmt::saver_date(true, 0, 16, 10).empty());
  CHECK(gp::fmt::saver_date(true, 8, 16, 10).empty());
  CHECK(gp::fmt::saver_date(true, 6, 16, 0).empty());
  CHECK(gp::fmt::saver_date(true, 6, 16, 13).empty());
  CHECK(gp::fmt::saver_date(true, 6, 0, 10).empty());
  CHECK(gp::fmt::saver_date(true, 6, 32, 10).empty());
}

TEST_CASE("version_short_strips_the_config_hash") {
  CHECK(gp::fmt::version_short("2026.9.1 (config hash 0x1a2b3c4d)") == "2026.9.1");
  CHECK(gp::fmt::version_short("2026.9.1") == "2026.9.1");
  CHECK(gp::fmt::version_short("2026.10.0b1 Oct 17 2026, 10:00:00") == "2026.10.0b1");
  CHECK(gp::fmt::version_short("") == "");
  CHECK(gp::fmt::version_short(" leading") == "");
  CHECK(gp::fmt::version_short_or_dash(false, "2026.9.1 (x)") == "--");
  CHECK(gp::fmt::version_short_or_dash(true, "2026.9.1 (x)") == "2026.9.1");
}
