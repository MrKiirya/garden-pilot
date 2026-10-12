// gp — alert table (pure C++17, no ESPHome includes; unit tested on the host compiler).
// Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
//
// A small fixed table of active alerts: key, severity, ASCII text, "since" (uptime seconds) and the group index
// (or -1). `top()` is the highest severity, then the newest. When the table is full the lowest-severity oldest entry is
// dropped for a new one that is at least as severe; an ERROR is never dropped (the new alert is rejected and counted).
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace esphome::gp {

enum class Severity : uint8_t { INFO = 0, WARN = 1, ERROR = 2 };

inline constexpr size_t ALERT_CAPACITY = 12;
inline constexpr size_t ALERT_KEY_LEN = 15;
inline constexpr size_t ALERT_TEXT_LEN = 40;

struct Alert {
  char key[ALERT_KEY_LEN + 1];
  Severity severity;
  char text[ALERT_TEXT_LEN + 1];
  uint32_t since_s;
  int group;
  uint32_t order;  // newer = larger; used for sorting only
};

class AlertTable {
 public:
  /// Raises (or updates) the alert `key`. Returns true when something visible changed.
  bool raise(const char *key, Severity severity, const char *text, uint32_t now_s, int group = -1) {
    char k[ALERT_KEY_LEN + 1];
    char t[ALERT_TEXT_LEN + 1];
    sanitise_(k, sizeof(k), key);
    sanitise_(t, sizeof(t), text);
    Alert *existing = this->find_(k);
    if (existing != nullptr) {
      bool changed = false;
      if (existing->severity != severity) {
        existing->severity = severity;
        existing->order = ++this->counter_;
        changed = true;
      }
      if (std::strcmp(existing->text, t) != 0) {
        std::memcpy(existing->text, t, sizeof(t));
        changed = true;
      }
      if (changed)
        this->revision_++;
      return changed;
    }
    Alert *slot = nullptr;
    if (this->count_ < ALERT_CAPACITY) {
      slot = &this->items_[this->count_++];
    } else {
      // victim: lowest severity, then oldest; never an ERROR, never more severe than the new alert
      Alert *victim = nullptr;
      for (size_t i = 0; i < this->count_; i++) {
        Alert &a = this->items_[i];
        if (victim == nullptr || a.severity < victim->severity ||
            (a.severity == victim->severity && a.order < victim->order))
          victim = &a;
      }
      if (victim == nullptr || victim->severity == Severity::ERROR || victim->severity > severity) {
        this->overflow_++;
        return false;
      }
      slot = victim;
    }
    std::memcpy(slot->key, k, sizeof(k));
    std::memcpy(slot->text, t, sizeof(t));
    slot->severity = severity;
    slot->since_s = now_s;
    slot->group = group;
    slot->order = ++this->counter_;
    this->revision_++;
    return true;
  }

  /// Clears the alert `key`. Returns true when it existed.
  bool clear(const char *key) {
    char k[ALERT_KEY_LEN + 1];
    sanitise_(k, sizeof(k), key);
    Alert *a = this->find_(k);
    if (a == nullptr)
      return false;
    *a = this->items_[this->count_ - 1];
    this->count_--;
    this->revision_++;
    return true;
  }

  /// `key == nullptr`: any alert is active.
  bool active(const char *key) const {
    if (key == nullptr)
      return this->count_ > 0;
    char k[ALERT_KEY_LEN + 1];
    sanitise_(k, sizeof(k), key);
    return const_cast<AlertTable *>(this)->find_(k) != nullptr;
  }

  size_t count() const { return this->count_; }

  /// The i-th alert in display order (highest severity first, then newest). Out of range: the last/empty entry.
  const Alert &at(size_t index) const {
    static const Alert EMPTY = {"", Severity::INFO, "", 0, -1, 0};
    if (index >= this->count_)
      return EMPTY;
    // selection by rank: the alert with exactly `index` better-ranked alerts
    for (size_t i = 0; i < this->count_; i++) {
      size_t better = 0;
      for (size_t j = 0; j < this->count_; j++) {
        if (j != i && better_(this->items_[j], this->items_[i]))
          better++;
      }
      if (better == index)
        return this->items_[i];
    }
    return EMPTY;
  }

  const Alert *top() const { return this->count_ == 0 ? nullptr : &this->at(0); }

  uint32_t revision() const { return this->revision_; }
  uint32_t overflow_count() const { return this->overflow_; }

 protected:
  static bool better_(const Alert &a, const Alert &b) {
    if (a.severity != b.severity)
      return a.severity > b.severity;
    return a.order > b.order;
  }

  static void sanitise_(char *out, size_t size, const char *in) {
    size_t n = 0;
    if (in != nullptr) {
      for (; in[n] != '\0' && n + 1 < size; n++) {
        const unsigned char c = static_cast<unsigned char>(in[n]);
        out[n] = (c >= 0x20 && c <= 0x7e) ? static_cast<char>(c) : '?';
      }
    }
    out[n] = '\0';
  }

  Alert *find_(const char *sanitised_key) {
    for (size_t i = 0; i < this->count_; i++) {
      if (std::strcmp(this->items_[i].key, sanitised_key) == 0)
        return &this->items_[i];
    }
    return nullptr;
  }

  Alert items_[ALERT_CAPACITY]{};
  size_t count_{0};
  uint32_t counter_{0};
  uint32_t revision_{1};
  uint32_t overflow_{0};
};

}  // namespace esphome::gp
