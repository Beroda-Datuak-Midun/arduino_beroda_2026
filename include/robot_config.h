#pragma once
#include <stdint.h>

namespace config {
constexpr uint32_t Baud = 115200, ControlMs = 10, TelemetryMs = 100, TimeoutMs = 300;
constexpr int ServicePwmLimit = 40;
constexpr bool CalibrationConfirmed = false;
// Verify encoder voltage/output type before enabling internal pullups.
constexpr bool EncoderPullups = false;
struct Pins {
  uint8_t rpwm, lpwm, ren, len, encoderA, encoderB;
  int8_t motorSign, encoderSign;
};
constexpr Pins Motors[3] = {
    {5, 6, 22, 23, 2, 3, 1, 1},       // M1 rear
    {7, 8, 24, 25, 18, 19, 1, 1},     // M2 front right
    {9, 10, 26, 27, 20, 21, 1, 1},    // M3 front left
};
// Axle positions, degrees CCW from forward, viewed from above.
constexpr float WheelAngles[3] = {180.0f, 300.0f, 60.0f};
// Positive wheel motion: tangent CCW about the robot centre.
struct Calibration { float cpr, maxRpm, kp, ki, kd; };
// Measured x4 counts/output-shaft revolution, safe RPM, PID gains. Never guess.
constexpr Calibration CalibrationData[3] = {
    {0, 0, 0, 0, 0}, {0, 0, 0, 0, 0}, {0, 0, 0, 0, 0},
};
}  // namespace config
