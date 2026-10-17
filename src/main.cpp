#include <Arduino.h>
#include <util/atomic.h>
#include <stdio.h>
#include "robot_core.h"

namespace {
robot::Controller controller;
robot::LineReader reader;
volatile uint32_t ticks[3] = {};
volatile uint8_t phases[3] = {};
uint32_t previousTicks[3] = {}, snapshot[3] = {};
uint32_t lastControl = 0, lastTelemetry = 0;

// Bounded nonblocking transmission: a slow receiver cannot delay the watchdog.
char tx[4][240];
uint8_t txHead = 0, txCount = 0;
uint16_t txOffset = 0;
void enqueue(const char* line) {
  if (txCount == 4) return;
  strncpy(tx[(txHead + txCount) % 4], line, sizeof(tx[0]) - 1);
  tx[(txHead + txCount) % 4][sizeof(tx[0]) - 1] = '\0';
  ++txCount;
}
void transmit() {
  if (!txCount) return;
  const char* line = tx[txHead];
  const size_t remaining = strlen(line + txOffset);
  const size_t available = Serial.availableForWrite();
  const size_t amount = remaining < available ? remaining : available;
  txOffset += Serial.write(reinterpret_cast<const uint8_t*>(line + txOffset), amount);
  if (line[txOffset] == '\0') { txHead = (txHead + 1) % 4; --txCount; txOffset = 0; }
}
void encoder(uint8_t index) {
  const auto& p = config::Motors[index];
  const uint8_t current = (digitalRead(p.encoderA) << 1) | digitalRead(p.encoderB);
  ticks[index] += robot::quadrature(phases[index], current) * p.encoderSign;
  phases[index] = current;
}
void encoder0() { encoder(0); }
void encoder1() { encoder(1); }
void encoder2() { encoder(2); }
void outputs() {
  for (uint8_t i = 0; i < 3; ++i) {
    const auto& p = config::Motors[i];
    const int value = controller.pwm[i] * p.motorSign;
    // Clear the inactive PWM first, including when direction reverses.
    if (value > 0) { analogWrite(p.lpwm, 0); analogWrite(p.rpwm, value); }
    else { analogWrite(p.rpwm, 0); analogWrite(p.lpwm, -value); }
    digitalWrite(p.ren, value != 0 ? HIGH : LOW);
    digitalWrite(p.len, value != 0 ? HIGH : LOW);
  }
}
void receive(uint32_t now) {
  for (uint8_t budget = 0; budget < 64 && Serial.available(); ++budget) {
    if (!reader.push(static_cast<char>(Serial.read()))) continue;
    robot::Command cmd;
    if (reader.invalid || !robot::parse(reader.line, cmd)) {
      enqueue("ERR BAD_COMMAND\n"); continue;
    }
    const char* error = controller.accept(cmd, now);
    if (error) {
      char message[64];
      snprintf(message, sizeof(message), "ERR %s\n", error);
      enqueue(message); continue;
    }
    if (cmd.kind == robot::Kind::Zero) {
      ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
        for (uint8_t i = 0; i < 3; ++i) ticks[i] = 0;
      }
      for (uint8_t i = 0; i < 3; ++i) {
        previousTicks[i] = snapshot[i] = 0; controller.actual[i] = 0;
      }
      lastControl = now;
    }
    if (cmd.kind != robot::Kind::Move && cmd.kind != robot::Kind::Pwm && cmd.kind != robot::Kind::Rpm) {
      const char* names[] = {"STOP", "MOVE", "SERVICE", "EXIT", "PWM", "RPM", "ZERO", "SET", "ARM"};
      char response[24];
      snprintf(response, sizeof(response), "OK %s\n", names[static_cast<uint8_t>(cmd.kind)]);
      enqueue(response);
    }
    outputs();
  }
}
void telemetry(uint32_t now) {
  if (txCount) return;
  const char* mode = controller.mode == robot::Mode::Service ? "SERVICE" :
                     controller.mode == robot::Mode::Drive ? "DRIVE" : "IDLE";
  char line[240];
  const int length = snprintf(line, sizeof(line),
      "TEL %lu %s %u %.2f %.2f %ld %d %.2f %.2f %ld %d %.2f %.2f %ld %d\n",
      static_cast<unsigned long>(now), mode, controller.ready() ? 1 : 0,
      static_cast<double>(controller.target[0]), static_cast<double>(controller.actual[0]),
      static_cast<long>(static_cast<int32_t>(snapshot[0])), controller.pwm[0],
      static_cast<double>(controller.target[1]), static_cast<double>(controller.actual[1]),
      static_cast<long>(static_cast<int32_t>(snapshot[1])), controller.pwm[1],
      static_cast<double>(controller.target[2]), static_cast<double>(controller.actual[2]),
      static_cast<long>(static_cast<int32_t>(snapshot[2])), controller.pwm[2]);
  if (length > 0 && static_cast<size_t>(length) < sizeof(line)) enqueue(line);
}
}  // namespace

void setup() {
  for (uint8_t i = 0; i < 3; ++i) {
    const auto& p = config::Motors[i];
    const uint8_t pins[] = {p.rpwm, p.lpwm, p.ren, p.len};
    for (uint8_t pin : pins) { digitalWrite(pin, LOW); pinMode(pin, OUTPUT); }
    pinMode(p.encoderA, config::EncoderPullups ? INPUT_PULLUP : INPUT);
    pinMode(p.encoderB, config::EncoderPullups ? INPUT_PULLUP : INPUT);
    phases[i] = (digitalRead(p.encoderA) << 1) | digitalRead(p.encoderB);
  }
  void (*handlers[3])() = {encoder0, encoder1, encoder2};
  for (uint8_t i = 0; i < 3; ++i) {
    attachInterrupt(digitalPinToInterrupt(config::Motors[i].encoderA), handlers[i], CHANGE);
    attachInterrupt(digitalPinToInterrupt(config::Motors[i].encoderB), handlers[i], CHANGE);
  }
  Serial.begin(config::Baud);
  lastControl = millis();
  enqueue("BOOT OMNI1\n");
}
void loop() {
  const uint32_t now = millis();
  controller.watchdog(now);
  outputs();
  receive(now);
  const uint32_t elapsed = now - lastControl;
  if (elapsed >= config::ControlMs) {
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
      for (uint8_t i = 0; i < 3; ++i) snapshot[i] = ticks[i];
    }
    for (uint8_t i = 0; i < 3; ++i) {
      const int32_t delta = static_cast<int32_t>(snapshot[i] - previousTicks[i]);
      previousTicks[i] = snapshot[i];
      const float cpr = controller.cal[i].cpr;
      controller.actual[i] = cpr > 0 ? delta * 60000.0f / (cpr * elapsed) : 0;
    }
    controller.step(elapsed / 1000.0f);
    lastControl = now;
    outputs();
  }
  if (static_cast<uint32_t>(now - lastTelemetry) >= config::TelemetryMs) {
    lastTelemetry = now; telemetry(now);
  }
  transmit();
}
