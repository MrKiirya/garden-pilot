// Unit tests for the history entry life cycle (open at start, close at end), sources, skips and the History page texts
// (components/gp/{history,journal,zone_model,format_history}.h; host compiler, no ESPHome headers).
#include "minitest.h"

#include <cstring>
#include <string>

#include "gp/format_history.h"
#include "gp/history.h"
#include "gp/journal.h"
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
  // the result byte covers 0..6, anything else reads as UNKNOWN
  for (uint8_t r = 0; r <= 6; r++) {
    gp::HistoryEntry e{};
    e.result = r;
    CHECK(static_cast<uint8_t>(gp::result_of(e)) == r);
  }
  for (uint8_t r : {7, 8, 77, 255}) {
    gp::HistoryEntry e{};
    e.result = r;
    CHECK(gp::result_of(e) == gp::Result::UNKNOWN);
  }
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
  CHECK(newest.detail == 0);
  // an old entry renders like a finished one: its duration, source words as before
  const gp::fmt::HistoryCells old_cells = gp::fmt::history_cells(loaded.history.at(2), at(1, 1, 6, 0), {}, "Bed 1");
  CHECK(old_cells.text[3] == "5 min");
  CHECK(old_cells.text[4] == "queue");
  CHECK(old_cells.tone[3] == gp::fmt::Tone::TEXT);
  CHECK(gp::fmt::history_cells(newest, at(1, 1, 6, 0), {}, "Bed 3").text[4] == "test");
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

// ---------------------------------------------------------------------------------------------- run journal rig

namespace {

// model + journal + blob driven by a fake clock; `saves` counts the save requests the glue would make
struct Rig {
  gp::PersistBlob blob;
  gp::GroupModel model;
  gp::Journal journal{blob};
  gp::GroupInput in;
  uint32_t now_ms{1000};
  uint32_t epoch{1000000};
  uint32_t stop_ms{0};
  int saves{0};
  int finished{0};
  bool last_completed{false};
  gp::Result last_result{gp::Result::UNKNOWN};

  Rig() {
    in.zone_count = 4;
    for (size_t i = 0; i < 4; i++)
      in.zones[i].run_duration = 300;
  }
  void tick(uint32_t seconds) {
    now_ms += seconds * 1000U;
    if (epoch != 0)
      epoch += seconds;
    model.refresh(now_ms, epoch, in);
    const bool changed = journal.process(model, now_ms, stop_ms, [this](const gp::RunRecord &rec, gp::Result result) {
      if (!rec.is_skip()) {
        finished++;
        last_completed = rec.from_queue && result != gp::Result::STOPPED;
        last_result = result;
      }
    });
    if (changed)
      saves++;
  }
  void start(size_t zone, uint32_t planned, gp::Source source = gp::Source::MANUAL, uint8_t detail = 0,
             bool from_queue = false) {
    in.zones[zone].running = true;
    in.zones[zone].has_time_left = true;
    in.zones[zone].time_left = planned;
    in.start_source[zone] = source;
    in.start_detail[zone] = detail;
    in.start_from_queue[zone] = from_queue;
  }
  void end(size_t zone) {
    in.zones[zone].running = false;
    in.zones[zone].has_time_left = false;
  }
};

}  // namespace

TEST_CASE("book_open_then_close_done") {
  Rig r;
  r.tick(1);
  r.start(1, 300, gp::Source::SCHEDULE, 2);
  r.tick(1);
  REQUIRE(r.blob.history.size() == 1u);
  gp::HistoryEntry e = r.blob.history.at(0);
  CHECK(e.result == static_cast<uint8_t>(gp::Result::OPEN));
  CHECK(e.duration == 300u);  // planned
  CHECK(e.zone == 1);
  CHECK(e.source == static_cast<uint8_t>(gp::Source::SCHEDULE));
  CHECK(e.detail == 2);
  CHECK(e.epoch == r.epoch);
  const uint32_t start_epoch = e.epoch;
  CHECK(r.saves == 1);
  for (int i = 0; i < 299; i++)
    r.tick(1);
  CHECK(r.saves == 1);  // nothing is written while the zone runs
  CHECK(r.blob.history.size() == 1u);
  r.end(0 + 1);
  r.tick(1);
  REQUIRE(r.blob.history.size() == 1u);  // the SAME entry
  e = r.blob.history.at(0);
  CHECK(e.result == static_cast<uint8_t>(gp::Result::DONE));
  CHECK(e.duration >= 299u);
  CHECK(e.duration <= 301u);
  CHECK(e.epoch == start_epoch);
  CHECK(r.saves == 2);
  CHECK(r.finished == 1);
}

