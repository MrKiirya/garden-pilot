// Unit tests for the history result byte, skip entries and the History page texts
// (components/gp/{history,zone_model,format_history}.h; host compiler, no ESPHome headers).
#include "minitest.h"

#include <cstring>
#include <string>

#include "gp/format_history.h"
#include "gp/history.h"
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

// The layout of an entry as the previous firmware wrote it (the last field was an unused uint16_t, always zero).
struct OldEntry {
  uint32_t epoch;
  uint32_t duration;
  uint8_t zone;
  uint8_t source;
  uint16_t reserved;
};

gp::fmt::LocalTime at(uint8_t day, uint8_t month, uint8_t hour, uint8_t minute) {
  return gp::fmt::LocalTime{true, day, month, hour, minute};
}

gp::HistoryEntry entry(uint32_t epoch, uint32_t duration, uint8_t zone, gp::Source source, gp::Result result) {
  return gp::HistoryEntry{epoch, duration, zone, static_cast<uint8_t>(source), static_cast<uint8_t>(result), 0};
}

}  // namespace

TEST_CASE("history_layout_unchanged") {
  // These numbers were computed from the layout before the result byte existed: 4 magic + (100 * 12 + 2 + 2) history
  // + 16 * 8 last runs. Changing them would make every device drop its history on upgrade.
  CHECK(sizeof(gp::HistoryEntry) == 12u);
  CHECK(sizeof(OldEntry) == sizeof(gp::HistoryEntry));
  CHECK(sizeof(gp::PersistBlob) == 1336u);
  CHECK(gp::PersistBlob::MAGIC == 0x47503031u);
  gp::PersistBlob fresh;
  CHECK(fresh.magic == 0x47503031u);
  CHECK(fresh.valid());
}

TEST_CASE("old_blob_still_loads") {
  // Build a blob the way the previous firmware stored it: same struct, entries with the old layout (reserved == 0).
  gp::PersistBlob blob;
  OldEntry old_entries[3] = {{1000, 300, 0, 2, 0}, {2000, 45, 1, 1, 0}, {3000, 300, 2, 3, 0}};
  for (const OldEntry &o : old_entries) {
    gp::HistoryEntry e{};
    static_assert(sizeof(e) == sizeof(o), "same size");
    std::memcpy(&e, &o, sizeof(e));
    blob.history.push(e);
  }
  gp::PersistBlob loaded;
  std::memcpy(&loaded, &blob, sizeof(blob));  // what the preference layer stores and returns
  CHECK(loaded.valid());
  CHECK(loaded.history.size() == 3u);
  const gp::HistoryEntry newest = loaded.history.at(0);
  CHECK(newest.epoch == 3000u);
  CHECK(newest.zone == 2);
  CHECK(newest.result == 0);  // a zero byte reads as UNKNOWN
  CHECK(gp::result_of(newest) == gp::Result::UNKNOWN);
  CHECK(std::strcmp(gp::fmt::result_word(newest), "test") == 0);  // source 3 = service
  CHECK(std::strcmp(gp::fmt::result_word(loaded.history.at(1)), "-") == 0);
  CHECK(gp::fmt::history_row(loaded.history.at(2), at(1, 1, 6, 0)) == "B1  1 Jan 06:00  5 min  -");
}

TEST_CASE("history_result_words") {
  CHECK(std::strcmp(gp::fmt::result_word(entry(1, 1, 0, gp::Source::QUEUE, gp::Result::DONE)), "done") == 0);
  CHECK(std::strcmp(gp::fmt::result_word(entry(1, 1, 0, gp::Source::MANUAL, gp::Result::STOPPED)), "stopped") == 0);
  CHECK(std::strcmp(gp::fmt::result_word(entry(1, 0, 0, gp::Source::UNKNOWN, gp::Result::SKIPPED_WET)), "skipped wet") == 0);
  CHECK(std::strcmp(gp::fmt::result_word(entry(1, 0, 0, gp::Source::UNKNOWN, gp::Result::SKIPPED)), "skipped") == 0);
  CHECK(std::strcmp(gp::fmt::result_word(entry(1, 1, 0, gp::Source::QUEUE, gp::Result::UNKNOWN)), "-") == 0);
  // a byte outside the enum reads as unknown, a service run is always "test"
  gp::HistoryEntry odd = entry(1, 1, 0, gp::Source::QUEUE, gp::Result::DONE);
  odd.result = 77;
  CHECK(gp::result_of(odd) == gp::Result::UNKNOWN);
  CHECK(std::strcmp(gp::fmt::result_word(entry(1, 8, 0, gp::Source::SERVICE, gp::Result::DONE)), "test") == 0);
}

