# F27 — Joy-Con 2 mouse-emulation proof of concept

F27 is an isolated hardware experiment built on the current `switch2pro` transport. It does not change PR #269. The test images reuse the proven Nintendo Switch 2 Pro USB session and replace the logical controller identity/native input stream at build time.

## Targets

`OPK_F27_JOYCON_TARGET` selects one of three artifacts:

- `1` — Joy-Con 2 (L): factory/logical PID `0x2067`, native report `0x07`, left Steam trackpad drives the mouse.
- `2` — Joy-Con 2 (R): factory/logical PID `0x2066`, native report `0x08`, right Steam trackpad drives the mouse.
- `3` — Joy-Con 2 Both: experimental logical PID `0x2068`; one USB session alternates native reports `0x07` and `0x08`. This deliberately tests whether Switch 2 demultiplexes both halves. There is no evidence that a physical `0x2068` USB pair exists; SDL creates `0x2068` only as a synthetic combined host-side identity.

The normal repository source remains the reviewed Pro Controller 2 implementation. `tools/f27_joycon2_poc.py` applies the small integration hooks only in F27 artifact builds.

## Compatibility strategy

L and R follow the split-identity behavior demonstrated by NS-PC-Control:

- USB enumeration remains the known-good Pro Controller 2 session (`057E:2069`) and Pro2 HID descriptor.
- Factory memory / EP0 identity is changed to `2067` (L) or `2066` (R).
- Native streaming changes to `0x07` or `0x08`.
- Joy-Con mouse feature bit `0x10` is included in the initial feature mask (`0x37`: buttons, sticks, IMU, mouse, rumble).
- A console request for report `0x09` is translated to the selected Joy-Con native report. This covers the case where the Pro2 USB descriptor causes the host to request `0x09` before logical identity takes effect.

`Both` intentionally extends that idea beyond published evidence. If it fails while L/R work, the next experiment should be a true dual-function / dual-session USB facade rather than more report multiplexing.

## Trackpad mouse model

The Steam Controller already supplies signed 16-bit absolute trackpad coordinates plus independent capacitive touch bits.

For each virtual Joy-Con:

- touch-down stores the current pad coordinate and emits zero movement, preventing a cursor jump;
- while touched, coordinate differences become signed Joy-Con mouse deltas;
- Y is inverted to screen-coordinate convention, matching OpenPuck's existing XInput mouse path;
- `g_mDiv` is reused as the sensitivity divisor with remainder carry so small movement is not quantized away;
- touch release clears residual motion;
- pad click maps to the real Joy-Con mouse-posture primary shoulder (`L` for L, `R` for R).

The console remains authoritative: if Joy-Con mouse feature bit `0x10` is not enabled, trackpad touch does not assert mouse surface state.

## Surface / flat-posture synthesis

Public captures identify the final byte of the native five-byte mouse block as a surface / likely lift-off-distance state. The hardware-tested synthetic values used by NS-PC-Control are:

- `0x17` — on surface
- `0xFF` — off surface

F27 maps capacitive pad touch to this state. A stationary finger therefore remains `0x17` even when `dx=dy=0`; it does not blink off merely because one 4 ms report contains no movement.

When mouse is active and IMU feature bit `0x04` is enabled, F27 also emits the captured stationary Joy-Con mouse posture as a 30-byte native motion carrier:

- stationary identity orientation;
- +1 g on native Switch 2 X;
- zero angular rate;
- approximately 4 ms timing progression.

This reproduces the coherent state a real Joy-Con reports when its optical side is resting on a surface, even though the Steam Controller is being held normally.

When the trackpad is released, surface becomes `0xFF` and native motion length returns to zero in this first proof of concept. Full live Switch 2 motion-carrier translation is intentionally deferred until controller recognition and mouse activation are proven; ordinary stick/button state remains live.

## Button / stick split

Joy-Con L uses the Steam Controller's left stick, D-pad, L/ZL, L3 and `-`. L4/L5 provide SL/SR in the POC. QAM provides Capture.

Joy-Con R uses the right stick, ABXY, R/ZR, R3 and `+`. R4/R5 provide SL/SR, QAM provides C and the Steam button provides Home.

The existing Nintendo A/B and X/Y swap setting is honored on the R face buttons.

## Hardware test order

Test L and R independently before Both.

For each image:

1. Flash the F27 Makerdiary MDK UF2.
2. Enter the existing Switch 2 clean mode (mode 13) if it is not already persisted.
3. Confirm controller enumeration / Change Grip-Order behavior before touching a pad.
4. Confirm the console enables Joy-Con mouse controls / feature `0x10`.
5. Touch the assigned trackpad without moving it. The cursor should become available without physical controller reorientation.
6. Move slowly in all four directions and record axis/sign/sensitivity behavior.
7. Stop while keeping the finger down; cursor hover must remain stable.
8. Release the finger; cursor should leave mouse mode immediately and stick/button input should continue.
9. Repeat with pad click.
10. For `Both`, record whether the console shows zero, one, or two Joy-Con halves and whether either/both cursors respond.

A successful L/R result proves that trackpad-to-native-mouse translation and synthetic flat/surface state work. A successful Both result would additionally prove that one OpenPuck USB device can carry two logical Joy-Con halves through a single Nintendo session. A Both failure does not invalidate mouse emulation; it only rejects this first multiplex transport strategy.
