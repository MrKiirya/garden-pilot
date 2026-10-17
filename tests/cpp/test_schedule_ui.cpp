// Unit tests for components/garden_schedule/schedule_ui.h (host compiler, no ESPHome headers): the editor draft, the
// D08 row texts and the status words.
#include "minitest.h"

#include <string>

#include "garden_schedule/schedule_core.h"
#include "garden_schedule/schedule_format.h"
#include "garden_schedule/schedule_ui.h"
namespace gs = esphome::garden_schedule;

namespace {

bool ascii(const std::string &s) {
  for (char c : s) {
    if (c < 0x20 || c > 0x7E)
      return false;
  }
  return true;
}

/// Hand-written matcher of the zone text entity pattern ^(all|[1-9][0-9]?( [1-9][0-9]?)*)$
bool matches_zone_pattern(const std::string &t) {
  if (t == "all")
    return true;
  size_t i = 0;
  if (t.empty())
    return false;
  while (true) {
    if (i >= t.size() || t[i] < '1' || t[i] > '9')
      return false;
    i++;
    if (i < t.size() && t[i] >= '0' && t[i] <= '9')
      i++;
    if (i == t.size())
      return true;
    if (t[i] != ' ')
      return false;
    i++;
  }
}

gs::ScheduleDraft draft(unsigned hour, unsigned minute) {
  gs::ScheduleDraft d;
  d.index = 1;
  d.enabled = true;
  d.hour = static_cast<uint8_t>(hour);
  d.minute = static_cast<uint8_t>(minute);
  d.days_mask = gs::ALL_DAYS;
  d.zone_mask = 0x3;
  d.pct = 100;
  return d;
}

uint32_t five_min(size_t) { return 300; }

}  // namespace

TEST_CASE("draft_time_wrap") {
  gs::ScheduleDraft d = draft(23, 55);
  d.hour_up();
  CHECK(d.hour == 0);
  d.hour_down();
  CHECK(d.hour == 23);
  d.hour_down();
  CHECK(d.hour == 22);
  d.minute_up();
  CHECK(d.minute == 0);
  d.minute_down();
  CHECK(d.minute == 55);
  d.minute = 7;
  d.minute_up();
  CHECK(d.minute == 10);
  d.minute = 7;
  d.minute_down();
  CHECK(d.minute == 5);
  d.minute = 0;
  d.minute_down();
  CHECK(d.minute == 55);
  d.minute = 58;  // from Home Assistant
  d.minute_up();
  CHECK(d.minute == 0);
  d.minute = 5;
  d.minute_down();
  CHECK(d.minute == 0);
  CHECK(draft(7, 5).hour_text() == "07");
  CHECK(draft(7, 5).minute_text() == "05");
  CHECK(draft(18, 45).hour_text() == "18");
  CHECK(draft(18, 45).minute_text() == "45");
}

TEST_CASE("draft_days_zones_pct") {
  gs::ScheduleDraft d = draft(6, 0);
  d.days_mask = 0;
  d.toggle_day(0);
  d.toggle_day(6);
  CHECK(d.days_mask == 0x41);
  d.toggle_day(0);
  CHECK(d.days_mask == 0x40);
  d.toggle_day(7);  // not a day
  CHECK(d.days_mask == 0x40);
  d.zone_mask = 0;
  d.toggle_zone(0, 4);
  d.toggle_zone(3, 4);
  CHECK(d.zone_mask == 0x9u);
  d.toggle_zone(4, 4);  // beyond the zone count: ignored
  CHECK(d.zone_mask == 0x9u);
  d.zone_mask |= 1u << 7;  // bits the screen has no button for stay
  d.toggle_zone(0, 8);
  CHECK(d.zone_mask == ((1u << 7) | 0x8u));
  d.toggle_zone(7, 6);  // a zone past the 6 buttons is not reachable either
  CHECK(d.zone_mask == ((1u << 7) | 0x8u));
  d.pct = 100;
  d.pct_up();
  CHECK(d.pct == 110);
  d.pct = 200;
  d.pct_up();
  CHECK(d.pct == 200);
  d.pct = 20;
  d.pct_down();
  CHECK(d.pct == 10);
  d.pct_down();
  CHECK(d.pct == 10);
  d.pct = 100;
  CHECK(d.factor_text() == "x1.0");
  d.pct = 50;
  CHECK(d.factor_text() == "x0.5");
  d.pct = 200;
  CHECK(d.factor_text() == "x2.0");
  d.pct = 10;
  CHECK(d.factor_text() == "x0.1");
  d.pct = 150;
  CHECK(d.factor_text() == "x1.5");
  d.enabled = false;
  d.toggle_enabled();
  CHECK(d.enabled);
}

