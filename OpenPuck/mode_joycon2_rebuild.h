#pragma once
#include "controllers.h"

// F27 clean reconstruction stage 1: stock TinyUSB HID plumbing with only
// Joy-Con 2 R USB identity changed. No native Joy-Con report contract or
// Nintendo vendor interface exists at this stage.
class JoyCon2RebuildController : public IController {
    public:
	void begin() override;
};

extern JoyCon2RebuildController g_joyCon2Rebuild;
