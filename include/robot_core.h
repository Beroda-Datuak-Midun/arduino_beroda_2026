#pragma once
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "robot_config.h"

namespace robot {
inline float clamp(float v, float low, float high) {
  return v < low ? low : (v > high ? high : v);
}

class LineReader {
 public:
  char line[96] = {};
  bool invalid = false;
  bool push(char ch) {
    if (ch == '\n') {
      line[length_] = '\0'; invalid = dropping_;
      length_ = 0; dropping_ = false; return true;
    }
    if (ch == '\r') return false;
    if (dropping_) return false;
    if (ch < 32 || ch > 126 || length_ >= sizeof(line) - 1) dropping_ = true;
    else line[length_++] = ch;
    return false;
  }
 private:
  uint8_t length_ = 0;
  bool dropping_ = false;
};

enum class Kind { Stop, Move, Service, Exit, Pwm, Rpm, Zero, Set, Arm };
struct Command {
  Kind kind = Kind::Stop;
  int motor = 0;
  float value[5] = {};
};
inline bool number(const char* text, float& result) {
  if (!text || !*text) return false;
  char* end = nullptr;
  result = static_cast<float>(strtod(text, &end));
  return end != text && *end == '\0' && isfinite(result);
}
inline bool parse(char* line, Command& cmd) {
  char* tokens[8]; uint8_t count = 0; char* save = nullptr;
  for (char* p = strtok_r(line, " \t", &save); p; p = strtok_r(nullptr, " \t", &save)) {
    if (count == 8) return false;
    tokens[count++] = p;
  }
  if (!count) return false;
  if (count == 1) {
    const char* names[] = {"STOP", "SERVICE", "EXIT", "ZERO", "ARM"};
    const Kind kinds[] = {Kind::Stop, Kind::Service, Kind::Exit, Kind::Zero, Kind::Arm};
    for (uint8_t i = 0; i < 5; ++i)
      if (!strcmp(tokens[0], names[i])) { cmd.kind = kinds[i]; return true; }
    return false;
  }
  if (!strcmp(tokens[0], "MOVE") && count == 4) {
    cmd.kind = Kind::Move;
    for (uint8_t i = 0; i < 3; ++i)
      if (!number(tokens[i + 1], cmd.value[i]) || fabsf(cmd.value[i]) > 1) return false;
    return true;
  }
  if (count != 3 && count != 7) return false;
  if (!strcmp(tokens[0], "PWM") && count == 3) cmd.kind = Kind::Pwm;
  else if (!strcmp(tokens[0], "RPM") && count == 3) cmd.kind = Kind::Rpm;
  else if (!strcmp(tokens[0], "SET") && count == 7) cmd.kind = Kind::Set;
  else return false;
  float motor;
  if (!number(tokens[1], motor) || motor < 1 || motor > 3 || floorf(motor) != motor)
    return false;
  cmd.motor = static_cast<int>(motor) - 1;
  for (uint8_t i = 2; i < count; ++i)
    if (!number(tokens[i], cmd.value[i - 2])) return false;
  return cmd.kind != Kind::Pwm ||
         (fabsf(cmd.value[0]) <= config::ServicePwmLimit && floorf(cmd.value[0]) == cmd.value[0]);
}
inline bool valid(const config::Calibration& c) {
  return isfinite(c.cpr) && c.cpr >= 1 && c.cpr <= 10000000 &&
         isfinite(c.maxRpm) && c.maxRpm > 0 && c.maxRpm <= 10000 &&
         isfinite(c.kp) && c.kp > 0 && c.kp <= 1000 &&
         isfinite(c.ki) && c.ki >= 0 && c.ki <= 1000 &&
         isfinite(c.kd) && c.kd >= 0 && c.kd <= 1000;
}
inline void mix(float vx, float vy, float wz, const config::Calibration* cal, float* targets) {
  float scale = 1;
  for (uint8_t i = 0; i < 3; ++i) {
    const float angle = config::WheelAngles[i] * 0.017453292519943f;
    targets[i] = -sinf(angle) * vx + cosf(angle) * vy + wz;
    if (fabsf(targets[i]) < 0.000001f) targets[i] = 0;
    if (fabsf(targets[i]) > scale) scale = fabsf(targets[i]);
  }
  float limit = cal[0].maxRpm;
  for (uint8_t i = 1; i < 3; ++i) if (cal[i].maxRpm < limit) limit = cal[i].maxRpm;
  for (uint8_t i = 0; i < 3; ++i) targets[i] *= limit / scale;
}
class Pid {
 public:
  void reset() { integral_ = 0; previous_ = 0; started_ = false; }
  float update(float target, float measured, float dt, const config::Calibration& c) {
    if (target == 0 || dt <= 0) { reset(); return 0; }
    const float error = target - measured;
    const float derivative = started_ ? -(measured - previous_) / dt : 0;
    const float candidate = clamp(integral_ + c.ki * error * dt, -255, 255);
    const float raw = c.kp * error + candidate + c.kd * derivative;
    if (fabsf(raw) <= 255 || (raw > 255 && error < 0) || (raw < -255 && error > 0))
      integral_ = candidate;
    previous_ = measured; started_ = true;
    return clamp(c.kp * error + integral_ + c.kd * derivative, -255, 255);
  }
 private:
  float integral_ = 0, previous_ = 0;
  bool started_ = false;
};
enum class Mode { Idle, Drive, Service };
class Controller {
 public:
  config::Calibration cal[3];
  float target[3] = {}, actual[3] = {};
  int pwm[3] = {};
  Mode mode = Mode::Idle;
  bool armed = config::CalibrationConfirmed;
  Controller() {
    for (uint8_t i = 0; i < 3; ++i) cal[i] = config::CalibrationData[i];
    if (!configured()) armed = false;
  }
  bool configured() const {
    for (uint8_t i = 0; i < 3; ++i) if (!valid(cal[i])) return false;
    return true;
  }
  bool ready() const { return armed && configured(); }
  bool moving() const {
    for (uint8_t i = 0; i < 3; ++i) if (target[i] != 0 || pwm[i] != 0) return true;
    return false;
  }
  void stop() {
    for (uint8_t i = 0; i < 3; ++i) { target[i] = 0; pwm[i] = 0; pid_[i].reset(); }
    openLoop_ = false;
    if (mode == Mode::Drive) mode = Mode::Idle;
  }
  const char* accept(const Command& cmd, uint32_t now) {
    if (cmd.kind == Kind::Stop) { stop(); return nullptr; }
    if (cmd.kind == Kind::Service) { stop(); mode = Mode::Service; return nullptr; }
    if (cmd.kind == Kind::Exit) { stop(); mode = Mode::Idle; return nullptr; }
    if (cmd.kind == Kind::Move) {
      if (mode == Mode::Service) return "SERVICE_ACTIVE";
      if (!ready()) return "NOT_CALIBRATED";
      if (cmd.value[0] == 0 && cmd.value[1] == 0 && cmd.value[2] == 0) stop();
      else { mix(cmd.value[0], cmd.value[1], cmd.value[2], cal, target); mode = Mode::Drive; }
      lastMotion_ = now; return nullptr;
    }
    if (mode != Mode::Service) return "SERVICE_REQUIRED";
    if (cmd.kind == Kind::Set) {
      if (moving()) return "STOP_REQUIRED";
      config::Calibration c = {cmd.value[0], cmd.value[1], cmd.value[2], cmd.value[3], cmd.value[4]};
      if (!valid(c)) return "BAD_CONFIG";
      cal[cmd.motor] = c; armed = false; return nullptr;
    }
    if (cmd.kind == Kind::Arm) {
      if (moving()) return "STOP_REQUIRED";
      if (!configured()) return "NOT_CALIBRATED";
      armed = true; return nullptr;
    }
    if (cmd.kind == Kind::Zero) return moving() ? "STOP_REQUIRED" : nullptr;
    if (cmd.kind == Kind::Rpm && (!valid(cal[cmd.motor]) ||
        fabsf(cmd.value[0]) > cal[cmd.motor].maxRpm)) return "BAD_RPM";
    const bool nextOpen = cmd.kind == Kind::Pwm;
    if (serviceMotor_ != cmd.motor || openLoop_ != nextOpen) stop();
    serviceMotor_ = cmd.motor; openLoop_ = nextOpen;
    for (uint8_t i = 0; i < 3; ++i)
      if (i != cmd.motor) { target[i] = 0; pwm[i] = 0; pid_[i].reset(); }
    if (openLoop_) { target[cmd.motor] = 0; pwm[cmd.motor] = static_cast<int>(cmd.value[0]); }
    else target[cmd.motor] = cmd.value[0];
    lastMotion_ = now; return nullptr;
  }
  void watchdog(uint32_t now) {
    if (moving() && static_cast<uint32_t>(now - lastMotion_) >= config::TimeoutMs) stop();
  }
  void step(float dt) {
    if (openLoop_) return;
    for (uint8_t i = 0; i < 3; ++i)
      pwm[i] = static_cast<int>(pid_[i].update(target[i], actual[i], dt, cal[i]));
  }
 private:
  Pid pid_[3];
  uint32_t lastMotion_ = 0;
  bool openLoop_ = false;
  int serviceMotor_ = -1;
};
inline int8_t quadrature(uint8_t previous, uint8_t current) {
  const int8_t transitions[16] = {0, -1, 1, 0, 1, 0, 0, -1,
                                -1, 0, 0, 1, 0, 1, -1, 0};
  return transitions[(previous << 2) | current];
}
}  // namespace robot
