#!/usr/bin/env python3
"""Restore observed Joy-Con 2 initialisation/pairing behavior on the latest endpoint.

Applied after f27_g5_integrate.py + f27_g5_re_refresh.py. The RE refresh was
intentionally conservative and removed the provisional 0x15 pairing responder,
but current captured protocol documentation establishes that Switch 2 requires
successful pairing to complete controller initialisation and that the exchange
can be performed over USB. This transform restores that documented behavior and
fills the response payloads used in the observed Joy-Con initialisation path.
"""
from pathlib import Path

PATH = Path("OpenPuck/mode_joycon2.cpp")
src = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global src
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"JC2 init fidelity {label}: anchor count {count}, expected 1")
    src = src.replace(old, new, 1)


# Binary witness for artifact validation.
replace_once(
    "JoyCon2Controller g_joyCon2;\n",
    "JoyCon2Controller g_joyCon2;\n"
    "static const char g_jc2InitFidelityMarker[] __attribute__((used)) =\n"
    "\t\"F27-JC2-R374-INIT-PAIRING-FIDELITY\";\n",
    "marker",
)

# Captured Joy-Con feature-info values differ from the Pro Controller for IMU,
# magnetometer and mouse support: Joy-Con reports 0x03 for those capabilities.
replace_once(
    "\tif (flags & 0x04)\n\t\tout[2] = 0x01;\n"
    "\tif (flags & 0x80)\n\t\tout[3] = 0x01;\n"
    "\tif (flags & 0x10)\n\t\tout[4] = 0x01;\n",
    "\tif (flags & 0x04)\n\t\tout[2] = 0x03;\n"
    "\tif (flags & 0x80)\n\t\tout[3] = 0x03;\n"
    "\tif (flags & 0x10)\n\t\tout[4] = 0x03;\n",
    "Joy-Con feature info",
)

# Re-introduce the documented 0x15 pseudo-OOB pairing exchange. Wire-format
# A1/A2/LTK values are byte-reversed for the AES computation exactly as in the
# published capture notes. B1 is the fixed controller key observed on hardware.
pairing = r'''
static uint8_t g_jc2PairLtk[16];
static bool g_jc2PairLtkValid = false;
static const uint8_t JC2_PAIR_PUBLIC[16] = {
	0x5c, 0xf6, 0xee, 0x79, 0x2c, 0xdf, 0x05, 0xe1,
	0xba, 0x2b, 0x63, 0x25, 0xc4, 0x1a, 0x5f, 0x10,
};

struct Jc2EcbBlock {
	uint8_t key[16];
	uint8_t clear[16];
	uint8_t cipher[16];
} __attribute__((aligned(4)));

static bool jc2Aes128Ecb(const uint8_t key[16], const uint8_t clear[16],
			 uint8_t cipher[16])
{
	static Jc2EcbBlock block;
	memcpy(block.key, key, 16);
	memcpy(block.clear, clear, 16);
	NRF_ECB->TASKS_STOPECB = 1;
	NRF_ECB->EVENTS_ENDECB = 0;
	NRF_ECB->EVENTS_ERRORECB = 0;
	NRF_ECB->ECBDATAPTR = (uint32_t)&block;
	NRF_ECB->TASKS_STARTECB = 1;
	while (!NRF_ECB->EVENTS_ENDECB && !NRF_ECB->EVENTS_ERRORECB) {
	}
	if (NRF_ECB->EVENTS_ERRORECB)
		return false;
	memcpy(cipher, block.cipher, 16);
	return true;
}

static void jc2ControllerAddress(uint8_t out[6])
{
	uint32_t a = NRF_FICR->DEVICEID[0], b = NRF_FICR->DEVICEID[1];
	out[0] = (uint8_t)a;
	out[1] = (uint8_t)(a >> 8);
	out[2] = (uint8_t)(a >> 16);
	out[3] = (uint8_t)(a >> 24);
	out[4] = (uint8_t)b;
	out[5] = (uint8_t)(b >> 8);
}

static void jc2PairResponse(const uint8_t challenge[16], uint8_t out[16])
{
	uint8_t key[16], clear[16], cipher[16];
	for (uint8_t i = 0; i < 16; i++) {
		key[i] = g_jc2PairLtk[15 - i];
		clear[i] = challenge[15 - i];
	}
	if (!g_jc2PairLtkValid || !jc2Aes128Ecb(key, clear, cipher)) {
		memset(out, 0, 16);
		return;
	}
	memcpy(out, cipher, 16);
}

static uint8_t handlePairing(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
	uint8_t sub = cmd[3];
	dataHeader(reply, 0x15, cmd[2], sub);
	if (sub == 0x01) {
		uint8_t addr[6];
		jc2ControllerAddress(addr);
		reply[8] = 0x01;
		reply[9] = 0x04;
		reply[10] = 0x01;
		memcpy(reply + 11, addr, sizeof addr);
		return 17;
	}
	if (sub == 0x04 && n >= 25) {
		reply[8] = 0x01;
		memcpy(reply + 9, JC2_PAIR_PUBLIC, sizeof JC2_PAIR_PUBLIC);
		for (uint8_t i = 0; i < 16; i++)
			g_jc2PairLtk[i] = cmd[9 + i] ^ JC2_PAIR_PUBLIC[i];
		g_jc2PairLtkValid = true;
		return 25;
	}
	if (sub == 0x02 && n >= 25) {
		reply[8] = 0x01;
		jc2PairResponse(cmd + 9, reply + 9);
		return 25;
	}
	if (sub == 0x03) {
		reply[8] = 0x01;
		return 9;
	}
	reply[8] = 0x01;
	return 9;
}

'''
replace_once(
    "\nstatic void buildVendorReply()\n",
    "\n" + pairing + "static void buildVendorReply()\n",
    "pairing insertion",
)