TEST_CASE("book_parallel_open") {
  Rig r;
  r.tick(1);
  r.start(0, 300);
  r.start(1, 300);
  r.tick(1);
  CHECK(r.blob.history.size() == 2u);
  // a skip of zone 2 lands between the open entries and the closes
  r.in.zones[2].has_skip = true;
  r.in.zones[2].skip_stamp = 5000;
  r.in.zones[2].skip_wet = true;
  r.in.zones[2].skip_limit = 60;
  r.in.zones[2].skip_text = "soil moisture 80.0 > 60.0";
  r.tick(10);
  CHECK(r.blob.history.size() == 3u);
  r.end(0);
  r.tick(1);
  REQUIRE(r.blob.history.size() == 3u);
  CHECK(gp::book::find_open(r.blob.history, 0) == -1);  // zone 0 was closed in its own entry
  CHECK(gp::book::find_open(r.blob.history, 1) >= 0);   // zone 1 is still open
  CHECK(r.blob.history.at(2).zone == 0);
  CHECK(r.blob.history.at(2).result == static_cast<uint8_t>(gp::Result::DONE));
  CHECK(r.blob.history.at(0).zone == 2);  // the skip is still the newest
}

TEST_CASE("book_stopped") {
  Rig r;
  r.tick(1);
  r.start(0, 300);
  r.tick(60);
  r.stop_ms = r.now_ms + 500;  // STOP pressed just before the end is seen
  r.end(0);
  r.tick(1);
  CHECK(r.blob.history.at(0).result == static_cast<uint8_t>(gp::Result::STOPPED));
  CHECK(!r.last_completed);
  // a run that ends long after the last STOP is done; a watchdog end is done, too
  r.start(1, 120);
  r.tick(10);
  r.end(1);
  r.tick(1);
  CHECK(r.blob.history.at(0).result == static_cast<uint8_t>(gp::Result::DONE));
  CHECK(gp::ended_by_stop(10000, 8000));
  CHECK(!gp::ended_by_stop(10000, 6999));
  CHECK(!gp::ended_by_stop(10000, 0));
  CHECK(gp::ended_by_stop(100, 4294967000u));  // wrapped millis
}

TEST_CASE("book_interrupted_after_boot") {
  gp::PersistBlob blob;
  gp::book::open(blob.history, 100, 300, 0, 1, 0);
  gp::book::open(blob.history, 200, 120, 1, 4, 3);
  gp::HistoryEntry done{300, 60, 2, 1, static_cast<uint8_t>(gp::Result::DONE), 0};
  blob.history.push(done);
  CHECK(gp::book::recover_after_boot(blob.history));
  CHECK(blob.history.at(1).result == static_cast<uint8_t>(gp::Result::INTERRUPTED));
  CHECK(blob.history.at(2).result == static_cast<uint8_t>(gp::Result::INTERRUPTED));
  CHECK(blob.history.at(1).duration == 120u);  // planned kept
  CHECK(blob.history.at(2).duration == 300u);
  CHECK(blob.history.at(0).result == static_cast<uint8_t>(gp::Result::DONE));
  CHECK(gp::book::find_open(blob.history, 0) == -1);
  CHECK(!gp::book::recover_after_boot(blob.history));  // nothing open: no save
  gp::Journal journal(blob);
  CHECK(!journal.recover_after_boot());
}

TEST_CASE("book_epoch_backfill") {
  Rig r;
  r.epoch = 0;  // the clock is not valid yet
  r.tick(1);
  r.start(0, 300);
  r.tick(1);
  CHECK(r.blob.history.at(0).epoch == 0u);
  r.tick(60);
  r.epoch = 5000000;  // the clock became valid while the zone runs
  r.tick(1);
  r.end(0);
  r.tick(1);
  const gp::HistoryEntry e = r.blob.history.at(0);
  CHECK(e.result == static_cast<uint8_t>(gp::Result::DONE));
  CHECK(e.epoch != 0u);
  CHECK(e.epoch == r.epoch - e.duration);
}