TEST_CASE("draft_zones_text") {
  gs::ScheduleDraft d = draft(6, 0);
  d.zone_mask = 0x7;
  CHECK(d.zones_text(3) == "all");
  d.zone_mask = 0x5;
  CHECK(d.zones_text(3) == "1 3");
  d.zone_mask = 0x1;
  CHECK(d.zones_text(1) == "all");
  d.zone_mask = 0xFF | (1u << 7);
  CHECK(d.zones_text(8) == "all");
  d.zone_mask = 0x3 | (1u << 20);  // bits past the zone count are not written
  CHECK(d.zones_text(8) == "1 2");
  d.zone_mask = 0;
  CHECK(d.zones_text(3).empty());
  for (size_t count = 1; count <= 12; count++) {
    for (uint32_t mask = 1; mask < (1u << count); mask += (count > 8 ? 37 : 1)) {
      d.zone_mask = mask;
      const std::string text = d.zones_text(count);
      CHECK(matches_zone_pattern(text));
      const auto parsed = gs::parse_zones(text, count);
      REQUIRE(parsed.has_value());
      CHECK(*parsed == mask);  // the round trip keeps the selection
    }
  }
  CHECK(matches_zone_pattern("1 3") && matches_zone_pattern("all") && matches_zone_pattern("12"));
  CHECK(!matches_zone_pattern("") && !matches_zone_pattern("1,3") && !matches_zone_pattern("0") && !matches_zone_pattern("1 "));
}

TEST_CASE("draft_can_save_and_diff") {
  gs::ScheduleDraft d = draft(6, 0);
  CHECK(d.can_save());
  d.days_mask = 0;
  CHECK(!d.can_save());  // enabled without a day
  d.days_mask = 0x1;
  d.zone_mask = 0;
  CHECK(!d.can_save());  // enabled without a zone
  d.enabled = false;
  CHECK(d.can_save());  // switching a slot off never needs days or zones
  d.days_mask = 0;
  CHECK(d.can_save());

  const gs::ScheduleDraft base = draft(6, 0);
  gs::ScheduleDraft e = base;
  gs::Diff none = e.diff(base);
  CHECK(!none.any());
  e.enabled = false;
  CHECK(e.diff(base).enabled && e.diff(base).any());
  CHECK(!e.diff(base).start && !e.diff(base).zones && !e.diff(base).pct && e.diff(base).days == 0);
  e = base;
  e.hour = 7;
  CHECK(e.diff(base).start && !e.diff(base).enabled);
  e = base;
  e.minute = 5;
  CHECK(e.diff(base).start);
  e = base;
  e.toggle_day(2);
  CHECK(e.diff(base).days == 0x04 && !e.diff(base).start);
  e.toggle_day(5);
  CHECK(e.diff(base).days == 0x24);
  e = base;
  e.toggle_zone(2, 3);
  CHECK(e.diff(base).zones && !e.diff(base).pct);
  e = base;
  e.pct_up();
  CHECK(e.diff(base).pct && !e.diff(base).zones);
  e.pct_down();
  CHECK(!e.diff(base).any());  // back to the original: nothing to write
}

