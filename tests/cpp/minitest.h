// Minimal header-only test harness for the host-compiled C++ unit tests (no third-party dependency).
// Usage: TEST_CASE("name") { CHECK(expr); } ... ; int main() { return gz_test::run_all(); }
#pragma once

#include <cstdio>
#include <vector>

namespace gz_test {

struct Case {
  const char *name;
  void (*fn)();
};

inline std::vector<Case> &cases() {
  static std::vector<Case> list;
  return list;
}

inline int &failures() {
  static int count = 0;
  return count;
}

struct Registrar {
  Registrar(const char *name, void (*fn)()) { cases().push_back(Case{name, fn}); }
};

inline void report(bool ok, const char *expr, const char *file, int line) {
  if (!ok) {
    failures()++;
    std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", file, line, expr);
  }
}

inline int run_all() {
  for (const Case &c : cases()) {
    int before = failures();
    c.fn();
    std::printf("[%s] %s\n", failures() == before ? "ok" : "FAIL", c.name);
  }
  std::printf("%zu test cases, %d failed checks\n", cases().size(), failures());
  return failures() == 0 ? 0 : 1;
}

}  // namespace gz_test

#define GZ_CONCAT_(a, b) a##b
#define GZ_CONCAT(a, b) GZ_CONCAT_(a, b)
#define TEST_CASE(name)                                                                  \
  static void GZ_CONCAT(gz_case_, __LINE__)();                                           \
  static gz_test::Registrar GZ_CONCAT(gz_reg_, __LINE__)(name, GZ_CONCAT(gz_case_, __LINE__)); \
  static void GZ_CONCAT(gz_case_, __LINE__)()

#define CHECK(expr) gz_test::report(static_cast<bool>(expr), #expr, __FILE__, __LINE__)
#define CHECK_FALSE(expr) gz_test::report(!static_cast<bool>(expr), "!(" #expr ")", __FILE__, __LINE__)
// Stops the current test case when the condition does not hold.
#define REQUIRE(expr)                                                       \
  do {                                                                      \
    bool gz_ok_ = static_cast<bool>(expr);                                  \
    gz_test::report(gz_ok_, #expr, __FILE__, __LINE__);                     \
    if (!gz_ok_)                                                            \
      return;                                                               \
  } while (0)