TEST_CASE("book_close_overwritten") {
  Rig r;
  r.tick(1);
  r.start(0, 300);
  r.tick(1);
  for (size_t i = 0; i < gp::HISTORY_LENGTH; i++)
    gp::book::open(r.blob.history, 1, 1, 3, 1, 0);  // 100 newer entries push the open one out
  CHECK(gp::book::find_open(r.blob.history, 0) == -1);
  r.tick(30);
  r.end(0);
  r.tick(1);
  CHECK(r.blob.history.size() == gp::HISTORY_LENGTH);
  const gp::HistoryEntry e = r.blob.history.at(0);
  CHECK(e.zone == 0);
  CHECK(e.result == static_cast<uint8_t>(gp::Result::DONE));
  CHECK(e.epoch != 0u);
}

TEST_CASE("tracker_elapsed_live") {
  gp::ZoneTracker t;
  gp::ZoneView v;
  gp::ZoneInput in;
  t.update(0, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(!v.run_elapsed.has_value());
  in.running = true;
  t.update(1000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.run_elapsed.value_or(99) == 0u);
  t.update(11000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.run_elapsed.value_or(0) == 10u);
  in.running = false;  // PAUSED gap: a manual run took the lane
  in.paused = true;
  t.update(21000, 0, 0, in, gp::Source::MANUAL, v);  // the valve was open until this sample
  CHECK(v.run_elapsed.value_or(0) == 20u);
  t.update(41000, 0, 0, in, gp::Source::MANUAL, v);  // 20 s paused: not counted
  CHECK(v.run_elapsed.value_or(0) == 20u);
  in.paused = false;
  in.running = true;
  t.update(42000, 0, 0, in, gp::Source::MANUAL, v);
  t.update(47000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(v.run_elapsed.value_or(0) == 25u);
  in.running = false;
  t.update(48000, 0, 0, in, gp::Source::MANUAL, v);
  CHECK(!v.run_elapsed.has_value());
}

TEST_CASE("pick_source_precedence") {
  using gp::Source;
  // intent > queued > cycle > queue > unknown
  CHECK(gp::pick_source(Source::MANUAL, true, Source::SCHEDULE, true, Source::HA, true) == Source::MANUAL);
  CHECK(gp::pick_source(Source::UNKNOWN, true, Source::SCHEDULE, true, Source::HA, true) == Source::SCHEDULE);
  CHECK(gp::pick_source(Source::UNKNOWN, false, Source::UNKNOWN, true, Source::HA, true) == Source::HA);
  CHECK(gp::pick_source(Source::UNKNOWN, false, Source::UNKNOWN, false, Source::HA, true) == Source::QUEUE);
  CHECK(gp::pick_source(Source::UNKNOWN, false, Source::UNKNOWN, false, Source::UNKNOWN, false) == Source::UNKNOWN);
  // an intent older than 15 s is ignored
  gp::SourcePlan plan;
  plan.note_intent(2, Source::MANUAL, 1000);
  CHECK(plan.resolve(2, 1000 + 14999, false, false).source == Source::MANUAL);
  CHECK(plan.resolve(2, 1000 + 15000, false, false).source == Source::UNKNOWN);
  CHECK(plan.resolve(2, 1000 + 15000, false, true).source == Source::QUEUE);
  // an intent beats a queued zone, but the run is then not from the queue
  plan.queue(2, Source::SCHEDULE, 4);
  const gp::StartInfo manual = plan.resolve(2, 2000, false, true);
  CHECK(manual.source == Source::MANUAL);
  CHECK(manual.detail == 0);
  CHECK(!manual.from_queue);
}

TEST_CASE("queued_source_lifecycle") {
  using gp::Source;
  gp::SourcePlan plan;
  plan.queue(1, Source::SCHEDULE, 2);
  plan.queue(2, Source::HA, 0);
  gp::StartInfo info = plan.resolve(1, 5000, false, true);
  CHECK(info.source == Source::SCHEDULE);
  CHECK(info.detail == 2);
  CHECK(info.from_queue);
  plan.consume(1);  // used up at the start
  info = plan.resolve(1, 5000, false, true);
  CHECK(info.source == Source::QUEUE);
  CHECK(info.detail == 0);
  plan.clear_queued(2);  // dequeue_zone
  CHECK(plan.resolve(2, 5000, false, false).source == Source::UNKNOWN);
  plan.queue(0, Source::SCHEDULE, 1);
  plan.queue(3, Source::HA, 0);
  plan.clear_all_queued();  // stop_all / clear_queue / service mode
  CHECK(plan.resolve(0, 5000, false, false).source == Source::UNKNOWN);
  CHECK(plan.resolve(3, 5000, false, false).source == Source::UNKNOWN);
  // the whole path: a scheduled queue run opens an entry with SCHEDULE and the slot
  Rig r;
  r.tick(1);
  r.start(1, 300, Source::SCHEDULE, 2, true);
  r.tick(1);
  CHECK(r.blob.history.at(0).source == static_cast<uint8_t>(Source::SCHEDULE));
  CHECK(r.blob.history.at(0).detail == 2);
}

TEST_CASE("completed_flag_kept") {
  Rig r;
  r.tick(1);
  // a scheduled queue run that ends by itself is completed
  r.start(0, 100, gp::Source::SCHEDULE, 1, true);
  r.tick(5);
  r.end(0);
  r.tick(1);
  CHECK(r.finished == 1);
  CHECK(r.last_completed);
  // a plain queue run too
  r.start(1, 100, gp::Source::QUEUE, 0, true);
  r.tick(5);
  r.end(1);
  r.tick(1);
  CHECK(r.last_completed);
  // a run_zone run is not
  r.start(2, 100, gp::Source::MANUAL, 0, false);
  r.tick(5);
  r.end(2);
  r.tick(1);
  CHECK(r.finished == 3);
  CHECK(!r.last_completed);
  // a stopped queue run is not
  r.start(3, 100, gp::Source::HA, 0, true);
  r.tick(5);
  r.stop_ms = r.now_ms;
  r.end(3);
  r.tick(1);
  CHECK(!r.last_completed);
  CHECK(r.last_result == gp::Result::STOPPED);
}

TEST_CASE("skip_entry_source_and_limit") {
  Rig r;
  r.tick(1);
  r.in.start_source[1] = gp::Source::SCHEDULE;
  r.in.zones[1].has_skip = true;
  r.in.zones[1].skip_stamp = 3000;
  r.in.zones[1].skip_wet = true;
  r.in.zones[1].skip_limit = 60;
  r.in.zones[1].skip_text = "soil moisture 72.0 > 60.0";
  r.tick(1);
  gp::HistoryEntry e = r.blob.history.at(0);
  CHECK(e.result == static_cast<uint8_t>(gp::Result::SKIPPED_WET));
  CHECK(e.source == static_cast<uint8_t>(gp::Source::SCHEDULE));
  CHECK(e.detail == 60);
  CHECK(e.duration == 0u);
  // the threshold could not be read
  r.in.zones[2].has_skip = true;
  r.in.zones[2].skip_stamp = 4000;
  r.in.zones[2].skip_wet = true;
  r.in.zones[2].skip_text = "soil moisture 72.0 > ?";
  r.tick(1);
  e = r.blob.history.at(0);
  CHECK(e.detail == 255);
  CHECK(gp::fmt::history_cells(e, at(1, 1, 6, 0), {}, "Bed 3").text[4] == "too wet");
}

// ---------------------------------------------------------------------------------------------- texts

TEST_CASE("fmt_history_cells") {
  using gp::fmt::Tone;
  const gp::fmt::LocalTime when = at(16, 10, 6, 0);
  const auto done = gp::fmt::history_cells(entry(1, 300, 0, gp::Source::SCHEDULE, gp::Result::DONE), when, {}, "Bed 1");
  CHECK(done.text[0] == "16.10");
  CHECK(done.text[1] == "06:00");
  CHECK(done.text[2] == "Bed 1");
  CHECK(done.text[3] == "5 min");
  CHECK(done.text[4] == "schedule");
  CHECK(done.tone[0] == Tone::DIM);
  CHECK(done.tone[1] == Tone::TEXT);
  CHECK(done.tone[2] == Tone::TEXT);
  CHECK(done.tone[3] == Tone::TEXT);
  CHECK(done.tone[4] == Tone::DIM);
  // below one minute, and the 5 s tolerance of the sampling
  CHECK(gp::fmt::history_cells(entry(1, 45, 0, gp::Source::MANUAL, gp::Result::DONE), when, {}, "Bed 1").text[3] == "45 s");
  CHECK(gp::fmt::history_cells(entry(1, 299, 0, gp::Source::MANUAL, gp::Result::DONE), when, {}, "Bed 1").text[3] == "5 min");
  CHECK(gp::fmt::duration_text(59) == "59 s");
  CHECK(gp::fmt::duration_text(60) == "1 min");
  CHECK(gp::fmt::duration_text(124) == "2 min");
  CHECK(gp::fmt::duration_text(114) == "1 min");
  CHECK(gp::fmt::duration_text(179) == "3 min");
  // open and live
  const auto live = gp::fmt::history_cells(entry(1, 300, 1, gp::Source::MANUAL, gp::Result::OPEN), when, 240u, "Bed 2");
  CHECK(live.text[3] == "4 min...");
  CHECK(live.text[4] == "manual");
  CHECK(live.tone[0] == Tone::DIM);
  CHECK(live.tone[1] == Tone::GREEN);
  CHECK(live.tone[2] == Tone::GREEN);
  CHECK(live.tone[3] == Tone::GREEN);
  CHECK(live.tone[4] == Tone::DIM);
  CHECK(gp::fmt::history_cells(entry(1, 300, 1, gp::Source::MANUAL, gp::Result::OPEN), when, 45u, "Bed 2").text[3] == "45 s...");
  // an open entry whose zone is not live: like done, with the planned time
  const auto stale = gp::fmt::history_cells(entry(1, 300, 1, gp::Source::MANUAL, gp::Result::OPEN), when, {}, "Bed 2");
  CHECK(stale.text[3] == "5 min");
  CHECK(stale.tone[1] == Tone::TEXT);
  // stopped
  const auto stopped = gp::fmt::history_cells(entry(1, 120, 0, gp::Source::HA, gp::Result::STOPPED), when, {}, "Bed 1");
  CHECK(stopped.text[3] == "2 min");
  CHECK(stopped.text[4] == "HA");
  CHECK(stopped.tone[3] == Tone::AMBER);
  CHECK(stopped.tone[1] == Tone::TEXT);
  CHECK(stopped.tone[4] == Tone::DIM);
  // interrupted
  const auto cut = gp::fmt::history_cells(entry(1, 300, 0, gp::Source::QUEUE, gp::Result::INTERRUPTED), when, {}, "Bed 1");
  CHECK(cut.text[3] == "<5 min");
  CHECK(cut.tone[3] == Tone::AMBER);
  CHECK(gp::fmt::history_cells(entry(1, 0, 0, gp::Source::QUEUE, gp::Result::INTERRUPTED), when, {}, "Bed 1").text[3] == "?");
  CHECK(gp::fmt::history_cells(entry(1, 40, 0, gp::Source::QUEUE, gp::Result::INTERRUPTED), when, {}, "Bed 1").text[3] == "<40 s");
  // skips
  gp::HistoryEntry wet = entry(1, 0, 2, gp::Source::SCHEDULE, gp::Result::SKIPPED_WET);
  wet.detail = 60;
  const auto skip = gp::fmt::history_cells(wet, when, {}, "Bed 3");
  CHECK(skip.text[3] == "skipped");
  CHECK(skip.text[4] == "soil > 60%");
  for (size_t c = 0; c < gp::fmt::HISTORY_COLS; c++)
    CHECK(skip.tone[c] == Tone::DIM);
  wet.detail = 255;
  CHECK(gp::fmt::history_cells(wet, when, {}, "Bed 3").text[4] == "too wet");
  const auto nosensor = gp::fmt::history_cells(entry(1, 0, 2, gp::Source::SCHEDULE, gp::Result::SKIPPED), when, {}, "Bed 3");
  CHECK(nosensor.text[3] == "skipped");
  CHECK(nosensor.text[4] == "no sensor");
  // clock never valid
  const auto none = gp::fmt::history_cells(entry(0, 300, 0, gp::Source::QUEUE, gp::Result::DONE), when, {}, "Bed 1");
  CHECK(none.text[0] == "--.--");
  CHECK(none.text[1] == "--:--");
  CHECK(gp::fmt::history_cells(entry(1, 300, 0, gp::Source::QUEUE, gp::Result::DONE), gp::fmt::LocalTime{}, {}, "Bed 1").text[1] == "--:--");
  // names and source words
  CHECK(gp::fmt::history_cells(entry(1, 300, 4, gp::Source::QUEUE, gp::Result::DONE), when, {}, "").text[2] == "B5");
  CHECK(gp::fmt::history_cells(entry(1, 300, 4, gp::Source::QUEUE, gp::Result::DONE), when, {}, nullptr).text[2] == "B5");
  CHECK(std::string(gp::fmt::history_source_word(static_cast<uint8_t>(gp::Source::UNKNOWN))) == "-");
  CHECK(std::string(gp::fmt::history_source_word(static_cast<uint8_t>(gp::Source::SERVICE))) == "test");
  CHECK(std::string(gp::fmt::history_source_word(static_cast<uint8_t>(gp::Source::HA))) == "HA");
  CHECK(std::string(gp::fmt::history_source_word(77)) == "-");
  // every cell is ASCII and fits its column (date 5, time 5, TIME ON 8, SOURCE 11 characters)
  const gp::Result results[] = {gp::Result::UNKNOWN, gp::Result::DONE,    gp::Result::STOPPED,     gp::Result::SKIPPED_WET,
                                gp::Result::SKIPPED, gp::Result::OPEN,    gp::Result::INTERRUPTED};
  for (gp::Result result : results) {
    for (uint8_t source = 0; source <= 5; source++) {
      for (uint8_t detail : {0, 60, 100, 255}) {
        gp::HistoryEntry e = entry(1, 99999, 15, static_cast<gp::Source>(source), result);
        e.detail = detail;
        for (std::optional<uint32_t> live : {std::optional<uint32_t>{}, std::optional<uint32_t>{99999u}}) {
          const auto cells = gp::fmt::history_cells(e, at(28, 12, 23, 59), live, "Bed 12");
          for (size_t c = 0; c < gp::fmt::HISTORY_COLS; c++)
            CHECK(printable_ascii(cells.text[c]));
          CHECK(cells.text[0].size() <= 5u);
          CHECK(cells.text[1].size() <= 5u);
          CHECK(cells.text[3].size() <= 9u);
          CHECK(cells.text[4].size() <= 11u);
        }
      }
    }
  }
}

TEST_CASE("fmt_history_zone_label") {
  CHECK(gp::fmt::history_zone_label("Bed 2", 1) == "Bed 2");
  CHECK(gp::fmt::history_zone_label("Greenhouse bed 1", 0) == "Bed 1");
  CHECK(gp::fmt::history_zone_label("Front flower border", 3) == "Border");
  CHECK(gp::fmt::history_zone_label("Lawn", 4) == "Lawn");
  CHECK(gp::fmt::history_zone_label("Tomatoes and peppers", 5) == "Peppers");  // the tail fits
  CHECK(gp::fmt::history_zone_label("Verylongname", 6) == "B7");
  CHECK(gp::fmt::history_zone_label("", 7) == "B8");
  CHECK(gp::fmt::history_zone_label(nullptr, 8) == "B9");
}

TEST_CASE("fmt_history_title") {
  CHECK(gp::fmt::history_title(100, 0) == "History - 1/13");
  CHECK(gp::fmt::history_title(100, 12) == "History - 13/13");
  CHECK(gp::fmt::history_title(100, 99) == "History - 13/13");  // clamped
  CHECK(gp::fmt::history_title(100, -1) == "History - 1/13");
  CHECK(gp::fmt::history_title(8, 0) == "History - 1/1");
  CHECK(gp::fmt::history_title(9, 1) == "History - 2/2");
  CHECK(gp::fmt::history_title(0, 0) == "History");
  CHECK(gp::fmt::history_page_count(0) == 1u);
  CHECK(gp::fmt::history_page_count(8) == 1u);
  CHECK(gp::fmt::history_page_count(9) == 2u);
  CHECK(gp::fmt::history_page_count(100) == 13u);
  CHECK(gp::fmt::history_clamp_page(100, 13) == 12);
  CHECK(gp::fmt::history_clamp_page(0, 3) == 0);
  CHECK(gp::fmt::history_clamp_page(10, -4) == 0);
}

TEST_CASE("skip_limit_parsing") {
  CHECK(gp::parse_skip_limit("soil moisture 72.0 > 60.0") == 60);
  CHECK(gp::parse_skip_limit("soil moisture 72.0 > 59.6") == 60);
  CHECK(gp::parse_skip_limit("soil moisture 99.0 > 100.0") == 100);
  CHECK(gp::parse_skip_limit("soil moisture 99.0 > 250") == 100);
  CHECK(gp::parse_skip_limit("soil sensor unavailable") == 255);
  CHECK(gp::parse_skip_limit("soil moisture 72.0 > ?") == 255);
  CHECK(gp::parse_skip_limit("") == 255);
  CHECK(gp::parse_skip_limit(nullptr) == 255);
}