TEST_CASE("tracker_records_skip_once") {
  gp::ZoneTracker t;
  gp::ZoneView v;
  gp::RunRecord rec;
  gp::ZoneInput in;
  in.run_duration = 300;
  t.update(1000, 5000, 1, in, gp::Source::QUEUE, v);
  CHECK(!t.take_completed(rec));
  // a skip with skip_wet -> one record
  in.has_skip = true;
  in.skip_stamp = 2000;
  in.skip_text = "soil moisture 72.0 > 60.0";
  in.skip_wet = true;
  t.update(2100, 6000, 1, in, gp::Source::QUEUE, v);
  REQUIRE(t.take_completed(rec));
  CHECK(rec.zone == 1);
  CHECK(rec.duration == 0u);
  CHECK(rec.epoch == 6000u);
  CHECK(rec.result == gp::Result::SKIPPED_WET);
  CHECK(rec.is_skip());
  CHECK(!t.take_completed(rec));
  // the same stamp again: nothing
  t.update(3100, 7000, 1, in, gp::Source::QUEUE, v);
  CHECK(!t.take_completed(rec));
  // a new stamp: a second record
  in.skip_stamp = 9000;
  t.update(9100, 8000, 1, in, gp::Source::QUEUE, v);
  REQUIRE(t.take_completed(rec));
  CHECK(rec.epoch == 8000u);
  CHECK(!t.take_completed(rec));
  // not wet: a plain skip
  in.skip_stamp = 9500;
  in.skip_wet = false;
  in.skip_text = "soil sensor unavailable";
  t.update(9600, 9000, 1, in, gp::Source::QUEUE, v);
  REQUIRE(t.take_completed(rec));
  CHECK(rec.result == gp::Result::SKIPPED);
  CHECK(!t.take_completed(rec));
}

TEST_CASE("skip_and_run_records_come_in_order") {
  gp::GroupModel m;
  gp::GroupInput g;
  g.zone_count = 2;
  g.zones[0].run_duration = 300;
  g.zones[1].run_duration = 300;
  g.start_source[0] = gp::Source::QUEUE;
  g.start_source[1] = gp::Source::QUEUE;
  m.refresh(1000, 100, g);
  g.zones[0].running = true;
  m.refresh(2000, 200, g);
  g.zones[0].running = false;
  g.zones[1].has_skip = true;
  g.zones[1].skip_stamp = 3000;
  g.zones[1].skip_wet = true;
  g.zones[1].skip_text = "soil moisture 80.0 > 60.0";
  m.refresh(3100, 300, g);
  gp::RunRecord rec;
  REQUIRE(m.take_completed(rec));
  CHECK(rec.zone == 0);
  CHECK(rec.result == gp::Result::DONE);  // the glue turns it into STOPPED inside a stop window
  REQUIRE(m.take_completed(rec));
  CHECK(rec.zone == 1);
  CHECK(rec.is_skip());
  CHECK(!m.take_completed(rec));
}

TEST_CASE("history_row_texts") {
  const gp::HistoryEntry done = entry(1, 300, 1, gp::Source::QUEUE, gp::Result::DONE);
  CHECK(gp::fmt::history_row(done, at(13, 10, 6, 0)) == "B2  13 Oct 06:00  5 min  done");
  CHECK(gp::fmt::history_row(entry(1, 45, 0, gp::Source::MANUAL, gp::Result::STOPPED), at(2, 3, 18, 7)) ==
        "B1  2 Mar 18:07  45 s  stopped");
  CHECK(gp::fmt::history_row(entry(1, 0, 2, gp::Source::UNKNOWN, gp::Result::SKIPPED_WET), at(13, 10, 6, 0)) ==
        "B3  13 Oct 06:00  skipped wet");
  CHECK(gp::fmt::history_row(entry(1, 0, 2, gp::Source::UNKNOWN, gp::Result::SKIPPED), at(31, 12, 23, 59)) ==
        "B3  31 Dec 23:59  skipped");
  // clock never valid: epoch 0, or a time that did not convert
  CHECK(gp::fmt::history_row(entry(0, 300, 0, gp::Source::QUEUE, gp::Result::DONE), at(13, 10, 6, 0)) ==
        "B1  --:--  5 min  done");
  CHECK(gp::fmt::history_row(done, gp::fmt::LocalTime{}) == "B2  --:--  5 min  done");
  // the longest realistic row stays far below the label limit and is ASCII
  const std::string longest =
      gp::fmt::history_row(entry(1, 99999, 15, gp::Source::SERVICE, gp::Result::SKIPPED_WET), at(28, 9, 12, 30));
  CHECK(longest.size() < gp::fmt::LABEL_MAX);
  CHECK(printable_ascii(longest));
  CHECK(gp::fmt::duration_text(59) == "59 s");
  CHECK(gp::fmt::duration_text(60) == "1 min");
  CHECK(gp::fmt::duration_text(89) == "1 min");
  CHECK(gp::fmt::duration_text(90) == "2 min");
}

TEST_CASE("history_pager") {
  CHECK(gp::fmt::history_pager(37, 0) == "1-6 of 37");
  CHECK(gp::fmt::history_pager(37, 1) == "7-12 of 37");
  CHECK(gp::fmt::history_pager(37, 6) == "37-37 of 37");
  CHECK(gp::fmt::history_pager(37, 99) == "37-37 of 37");  // clamped
  CHECK(gp::fmt::history_pager(37, -1) == "1-6 of 37");
  CHECK(gp::fmt::history_pager(6, 0) == "1-6 of 6");
  CHECK(gp::fmt::history_pager(7, 1) == "7-7 of 7");
  CHECK(gp::fmt::history_pager(0, 0) == "No watering yet");
  CHECK(gp::fmt::history_page_count(0) == 1u);
  CHECK(gp::fmt::history_page_count(6) == 1u);
  CHECK(gp::fmt::history_page_count(7) == 2u);
  CHECK(gp::fmt::history_page_count(100) == 17u);
  CHECK(gp::fmt::history_clamp_page(100, 17) == 16);
  CHECK(gp::fmt::history_clamp_page(0, 3) == 0);
  CHECK(gp::fmt::history_clamp_page(10, -4) == 0);
}
