// Unit tests for the screen data of components/gp (task 025 part A): run_total,
// soil, the card formatters and the bed-card layout (host compiler, no ESPHome headers).
#include "minitest.h"

#include <cstring>
#include <string>

#include "gp/format.h"
#include "gp/history.h"
#include "gp/layout.h"
#include "gp/zone_model.h"
namespace gp = esphome::gp;

namespace {

bool printable_ascii(const std::string &s) {
  for (char c : s) {
    if (c < 0x20 || c > 0x7e)
      return false;
  }
  return true;
}

gp::GroupInput group_of(size_t zones) {
  gp::GroupInput g;
  g.zone_count = zones;
  for (size_t i = 0; i < zones; i++) {
    g.zones[i].name = "Greenhouse bed";
    g.zones[i].run_duration = 300;
    g.start_source[i] = gp::Source::MANUAL;
  }
  return g;
}

gp::ZoneView view(gp::ZoneState state) {
  gp::ZoneView v;
  v.present = true;
  v.state = state;
  v.run_duration = 300;
  return v;
}

// design/tokens.json colours (tests/test_screens_gp.py checks the header against the file)
bool is_token_color(uint32_t c) {
  static const uint32_t TOKENS[] = {0x131313, 0x1c1b1b, 0x201f1f, 0x3f4a3c, 0x353534, 0xe5e2e1, 0xbecab9, 0x78dc77, 0x4caf50,
                                    0x003c0b, 0x9ecaff, 0x1e95f2, 0x002b4d, 0xffb870, 0xe18500, 0x93000a, 0xffdad6};
  for (uint32_t t : TOKENS) {
    if (t == c)
      return true;
  }
  return false;
}

gp::fmt::Moment at(int day, int month, int hour, int minute) { return gp::fmt::Moment{true, 2026, month, day, hour, minute}; }

}  // namespace

TEST_CASE("run_total_and_progress") {
  gp::GroupModel m;
  gp::GroupInput g = group_of(1);
  m.refresh(1000, 0, g);
  CHECK(m.zone(0).run_total == 0u);
  CHECK(gp::fmt::card_progress(m.zone(0)) == 0);
  g.zones[0].running = true;
  g.zones[0].has_time_left = true;
  g.zones[0].time_left = 600;  // longer than run_duration (a multiplier / manual duration)
  g.active_count = 1;
  g.active[0] = 0;
  m.refresh(2000, 0, g);
  CHECK(m.zone(0).run_total == 600u);
  CHECK(gp::fmt::card_progress(m.zone(0)) == 0);
  g.zones[0].time_left = 300;
  m.refresh(3000, 0, g);
  CHECK(m.zone(0).run_total == 600u);  // kept for the whole run
  CHECK(gp::fmt::card_progress(m.zone(0)) == 50);
  g.zones[0].time_left = 0;
  m.refresh(4000, 0, g);
  CHECK(gp::fmt::card_progress(m.zone(0)) == 100);
  g.zones[0].running = false;
  g.zones[0].has_time_left = false;
  g.active_count = 0;
  m.refresh(5000, 0, g);  // the end of the run clears it
  CHECK(m.zone(0).run_total == 0u);
  CHECK(gp::fmt::card_progress(m.zone(0)) == 0);
  // the time left is unknown at the first running sample: total is taken from the first sample that has it
  g.zones[0].running = true;
  g.active_count = 1;
  m.refresh(6000, 0, g);
  CHECK(m.zone(0).run_total == 0u);
  g.zones[0].has_time_left = true;
  g.zones[0].time_left = 120;
  m.refresh(7000, 0, g);
  CHECK(m.zone(0).run_total == 120u);
}

TEST_CASE("zone_soil_in_view") {
  gp::GroupModel m;
  gp::GroupInput g = group_of(1);
  m.refresh(1000, 0, g);
  CHECK(!m.zone(0).soil.has_value());
  g.zones[0].has_soil = true;
  g.zones[0].soil = 57.0f;
  m.refresh(2000, 0, g);
  const uint32_t at57 = m.summary().revision;
  CHECK(m.zone(0).soil.has_value());
  g.zones[0].soil = 57.6f;
  m.refresh(3000, 0, g);
  CHECK(*m.zone(0).soil == 57.6f);
  const uint32_t at576 = m.summary().revision;
  CHECK(at576 != at57);  // 57 -> 58 whole percent
  g.zones[0].soil = 57.8f;
  m.refresh(4000, 0, g);
  CHECK(m.summary().revision == at576);  // 57.6 -> 57.8 shows the same text
  g.zones[0].has_soil = false;
  m.refresh(5000, 0, g);
  CHECK(!m.zone(0).soil.has_value());
  CHECK(m.summary().revision != at576);
}