# The previous generic handlers returned only an 8-byte header for several
# commands whose captured Joy-Con responses carry mandatory data. Match those
# observed lengths/payloads so the console can advance through initialisation.
old_group = """\tcase 0x07:\n\tcase 0x09:\n\tcase 0x0a:\n\tcase 0x0b:\n\tcase 0x0d:\n\tcase 0x11:\n\tcase 0x16:\n\tcase 0x17:\n\tcase 0x18:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tbreak;\n"""
new_group = """\tcase 0x07:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tif (sub == 0x01) {\n\t\t\treply[8] = 0x00;\n\t\t\treplyLen = 9;\n\t\t}\n\t\tbreak;\n\tcase 0x09:\n\tcase 0x0a:\n\tcase 0x0d:\n\tcase 0x17:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tbreak;\n\tcase 0x0b:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tif (sub == 0x03) {\n\t\t\tstatic const uint8_t voltage[4] = { 0xa5, 0x0e, 0x00, 0x00 };\n\t\t\tmemcpy(reply + 8, voltage, sizeof voltage);\n\t\t\treplyLen = 12;\n\t\t} else if (sub == 0x04) {\n\t\t\tstatic const uint8_t charge[4] = { 0x34, 0x00, 0x83, 0x00 };\n\t\t\tmemcpy(reply + 8, charge, sizeof charge);\n\t\t\treplyLen = 12;\n\t\t} else if (sub == 0x06) {\n\t\t\treply[8] = 0x11;\n\t\t\treplyLen = 12;\n\t\t}\n\t\tbreak;\n\tcase 0x11:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tif (sub == 0x01) {\n\t\t\treply[8] = 0x01;\n\t\t\treplyLen = 12;\n\t\t} else if (sub == 0x03) {\n\t\t\tstatic const uint8_t info[29] = {\n\t\t\t\t0x01, 0x20, 0x03, 0x00, 0x00, 0x0a, 0xe8, 0x1c,\n\t\t\t\t0x3b, 0x79, 0x7d, 0x8b, 0x3a, 0x0a, 0xe8, 0x9c,\n\t\t\t\t0x42, 0x58, 0xa0, 0x0b, 0x42, 0x0a, 0xe8, 0x9c,\n\t\t\t\t0x41, 0x58, 0xa0, 0x0b, 0x41,\n\t\t\t};\n\t\t\tmemcpy(reply + 8, info, sizeof info);\n\t\t\treplyLen = 37;\n\t\t}\n\t\tbreak;\n\tcase 0x13:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tif (sub == 0x01) {\n\t\t\treply[8] = 0x01;\n\t\t\treplyLen = 12;\n\t\t} else if (sub == 0x02 || sub == 0x03) {\n\t\t\treply[8] = 0x01;\n\t\t\treplyLen = 16;\n\t\t}\n\t\tbreak;\n\tcase 0x16:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tif (sub == 0x01)\n\t\t\treplyLen = 32; // 24 observed zero data bytes.\n\t\tbreak;\n\tcase 0x18:\n\t\tdataHeader(reply, id, seq, sub);\n\t\tif (sub == 0x01) {\n\t\t\tstatic const uint8_t info[8] = {\n\t\t\t\t0x00, 0x00, 0x40, 0xf0, 0x00, 0x00, 0x60, 0x00,\n\t\t\t};\n\t\t\tmemcpy(reply + 8, info, sizeof info);\n\t\t\treplyLen = 16;\n\t\t} else if (sub == 0x03) {\n\t\t\treply[8] = n >= 9 ? cmd[8] : 0x07;\n\t\t\treplyLen = 9;\n\t\t}\n\t\tbreak;\n"""
replace_once(old_group, new_group, "observed response group")

# Dispatch the restored pairing command before the generic command handlers.
replace_once(
    "\tcase 0x01:\n",
    "\tcase 0x15:\n\t\treplyLen = handlePairing(cmd, n, reply);\n\t\tbreak;\n\tcase 0x01:\n",
    "pairing dispatch",
)

PATH.write_text(src, encoding="utf-8")
print("F27 JC2 observed init/pairing fidelity applied")
