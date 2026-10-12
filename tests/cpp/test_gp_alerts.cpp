// Unit tests for components/gp/alerts.h (host compiler, no ESPHome headers).
#include "minitest.h"

#include <cstring>
#include <string>

#include "gp/alerts.h"
namespace gp = esphome::gp;

TEST_CASE("alerts_raise_clear_idempotent") {
  gp::AlertTable t;
  CHECK(t.count() == 0);
  CHECK(t.top() == nullptr);
  const uint32_t rev0 = t.revision();
  CHECK(t.raise("a", gp::Severity::WARN, "text one", 10));
  CHECK(t.count() == 1);
  CHECK(t.revision() != rev0);
  const uint32_t rev1 = t.revision();
  // same key, same content: idempotent, no revision bump
  CHECK(!t.raise("a", gp::Severity::WARN, "text one", 20));
  CHECK(t.count() == 1);
  CHECK(t.revision() == rev1);
  // a text change bumps the revision but keeps one entry and the first "since"
  CHECK(t.raise("a", gp::Severity::WARN, "text two", 30));
  CHECK(t.count() == 1);
  CHECK(t.revision() != rev1);
  CHECK(std::strcmp(t.at(0).text, "text two") == 0);
  CHECK(t.at(0).since_s == 10u);
  CHECK(t.active("a"));
  CHECK(!t.active("b"));
  CHECK(t.active(nullptr));  // any alert
  const uint32_t rev2 = t.revision();
  CHECK(t.clear("a"));
  CHECK(t.count() == 0);
  CHECK(t.revision() != rev2);
  CHECK(!t.clear("a"));  // idempotent
  CHECK(!t.active(nullptr));
}

TEST_CASE("alerts_top_order") {
  gp::AlertTable t;
  t.raise("w1", gp::Severity::WARN, "warn old", 1);
  t.raise("i1", gp::Severity::INFO, "info", 2);
  t.raise("w2", gp::Severity::WARN, "warn new", 3);
  REQUIRE(t.top() != nullptr);
  CHECK(std::strcmp(t.top()->key, "w2") == 0);  // highest severity, then newest
  t.raise("e1", gp::Severity::ERROR, "error", 4);
  CHECK(std::strcmp(t.top()->key, "e1") == 0);
  CHECK(std::strcmp(t.at(0).key, "e1") == 0);
  CHECK(std::strcmp(t.at(1).key, "w2") == 0);
  CHECK(std::strcmp(t.at(2).key, "w1") == 0);
  CHECK(std::strcmp(t.at(3).key, "i1") == 0);
  // same key, severity change: still one entry, top follows
  t.raise("i1", gp::Severity::ERROR, "info is an error now", 5);
  CHECK(t.count() == 4);
  CHECK(std::strcmp(t.top()->key, "i1") == 0);  // newer than e1? the raise bumped its order
  t.clear("i1");
  t.clear("e1");
  CHECK(std::strcmp(t.top()->key, "w2") == 0);
}

TEST_CASE("alerts_capacity") {
  gp::AlertTable t;
  char key[8];
  for (int i = 0; i < 12; i++) {
    std::snprintf(key, sizeof(key), "i%d", i);
    CHECK(t.raise(key, gp::Severity::INFO, "info", i));
  }
  CHECK(t.count() == 12);
  // a WARN pushes out the oldest INFO
  CHECK(t.raise("w", gp::Severity::WARN, "warn", 100));
  CHECK(t.count() == 12);
  CHECK(!t.active("i0"));
  CHECK(t.active("i1"));
  // ERRORs push out INFOs, then WARN, never an ERROR
  for (int i = 0; i < 12; i++) {
    std::snprintf(key, sizeof(key), "e%d", i);
    CHECK(t.raise(key, gp::Severity::ERROR, "error", 200 + i));
  }
  CHECK(t.count() == 12);
  CHECK(!t.active("w"));
  for (int i = 0; i < 12; i++) {
    std::snprintf(key, sizeof(key), "e%d", i);
    CHECK(t.active(key));
  }
  // a full table of errors: nothing is dropped, the new one is rejected and the overflow counted
  CHECK(!t.raise("late", gp::Severity::ERROR, "error", 300));
  CHECK(!t.active("late"));
  CHECK(t.count() == 12);
  CHECK(t.overflow_count() == 1);
  CHECK(!t.raise("info", gp::Severity::INFO, "info", 301));
  CHECK(t.overflow_count() == 2);
}

TEST_CASE("alerts_text_sanitising") {
  gp::AlertTable t;
  const std::string long_text(80, 'x');
  t.raise("a-very-long-key-over-15-chars", gp::Severity::WARN, long_text.c_str(), 1);
  REQUIRE(t.count() == 1);
  CHECK(std::strlen(t.at(0).text) == 40);
  CHECK(std::strlen(t.at(0).key) == 15);
  t.raise("u", gp::Severity::INFO, "caf\xc3\xa9 \xe2\x80\x93 ok\n", 2);
  for (size_t i = 0; i < t.count(); i++) {
    if (std::strcmp(t.at(i).key, "u") == 0) {
      CHECK(std::strcmp(t.at(i).text, "caf?? ??? ok?") == 0);
    }
  }
  // the key lookup uses the truncated key too
  CHECK(t.clear("a-very-long-key-over-15-chars"));
}