TEST_CASE("fmt_card_state_and_colour") {
  using gp::ZoneState;
  gp::ZoneView v = view(ZoneState::RUNNING);
  CHECK(gp::fmt::card_state(v) == "Watering");
  CHECK(gp::fmt::card_state_color(v) == 0x78dc77u);
  CHECK(gp::fmt::card_edge_color(v) == 0x4caf50u);
  v = view(ZoneState::QUEUED);
  v.queue_position = 1;
  CHECK(gp::fmt::card_state(v) == "Queued #2");
  CHECK(gp::fmt::card_state_color(v) == 0x9ecaffu);
  CHECK(gp::fmt::card_edge_color(v) == 0x1e95f2u);
  v.queue_position.reset();
  CHECK(gp::fmt::card_state(v) == "Queued");
  v = view(ZoneState::DISABLED);
  CHECK(gp::fmt::card_state(v) == "Off");
  CHECK(gp::fmt::card_state_color(v) == 0xbecab9u);
  CHECK(gp::fmt::card_edge_color(v) == 0x3f4a3cu);
  v = view(ZoneState::LOCKED);
  CHECK(gp::fmt::card_state(v) == "Locked");
  CHECK(gp::fmt::card_state_color(v) == 0xffb870u);
  CHECK(gp::fmt::card_edge_color(v) == 0xe18500u);
  v = view(ZoneState::PAUSED);
  CHECK(gp::fmt::card_state(v) == "Paused");
  CHECK(gp::fmt::card_state_color(v) == 0xffb870u);
  CHECK(gp::fmt::card_edge_color(v) == 0xe18500u);
  v = view(ZoneState::SKIPPED);
  CHECK(gp::fmt::card_state(v) == "Skipped");
  CHECK(gp::fmt::card_state_color(v) == 0xbecab9u);
  CHECK(gp::fmt::card_edge_color(v) == 0x3f4a3cu);
  v = view(ZoneState::IDLE);
  CHECK(gp::fmt::card_state(v) == "Idle");
  CHECK(gp::fmt::card_edge_color(v) == 0x3f4a3cu);
  // no red anywhere: error-fill is the STOP button only
  const ZoneState all[] = {ZoneState::IDLE, ZoneState::SKIPPED, ZoneState::QUEUED, ZoneState::DISABLED,
                           ZoneState::PAUSED, ZoneState::RUNNING, ZoneState::LOCKED};
  for (ZoneState s : all) {
    gp::ZoneView z = view(s);
    CHECK(is_token_color(gp::fmt::card_state_color(z)));
    CHECK(is_token_color(gp::fmt::card_edge_color(z)));
    CHECK(gp::fmt::card_edge_color(z) != 0x93000au);
    CHECK(printable_ascii(gp::fmt::card_state(z)));
  }
}

TEST_CASE("fmt_card_name") {
  CHECK(gp::fmt::card_name("Greenhouse bed 1", "Greenhouse") == "Bed 1");
  CHECK(gp::fmt::card_name("Tomatoes", "Greenhouse") == "Tomatoes");
  CHECK(gp::fmt::card_name("Greenhouse", "Greenhouse") == "Greenhouse");
  CHECK(gp::fmt::card_name("", "Greenhouse").empty());
}

TEST_CASE("fmt_card_time") {
  gp::ZoneView v = view(gp::ZoneState::RUNNING);
  v.time_left = 299;
  CHECK(gp::fmt::card_time(v) == "04:59");
  v.time_left = 3600 + 125;
  CHECK(gp::fmt::card_time(v) == "1:02:05");
  v.time_left = 0;
  CHECK(gp::fmt::card_time(v) == "00:00");
  v = view(gp::ZoneState::PAUSED);
  v.time_left = 61;
  CHECK(gp::fmt::card_time(v) == "01:01");
  v = view(gp::ZoneState::IDLE);
  CHECK(gp::fmt::card_time(v) == "5 min");
  v.run_duration = 45;
  CHECK(gp::fmt::card_time(v) == "45 s");
  v.run_duration = 0;
  CHECK(gp::fmt::card_time(v) == "--");
  v = view(gp::ZoneState::RUNNING);  // running with no time left known: the run duration
  CHECK(gp::fmt::card_time(v) == "5 min");
}

