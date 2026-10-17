#include <assert.h>
#include <iostream>
#include <string>
#include "robot_core.h"

static robot::Command command(const char* text) {
  char line[160];
  strncpy(line, text, sizeof(line));
  robot::Command cmd;
  assert(robot::parse(line, cmd));
  return cmd;
}
static bool accepted(robot::Controller& c, const char* text, uint32_t now = 0) {
  return c.accept(command(text), now) == nullptr;
}
static bool parses(const char* text) {
  char line[160];
  strncpy(line, text, sizeof(line));
  robot::Command cmd;
  return robot::parse(line, cmd);
}
static void calibrate(robot::Controller& c) {
  assert(accepted(c, "SERVICE"));
  assert(accepted(c, "SET 1 1000 100 1 0.5 0"));
  assert(accepted(c, "SET 2 1000 120 1 0.5 0"));
  assert(accepted(c, "SET 3 1000 110 1 0.5 0"));
  assert(accepted(c, "ARM"));
  assert(accepted(c, "EXIT"));
}
static bool near(float a, float b) { return fabsf(a - b) < 0.001f; }

int main() {
  // Strict syntax/ranges and framing recovery must not turn a suffix into STOP.
  const char* invalid[] = {"", "MOVE 1 0", "MOVE 1 0 0 x", "MOVE nan 0 0",
      "MOVE inf 0 0", "MOVE 1e99 0 0", "MOVE 1.01 0 0", "MOVE 0 junk 0",
      "STOP NOW", "PWM 0 1", "PWM 4 1", "PWM 1.5 10", "PWM 1 41",
      "PWM 1 2.5", "PWM 1 nan", "SET 1 100 20 1 0", "RPM 1 infinity"};
  for (auto line : invalid) assert(!parses(line));
  assert(parses("MOVE -1 0 1"));
  assert(parses("PWM 3 -40"));
  robot::LineReader reader;
  for (int i = 0; i < 100; ++i) assert(!reader.push('x'));
  for (char ch : std::string("STOP\n")) reader.push(ch);
  assert(reader.invalid);
  for (char ch : std::string("MOVE 0 0 0\r\n")) reader.push(ch);
  assert(!reader.invalid && strcmp(reader.line, "MOVE 0 0 0") == 0);
  reader.push('\0'); reader.push('\n'); assert(reader.invalid);

  robot::Controller c;
  assert(!c.ready() && !c.moving());
  assert(!accepted(c, "MOVE 1 0 0"));
  assert(!accepted(c, "PWM 1 20"));
  assert(accepted(c, "SERVICE"));
  assert(!accepted(c, "ARM"));
  assert(accepted(c, "PWM 1 20", 10));
  assert(c.pwm[0] == 20 && c.pwm[1] == 0);
  assert(!accepted(c, "ZERO"));
  assert(!accepted(c, "SET 1 1000 100 1 0 0"));
  assert(!accepted(c, "MOVE 1 0 0"));
  assert(!accepted(c, "RPM 1 10"));
  c.watchdog(309); assert(c.pwm[0] == 20);
  c.watchdog(310); assert(!c.moving() && c.mode == robot::Mode::Service);
  assert(accepted(c, "ZERO"));
  assert(accepted(c, "EXIT"));
  calibrate(c);
  assert(c.ready());

  assert(accepted(c, "MOVE 1 0 0", 1000));
  assert(c.target[0] == 0 && near(c.target[1], 86.60254f) && near(c.target[2], -86.60254f));
  float forward[3]; for (int i = 0; i < 3; ++i) forward[i] = c.target[i];
  assert(accepted(c, "MOVE -1 0 0", 1000));
  for (int i = 0; i < 3; ++i) assert(near(c.target[i], -forward[i]));
  assert(accepted(c, "MOVE 0 0 1", 1000));
  for (float target : c.target) assert(near(target, 100));
  assert(accepted(c, "MOVE 0 0 -1", 1000));
  for (float target : c.target) assert(near(target, -100));
  assert(accepted(c, "MOVE 1 0 1", 1000));
  assert(near(c.target[1], 100));
  assert(near(c.target[0] / c.target[1], 1 / 1.8660254f));
  for (float target : c.target) assert(fabsf(target) <= 100.001);
  c.step(0.01f); assert(c.pwm[1] > 0);
  assert(!accepted(c, "SET 1 1000 100 1 0 0", 1100));
  c.watchdog(1299); assert(c.moving());
  c.watchdog(1300); assert(!c.moving() && c.mode == robot::Mode::Idle);
  assert(accepted(c, "MOVE 1 0 0", 0xFFFFFFF0U));
  c.watchdog(0x0000011BU); assert(c.moving());
  c.watchdog(0x0000011CU); assert(!c.moving());
  assert(accepted(c, "MOVE 1 0 0", 0));
  assert(accepted(c, "MOVE 0 0 0", 10)); assert(!c.moving());
  assert(accepted(c, "SERVICE"));
  assert(!accepted(c, "RPM 1 101"));
  assert(accepted(c, "RPM 1 10", 100));
  c.step(0.1f); int first = c.pwm[0];
  assert(accepted(c, "RPM 1 10", 150)); c.step(0.1f);
  assert(c.pwm[0] > first); // Heartbeats retain integral state.
  assert(accepted(c, "PWM 2 -30", 180));
  assert(c.pwm[0] == 0 && c.pwm[1] == -30 && c.target[0] == 0);
  assert(accepted(c, "STOP")); c.step(0.01f); assert(!c.moving());
  assert(!accepted(c, "SET 1 0 100 1 0 0"));
  assert(!accepted(c, "SET 1 1000 100 0 0 0"));
  assert(accepted(c, "SET 1 1000 100 1 0 0")); assert(!c.ready());

  robot::Pid pid;
  config::Calibration gains = {1000, 100, 100, 10, 0};
  for (int i = 0; i < 1000; ++i) assert(pid.update(100, 0, .01f, gains) == 255);
  assert(near(pid.update(1, 1, .01f, gains), 0)); // No integral windup.
  assert(pid.update(-100, 0, .01f, gains) == -255);
  assert(pid.update(0, 50, .01f, gains) == 0);
  gains.kp = 1; gains.ki = 0;
  assert(pid.update(1, 0, .01f, gains) == 1);
  assert(robot::quadrature(0, 3) == 0); // Illegal two-bit jump.
  const uint8_t cycle[] = {0, 2, 3, 1, 0};
  int count = 0;
  for (int i = 0; i < 4; ++i) count += robot::quadrature(cycle[i], cycle[i+1]);
  assert(count == 4);
  count = 0;
  for (int i = 4; i > 0; --i) count += robot::quadrature(cycle[i], cycle[i-1]);
  assert(count == -4);
  std::cout << "Firmware core: all scenarios passed\n";
}