TEST_CASE("list_texts") {
  CHECK(gs::row_time(true, 6 * 60) == "06:00");
  CHECK(gs::row_time(true, 18 * 60 + 5) == "18:05");
  CHECK(gs::row_time(false, 6 * 60) == "--:--");

  CHECK(gs::zones_label("Greenhouse", "bed", 0x7, 3) == "Greenhouse - all beds");
  CHECK(gs::zones_label("Greenhouse", "bed", 0x2, 3) == "Greenhouse - bed 2");
  CHECK(gs::zones_label("Greenhouse", "bed", 0x5, 3) == "Greenhouse - beds 1 3");
  CHECK(gs::zones_label("Greenhouse", "bed", 0x1, 1) == "Greenhouse - bed 1");  // the only bed
  CHECK(gs::zones_label("Greenhouse", "bed", 0xF, 6) == "Greenhouse - 4 beds");
  CHECK(gs::zones_label("Greenhouse", "bed", 0x7, 6) == "Greenhouse - beds 1 2 3");
  CHECK(gs::zones_label("Greenhouse", "bed", 0x0, 6) == "Greenhouse - no beds");
  CHECK(gs::zones_label("Greenhouse", "bed", 0x3F, 6) == "Greenhouse - all beds");

  CHECK(gs::duration_text(0x7, 3, five_min, 100) == "5 min each");
  CHECK(gs::duration_text(0x2, 3, five_min, 100) == "5 min");
  CHECK(gs::duration_text(0x7, 3, five_min, 200) == "10 min each");
  CHECK(gs::duration_text(0x1, 3, [](size_t) { return 90u; }, 50) == "45 s");
  auto mixed = [](size_t z) { return z == 0 ? 300u : z == 1 ? 420u : 480u; };
  CHECK(gs::duration_text(0x7, 3, mixed, 100) == "20 min total");
  CHECK(gs::duration_text(0x0, 3, five_min, 100).empty());

  CHECK(gs::row_caption(true, gs::ALL_DAYS, "5 min each") == "Every day - 5 min each");
  CHECK(gs::row_caption(true, 0x15, "20 min") == "Mon Wed Fri - 20 min");
  CHECK(gs::row_caption(true, 0x1F, "5 min each") == "Mon-Fri - 5 min each");
  CHECK(gs::row_caption(false, gs::ALL_DAYS, "5 min each") == "Not set - tap to set up");
  // a caption past CAPTION_MAX counts the days instead
  const std::string scattered = gs::row_caption(true, 0x5B, "1440 min total");
  CHECK(scattered == "5 days - 1440 min total");
  CHECK(gs::row_caption(true, 0x5B, "5 min each") == "5 days - 5 min each");
  CHECK(gs::row_caption(true, 0x5B, "20 s") == "Mon Tue Thu Fri Sun - 20 s");

  // worst cases stay ASCII and inside the label widths
  auto three_hours = [](size_t) { return 10800u; };
  for (uint32_t mask : {0xFFu, 0x55u, 0x81u, 0x1u}) {
    for (uint8_t days : {static_cast<uint8_t>(0x5B), static_cast<uint8_t>(0x7F), static_cast<uint8_t>(0x55), static_cast<uint8_t>(0x01)}) {
      const std::string cap = gs::row_caption(true, days, gs::duration_text(mask, 8, three_hours, 200));
      CHECK(ascii(cap));
      CHECK(cap.size() <= gs::CAPTION_MAX);
      const std::string label = gs::zones_label("Greenhouse", "bed", mask, 8);
      CHECK(ascii(label));
      CHECK(label.size() <= gs::LABEL_MAX);
    }
  }
}

TEST_CASE("status_words") {
  using gs::DayRunState;
  const auto w_off = gs::status_word(false, true, DayRunState::PENDING, false, true);
  CHECK(w_off.text == "OFF" && w_off.color == gs::TONE_DIM);
  const auto w_master = gs::status_word(true, false, DayRunState::FIRED, false, true);
  CHECK(w_master.text == "OFF" && w_master.color == gs::TONE_DIM);
  const auto w_done = gs::status_word(true, true, DayRunState::FIRED, false, false);
  CHECK(w_done.text == "DONE" && w_done.color == gs::TONE_DIM);
  const auto w_active = gs::status_word(true, true, DayRunState::FIRED, true, false);
  CHECK(w_active.text == "ACTIVE" && w_active.color == gs::TONE_GREEN);
  for (DayRunState s : {DayRunState::SKIPPED, DayRunState::MISSED, DayRunState::STOPPED}) {
    const auto w = gs::status_word(true, true, s, false, false);
    CHECK(w.text == "SKIP" && w.color == gs::TONE_AMBER);
  }
  const auto w_next = gs::status_word(true, true, DayRunState::PENDING, false, true);
  CHECK(w_next.text == "NEXT" && w_next.color == gs::TONE_GREEN);
  const auto w_none = gs::status_word(true, true, DayRunState::PENDING, false, false);
  CHECK(w_none.text.empty() && w_none.color == gs::TONE_DIM);
  // tones mirror design/tokens.json: text, text-dim, green, amber
  CHECK(gs::TONE_TEXT == 0xe5e2e1u && gs::TONE_DIM == 0xbecab9u && gs::TONE_GREEN == 0x78dc77u && gs::TONE_AMBER == 0xffb870u);
  for (const auto &w : {w_off, w_done, w_active, w_next, w_none})
    CHECK(ascii(w.text));
}