TEST_CASE("fmt_card_last") {
  const gp::fmt::Moment today = at(13, 10, 9, 30);
  CHECK(gp::fmt::card_last(at(13, 10, 6, 0), today, true, 300) == "06:00 5m");
  CHECK(gp::fmt::card_last(at(12, 10, 6, 0), today, true, 300) == "12 Oct 5m");
  CHECK(gp::fmt::card_last(gp::fmt::Moment{}, today, true, 300) == "--:-- 5m");
  CHECK(gp::fmt::card_last(at(13, 10, 6, 0), today, true, 45) == "06:00 45s");
  CHECK(gp::fmt::card_last(at(13, 10, 6, 0), gp::fmt::Moment{}, true, 300) == "13 Oct 5m");  // no clock now
  CHECK(gp::fmt::card_last(at(13, 10, 6, 0), today, false, 0) == "-");
  for (uint32_t d : {0u, 45u, 300u, 3300u, 7200u}) {
    for (int day : {12, 13, 31}) {
      const std::string s = gp::fmt::card_last(at(day, 12, 23, 59), today, true, d);
      CHECK(printable_ascii(s));
      CHECK(s.size() <= 20);
    }
  }
}

TEST_CASE("fmt_soil") {
  CHECK(gp::fmt::card_soil(std::optional<float>(57.6f)) == "Soil 58%");
  CHECK(gp::fmt::card_soil(std::optional<float>(57.4f)) == "Soil 57%");
  CHECK(gp::fmt::card_soil(std::optional<float>(0.0f)) == "Soil 0%");
  CHECK(gp::fmt::card_soil(std::optional<float>(130.0f)) == "Soil 100%");
  CHECK(gp::fmt::card_soil(std::optional<float>(-3.0f)) == "Soil 0%");
  CHECK(gp::fmt::card_soil(std::optional<float>()).empty());
}

TEST_CASE("layout_bed_cards") {
  using gp::layout::bed_card;
  for (size_t count = 1; count <= 6; count++) {
    int visible = 0;
    gp::layout::CardRect rects[6];
    for (size_t slot = 0; slot < 6; slot++) {
      rects[slot] = bed_card(count, slot);
      CHECK(rects[slot].visible == (slot < count));
      if (!rects[slot].visible)
        continue;
      visible++;
      CHECK(rects[slot].compact == (count > 3));
      CHECK(rects[slot].x >= 8);
      CHECK(rects[slot].y >= 48);
      CHECK(rects[slot].x + rects[slot].w <= 312);
      CHECK(rects[slot].y + rects[slot].h <= 168);
      if (!rects[slot].compact)
        CHECK(rects[slot].h >= 4 + 20 + 4 + 50);  // room for the info lines plus a 20 px button row
    }
    CHECK(visible == static_cast<int>(count));
    for (size_t a = 0; a < count; a++) {
      for (size_t b = a + 1; b < count; b++) {
        const gp::layout::CardRect &p = rects[a], &q = rects[b];
        const bool apart = p.x + p.w + 6 <= q.x || q.x + q.w + 6 <= p.x || p.y + p.h + 6 <= q.y || q.y + q.h + 6 <= p.y;
        CHECK(apart);  // no overlap, at least the 6 px gap
      }
    }
  }
  // the documented geometry
  gp::layout::CardRect r = bed_card(1, 0);
  CHECK(r.x == 8 && r.y == 48 && r.w == 304 && r.h == 120);
  r = bed_card(2, 1);
  CHECK(r.x == 163 && r.w == 149 && r.h == 120);
  r = bed_card(3, 2);
  CHECK(r.x == 214 && r.w == 97 && r.h == 120);
  r = bed_card(4, 3);
  CHECK(r.x == 8 && r.y == 111 && r.w == 97 && r.h == 57);
  r = bed_card(6, 5);
  CHECK(r.x == 214 && r.y == 111 && r.w == 97 && r.h == 57);
  // a count beyond six and a slot beyond the table are hidden
  CHECK(!bed_card(7, 6).visible);
  CHECK(!bed_card(0, 0).visible);
  CHECK(!bed_card(3, 9).visible);
}
