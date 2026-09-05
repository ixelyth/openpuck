// f27_joycon2.h -- F27 Joy-Con 2 mouse-emulation proof-of-concept hooks.
#pragma once
#include <stdint.h>

#define F27_JOYCON_OFF 0
#define F27_JOYCON_L 1
#define F27_JOYCON_R 2
#define F27_JOYCON_BOTH 3

#ifndef OPK_F27_JOYCON_TARGET
#define OPK_F27_JOYCON_TARGET F27_JOYCON_OFF
#endif

#if OPK_F27_JOYCON_TARGET < F27_JOYCON_OFF || \
	OPK_F27_JOYCON_TARGET > F27_JOYCON_BOTH
#error "OPK_F27_JOYCON_TARGET must be 0(off), 1(L), 2(R), or 3(Both)"
#endif

#if OPK_F27_JOYCON_TARGET == F27_JOYCON_L
#define F27_JOYCON_DEFAULT_REPORT 0x07
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R
#define F27_JOYCON_DEFAULT_REPORT 0x08
#else
#define F27_JOYCON_DEFAULT_REPORT 0x09
#endif

#if OPK_F27_JOYCON_TARGET == F27_JOYCON_OFF
#define F27_JOYCON_INITIAL_FEATURE_MASK 0x00
#else
#define F27_JOYCON_INITIAL_FEATURE_MASK 0x37
#endif

bool f27JoyconEnabled();
uint8_t f27JoyconTarget();
uint8_t f27JoyconSelectReport(uint8_t requested);
void f27JoyconPatchIdentity(uint8_t *data, uint16_t len);
void f27JoyconPatchFlash(uint32_t address, uint8_t *data, uint8_t len);

// Build one 63-byte native Joy-Con payload. `reportId` is both input and output:
// L/R force 0x07/0x08; Both alternates 0x07 and 0x08 so the console can tell us
// whether one Nintendo USB session will demultiplex two Joy-Con native reports.
bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,
			  uint8_t out[63]);
