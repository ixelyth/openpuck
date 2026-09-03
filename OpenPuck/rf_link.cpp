#include "rf_link.h"
#include "radio.h"
#include "bonds.h"
#include "config.h"
#include "triton.h"
#include "haptics.h"
#include "puck_hid.h" // g_cmdCapture (suppress I45 during feature-command capture)
#include "controllers.h"
#include "status_led.h"
#include "fault_diag.h"
#include "usb_mount.h" // modeSwitchReboot()
#include <Adafruit_TinyUSB.h>
#include <Arduino.h>
#include <string.h>

bool g_rfHost = true;
bool g_connOn = true;
uint8_t g_connType = 0xE7; // start with protocol-version handshake, then 0xE3
// 0=current(slow/awake), 1=protocol-version-1. 'V<n>' to toggle.
uint8_t g_e7b = 0;
uint8_t g_connLen = 0x08;
// GET report 0x45 param byte. 'q' cmd.
uint8_t g_getParam = 0x00;
// cycling the ESB PID drains the controller's report queue (~400 new/s vs ~60 with a fixed PID). 'e<n>' selects.
uint8_t g_e3mode = 1;

// ---- real-puck alignment (sniff1.json: a bonded controller RECONNECTING) ----
// The live air capture of a real puck<->controller reconnect shows the controller streams 0xF1 input in
// response to a BARE 0xE3 poll (1-byte payload, just the opcode) with NO 0xE7 awake-announce and NO
// GET-report-0x45 sub-TLV -- 1857 of the puck's 2003 polls were bare E3, and the very first session frame
// (a bare E3) was answered by F1 immediately. That contradicts the earlier RE "recipe" (rf_link.h) which
// assumed E7 + GET-0x45 were required. So these now default to the real-puck behavior; flip them at runtime
// ('d'/'n' console cmds) to fall back to the legacy GET/E7 path for an A/B comparison on hardware.
bool g_pollGet =
	false; // false = bare E3 poll (real puck); true = append GET-report-0x45 TLV (legacy)
bool g_e7announce =
	false; // false = no E7 awake-announce (real puck); true = announce host-awake (legacy)
// Session-channel E1 host-frame keepalive. The real puck sends NO E1 on its session channel (the bonded
// controller already knows the per-bond address and just resumes). OpenPuck still needs E1 because it runs
// the SHARED "ibex" address, not the (un-reversed) per-bond address -- E1 is how the controller learns this
// puck's session base/prefix/channel. So this defaults ON; turn it off ('m') to test the real-puck "no
// session E1" model once per-bond addressing exists. Discovery on ch2 is separate and always runs.
bool g_e1keepalive = true;

bool g_connVerbose = false;
// poll RX-window (us): the poll BUSY-WAITS up to this long for the controller's reply. The reply returns
// EARLY (EVENTS_END) on a successful poll, so this window is only paid IN FULL on a genuine no-reply --
// one slot needs (g_rxWin + overhead) < g_pollUs(4000) so a no-reply poll still fits inside the 250 Hz
// cycle. 1200 is the proven value; it was briefly raised to 2000 (issue-72, delayed-reply tolerance) which
// dropped the rate. FIXED + not configurable (like g_pollUs): there is no good reason to raise it in the
// field, and doing so silently starves the poll cycle. Any persisted/old value is ignored.
const uint32_t g_rxWin = 1200;
unsigned long g_connCooldown = 0;

uint8_t g_connSt = 0; // 0=announce awake, 1=poll loop
uint8_t g_connStep = 0; // repeat counter within a state
uint16_t g_connPoll = 0; // poll counter (re-assert awake every 32nd)
uint32_t g_connF1 = 0;
uint8_t g_connF3v = 0xFF;

uint8_t g_qos = 1;
uint8_t g_hopIdx = 0;
volatile uint16_t g_qosBad = 0;
unsigned long g_qosCheckMs = 0, g_qosLastHopMs = 0;

// clean, spread channels (from the puck's RSSI/PER scan)
unsigned long g_linkQualityCheckMs = 0, g_lastChannelHopMs = 0;

#define RF_LINK_QUALITY_WINDOW_MS 1000u
#define RF_LINK_QUALITY_MIN_POLLS 150u
// Three valid windows below this success threshold can request one recovery
// attempt after the minimum channel residence.
#define RF_LINK_QUALITY_BAD_SUCCESS_PERMILLE 550u
#define RF_LINK_QUALITY_BAD_STREAK_WINDOWS 3u
#define RF_LINK_QUALITY_MIN_RESIDENCY_MS 10000u
static uint32_t g_linkQualityPolls[NSLOT] = {};
static uint32_t g_linkQualityReplies[NSLOT] = {};
static uint8_t g_linkQualityBadStreak[NSLOT] = {};

// Recovery target state is session-only and explicit. Zero means disarmed.
static uint8_t g_recoveryTargetChannel = 0;
static uint8_t g_recoveryResidenceChannel = 0;
static bool g_recoveryRequestedThisResidence = false;

#define RF_RECOVERY_CHANNEL_MIN 4u
#define RF_RECOVERY_CHANNEL_MAX 80u
#define RF_RECOVERY_CHANNEL_COUNT 39u
#define RF_CHANNEL_EVIDENCE_WINDOWS 5u
#define RF_CHANNEL_EVIDENCE_MIN_SUCCESS_PERMILLE 800u
#define RF_CHANNEL_EVIDENCE_MAX_AGE_MS 120000u
#define RF_CHANNEL_RECOVERY_MIN_IMPROVEMENT_PERMILLE 200u

// Recovery evidence is per participant and target authority is cohort-wide.
// The same selector is authoritative for cohorts of one through four participants.
static uint8_t g_channelEvidenceGoodCount[NSLOT][RF_RECOVERY_CHANNEL_COUNT] = {};
static uint32_t g_channelEvidenceGoodSum[NSLOT][RF_RECOVERY_CHANNEL_COUNT] = {};
static uint16_t g_channelEvidenceMean[NSLOT][RF_RECOVERY_CHANNEL_COUNT] = {};
static uint32_t g_channelEvidenceLastGoodMs[NSLOT]
					   [RF_RECOVERY_CHANNEL_COUNT] = {};
static uint8_t g_channelEvidenceParticipantMask = 0;
static uint8_t g_channelEvidenceResidenceChannel = 0;
static bool g_channelRecoveryDecidedThisResidence = false;

// Progressive exploration: no full-band outage scan. One channel is learned
// naturally whenever degradation already requires a migration.
#define RF_CHANNEL_HISTORY_POOL_COUNT 14u
#define RF_CHANNEL_HISTORY_GOOD_WINDOWS 5u
#define RF_CHANNEL_HISTORY_GOOD_PERMILLE 800u
#define RF_CHANNEL_HISTORY_BAD_PERMILLE 550u
#define RF_CHANNEL_HISTORY_BAD_WINDOWS 3u
#define RF_CHANNEL_HISTORY_PERSIST_MAX_WRITES_PER_BOOT 4u
#define RF_CHANNEL_HISTORY_PERSIST_MIN_INTERVAL_MS 30000u
#define RF_CHANNEL_JOURNAL_FORMAT 2u
#define RF_CHANNEL_JOURNAL_PAGE_BYTES 4096u
#define RF_CHANNEL_JOURNAL_PAGE_COUNT 2u
#define RF_CHANNEL_JOURNAL_WORD_INTERVAL_US 8000u
#define RF_CHANNEL_JOURNAL_LIVE_WORD_MAX_US 250u
#define RF_CHANNEL_JOURNAL_TIMER3_TICKS_PER_US 16u
#define RF_CHANNEL_JOURNAL_OFFLINE_GUARD_MS 1000u
#define RF_CHANNEL_JOURNAL_MAGIC 0x51323735u
#define RF_CHANNEL_JOURNAL_COMMIT 0x51323743u
static const uint8_t g_recoveryChannelPool[RF_CHANNEL_HISTORY_POOL_COUNT] = {
	18, 20, 22, 34, 42, 46, 52, 56, 68, 70, 72, 74, 76, 80
};

// Persistent priors are loaded from the channel-history journal. Runtime evidence
// always overrides these priors for operational target selection.
static uint8_t
	g_channelHistoryPersistentWorstPct[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t
	g_channelHistoryPersistentMeanPct[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t
	g_channelHistoryPersistentConfidence[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t
	g_channelHistoryPersistentTrials[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t
	g_channelHistoryPersistentPenalty[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t
	g_channelHistoryPersistentRecentOrder[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t g_channelHistoryPersistentOrderCounter = 0;
static bool g_channelHistoryPersistentLoaded = false;
static bool g_channelHistoryPersistentDirty = false;
static uint32_t g_channelHistoryPersistentGeneration = 0;
static uint8_t g_channelHistoryPersistentWrites = 0;
static unsigned long g_channelHistoryPersistentLastWriteMs = 0;

// Ambient RSSI is diagnostic and can only rank channels that have never been
// tried. Real packet-delivery evidence and learned journal history remain
// authoritative for every explored channel.
#define RF_AMBIENT_SURVEY_PASSES 3u
#define RF_AMBIENT_SURVEY_SAMPLE_US 1200u
#define RF_AMBIENT_SURVEY_STEP_MS 100u
#define RF_AMBIENT_SURVEY_IDLE_GUARD_MS 10000u
#define RF_AMBIENT_SURVEY_REFRESH_MS 60000u
static uint8_t g_ambientStableRssi[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t g_ambientWorkRssi[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t g_ambientWorkSamples[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static bool g_ambientStableValid = false;
static bool g_ambientSurveyRunning = false;
static bool g_ambientSurveyPending = false;
static uint8_t g_ambientSurveyIndex = 0;
static uint8_t g_ambientSurveyPass = 0;
static uint16_t g_ambientSurveyGeneration = 0;
static unsigned long g_ambientSurveyIdleSinceMs = 0;
static unsigned long g_ambientSurveyLastStepMs = 0;
static unsigned long g_ambientSurveyLastCompleteMs = 0;

// Reserve two complete, page-aligned application-flash pages. The linker maps
// .rodata.* only inside application FLASH, whose upper bound is the InternalFS
// start (0xED000 on nRF52840). Therefore these pages cannot alias LittleFS or
// bootloader storage, and an oversized image fails at link time rather than
// silently colliding with persistence.
#define CHANNEL_JOURNAL_FF1 0xFFFFFFFFu
#define CHANNEL_JOURNAL_FF2 CHANNEL_JOURNAL_FF1, CHANNEL_JOURNAL_FF1
#define CHANNEL_JOURNAL_FF4 CHANNEL_JOURNAL_FF2, CHANNEL_JOURNAL_FF2
#define CHANNEL_JOURNAL_FF8 CHANNEL_JOURNAL_FF4, CHANNEL_JOURNAL_FF4
#define CHANNEL_JOURNAL_FF16 CHANNEL_JOURNAL_FF8, CHANNEL_JOURNAL_FF8
#define CHANNEL_JOURNAL_FF32 CHANNEL_JOURNAL_FF16, CHANNEL_JOURNAL_FF16
#define CHANNEL_JOURNAL_FF64 CHANNEL_JOURNAL_FF32, CHANNEL_JOURNAL_FF32
#define CHANNEL_JOURNAL_FF128 CHANNEL_JOURNAL_FF64, CHANNEL_JOURNAL_FF64
#define CHANNEL_JOURNAL_FF256 CHANNEL_JOURNAL_FF128, CHANNEL_JOURNAL_FF128
#define CHANNEL_JOURNAL_FF512 CHANNEL_JOURNAL_FF256, CHANNEL_JOURNAL_FF256
#define CHANNEL_JOURNAL_FF1024 CHANNEL_JOURNAL_FF512, CHANNEL_JOURNAL_FF512
#define CHANNEL_JOURNAL_FF2048 CHANNEL_JOURNAL_FF1024, CHANNEL_JOURNAL_FF1024
__attribute__((used, aligned(RF_CHANNEL_JOURNAL_PAGE_BYTES),
	       section(".rodata.channel_journal"))) static const uint32_t
	g_channelJournalFlash[2048] = { CHANNEL_JOURNAL_FF2048 };
#undef CHANNEL_JOURNAL_FF2048
#undef CHANNEL_JOURNAL_FF1024
#undef CHANNEL_JOURNAL_FF512
#undef CHANNEL_JOURNAL_FF256
#undef CHANNEL_JOURNAL_FF128
#undef CHANNEL_JOURNAL_FF64
#undef CHANNEL_JOURNAL_FF32
#undef CHANNEL_JOURNAL_FF16
#undef CHANNEL_JOURNAL_FF8
#undef CHANNEL_JOURNAL_FF4
#undef CHANNEL_JOURNAL_FF2
#undef CHANNEL_JOURNAL_FF1

struct RfChannelJournalRecord {
	uint32_t magic;
	uint32_t sequence;
	uint8_t format;
	uint8_t poolCount;
	uint8_t orderCounter;
	uint8_t reserved;
	uint8_t worstPct[RF_CHANNEL_HISTORY_POOL_COUNT];
	uint8_t meanPct[RF_CHANNEL_HISTORY_POOL_COUNT];
	uint8_t confidence[RF_CHANNEL_HISTORY_POOL_COUNT];
	uint8_t trials[RF_CHANNEL_HISTORY_POOL_COUNT];
	uint8_t penalty[RF_CHANNEL_HISTORY_POOL_COUNT];
	uint8_t recentOrder[RF_CHANNEL_HISTORY_POOL_COUNT];
	uint32_t crc32;
	uint32_t commit;
};
static_assert(sizeof(RfChannelJournalRecord) == 104u,
	      "channel journal record layout changed");
#define RF_CHANNEL_JOURNAL_RECORDS_PER_PAGE \
	(RF_CHANNEL_JOURNAL_PAGE_BYTES / sizeof(RfChannelJournalRecord))
#define RF_CHANNEL_JOURNAL_TOTAL_RECORDS \
	(RF_CHANNEL_JOURNAL_RECORDS_PER_PAGE * RF_CHANNEL_JOURNAL_PAGE_COUNT)

static uint32_t g_channelJournalSequence = 0;
static int16_t g_channelJournalLatestSlot = -1;
static int16_t g_channelJournalFreeSlot = -1;
static RfChannelJournalRecord g_channelJournalJob = {};
static int16_t g_channelJournalJobSlot = -1;
static uint8_t g_channelJournalJobWord = 0;
static bool g_channelJournalJobActive = false;
static uint32_t g_channelJournalJobGeneration = 0;
static uint32_t g_channelJournalLastWordUs = 0;
static uint32_t g_channelJournalNoLiveSinceMs = 0;
static bool g_channelJournalSoftDeviceChecked = false;
static bool g_channelJournalSoftDeviceEnabled = false;
static bool g_channelJournalLiveWriteUnsafe = false;

// Current-boot evidence. A historical score is a prior, never current proof.
static uint8_t
	g_channelHistoryRuntimeGoodStreak[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t
	g_channelHistoryRuntimeBadStreak[RF_CHANNEL_HISTORY_POOL_COUNT] = {};
static uint8_t g_channelHistoryResidenceChannel = 0xFFu;
static bool g_channelHistoryResidenceOutcomeRecorded = false;

#define RF_STARTUP_CHANNEL_READY_WINDOWS 5u
#define RF_STARTUP_CHANNEL_SETTLE_WINDOWS 2u
#define RF_STARTUP_CHANNEL_GOOD_SUCCESS_PERMILLE 800u

struct RfStartupChannelObservation {
	bool active;
	bool settledGood;
	uint8_t channel;
	uint8_t validWindows;
	uint8_t priorGoodChannel;
};

static bool g_startupWasUp[NSLOT] = {};
static RfStartupChannelObservation g_startupChannelObservation[NSLOT] = {};
static uint8_t g_startupLastGoodChannel[NSLOT] = {};

#define RF_STARTUP_CHANNEL_AUTO_PERSIST_MAX_WRITES_PER_BOOT 4u
static uint8_t g_startupPersistWrites = 0u;

static void
rfStartupChannelMaybePersist(const RfStartupChannelObservation &observation);

#define RF_CHANNEL_HANDOFF_QUIESCENT_MS 250u
#define RF_CHANNEL_HANDOFF_STICK_DEADZONE 2048
#define RF_CHANNEL_HANDOFF_TRIGGER_THRESHOLD 8u
#define RF_CHANNEL_HANDOFF_EARLY_SWITCH_MS 5u
#define RF_CHANNEL_HANDOFF_TARGET_OBSERVE_MS 1200u
#define RF_CHANNEL_HANDOFF_ROLLBACK_QUIET_MS 1000u
#define RF_CHANNEL_HANDOFF_ROLLBACK_ACQUIRE_MS 650u
#define RF_CHANNEL_HANDOFF_HOST_GRACE_MS 4000u
#define RF_E4_RESPONSE_WAIT_US 2500u
#define RF_E4_TIMING_CONTROL 0x50u

enum RfChannelHandoffState : uint8_t {
	RF_CH_IDLE = 0,
	RF_CH_HOP_PENDING = 1,
	RF_CH_QUIET_DWELL = 2,
	RF_CH_ACQUIRE = 3,
	RF_CH_ROLLBACK_QUIET_DWELL = 4,
	RF_CH_ROLLBACK_ACQUIRE = 5,
};

enum RfE4ResponseKind : uint8_t {
	RF_E4_RESP_NONE = 0,
	RF_E4_RESP_ZERO = 1,
	RF_E4_RESP_F1 = 2,
	RF_E4_RESP_OTHER = 3,
};

static uint8_t g_rfChHandoffState = RF_CH_IDLE;
static uint8_t g_rfChHandoffOld = 0;
static uint8_t g_rfChHandoffTarget = 0;
static uint8_t g_rfChHandoffMask = 0;
static unsigned long g_rfChHandoffStartedMs = 0;
static unsigned long g_rfChHandoffPhaseMs = 0;
static bool g_rfChHandoffRequireActivityCycle = true;
static uint32_t g_rfChHandoffReplyBaseline[NSLOT] = {};

// Decode-time activity latch. Updated from fresh 0x42/0x45/0x47 controller input.
static uint32_t g_rfHopInputSeq[NSLOT] = {};

// Fresh-neutral proof state. Silence/staleness is never equivalent to neutral.
#define RF_CHANNEL_HANDOFF_INPUT_REPORT_FRESH_MS 100u
static uint32_t g_rfHopInputReportSeq[NSLOT] = {};
static unsigned long g_rfHopInputLastReportMs[NSLOT] = {};

// One group coordinator handles every frozen live-controller cohort, including a cohort of one.
enum RfChannelGroupPhase : uint8_t {
	RF_GROUP_IDLE = 0,
	RF_GROUP_HOP_PENDING = 1,
	RF_GROUP_AUTHORIZED_WAIT_SWITCH = 2,
	RF_GROUP_TARGET_ACQUIRE = 3,
	RF_GROUP_PARTIAL_WAIT_ROLLBACK = 4,
	RF_GROUP_PARTIAL_ACQUIRE_OLD = 5,
	RF_GROUP_ROLLBACK_WAIT_SWITCH = 6,
	RF_GROUP_ROLLBACK_ACQUIRE_OLD = 7,
};

static bool g_rfChGroupActive = false;
static uint8_t g_rfChGroupPhase = RF_GROUP_IDLE;
static uint8_t g_rfChGroupParticipants = 0;
static uint8_t g_rfChGroupNeutralSeenMask = 0;
static bool g_rfChGroupSawActivitySincePending = false;
static bool g_rfChGroupNeutralStartValid = false;
static unsigned long g_rfChGroupNeutralStartMs = 0;
static uint32_t g_rfChGroupActivitySeqSeen[NSLOT] = {};
static uint32_t g_rfChGroupReportSeqSeen[NSLOT] = {};
static uint8_t g_rfHopInputLastMask[NSLOT] = {};

static void rfChannelNoteDecodedInput(int slot, uint32_t buttons);

uint16_t g_f1ps = 0;
uint16_t g_newps = 0;
// polls/s (GET+relay TXs) last second -- distinguishes loop-starvation from reply-loss
uint16_t g_pollsps = 0;
// last second's CRC-fail and no-reply-in-window counts (wedge diagnosis)
uint16_t g_crcps = 0, g_norxps = 0;
uint16_t g_rfStallRecover = 0;

// RF-stall self-heal thresholds. A genuine worst-case reply gap during normal play is ~1.5s (the
// hapticOnReconnect re-init window); past RF_STALL_MS with us still actively polling, the whole link is wedged,
// not merely blipping. RF_RECOVER_MS rate-limits the recovery so it can't thrash while a stalled link re-syncs.
#define RF_STALL_MS 2500u
#define RF_RECOVER_MS 2000u
// A genuinely WEDGED radio recovers within a power-cycle or two; a controller that is simply OFF / out of
// range never comes back no matter how many times we power-cycle. So after RF_STALL_GIVEUP consecutive
// recoveries that restored NO link, treat it as "controller absent" and stop hammering: back the power-cycle
// off to RF_STALL_BACKOFF_MS (a slow safety-net kick). Discovery beacons keep running throughout, so a
// returning controller still reconnects normally without the power-cycle -- and the aggressive 2s cadence was
// both wasteful and able to disrupt a controller mid-reconnect. The counter resets the moment any slot replies.
#define RF_STALL_GIVEUP 3u
#define RF_STALL_BACKOFF_MS 30000u
// measured avg us between GET-poll fires (vs intended g_pollUs)
uint16_t g_pollPeriodUs = 0;
static uint32_t g_pollDtSum = 0;
static uint16_t g_pollDtCnt = 0;
// smoothed |dBm| of the controller's replies, per slot (0 = none yet)
volatile uint8_t g_linkRssi[NSLOT] = { 0 };
// battery % from the controller's report 0x43 (body[1]); 0 = none yet. Per-slot -- the active controller's
// battery is the most recently seen one (other slots' values stay in their own array slots).
volatile uint8_t g_battery[NSLOT] = { 0 };
// charge state from report 0x43 body[0] (EChargeState: 1=discharging 2=charging 4=charging-done; 0=unknown).
volatile uint8_t g_batteryState[NSLOT] = { 0 };

// Slot the poll loop is currently driving. Set by rfConnStep before each E7/relay/E3, consumed by the
// decode (g_in[g_curSlot]), the haptic flush (per-slot session address), and the per-second stat dump.
int g_curSlot = -1;

// ---- internal counters / timers ----
// ESB PID is 2 bits. The controller dequeues a FRESH report only when the poll's PID differs from the
// last one it saw on that pipe; a repeated PID reads as a retransmit and returns the SAME (stale) report.
// PER SLOT, because a single shared counter advances by (2 * nWarm) per cycle -- with 2 controllers that's
// +4 per cycle = 0 mod 4, so each slot's GET PID is constant => the controller never dequeues => ~60 new/s
// instead of ~400. Each slot's counter increments once per poll-of-that-slot so it cycles 0,1,2,3 cleanly.
static uint8_t g_pollPid[NSLOT] = {};
// Relay PID is offset by 2 from poll PID so the two never share the same
// 2-bit PID value in the same cycle. Both counters advance once per cycle;
// starting 2 apart keeps them 2 apart (mod 4) forever, preventing the
// controller from deduplicating the E3 GET as a retransmit of the relay.
static uint8_t g_relayPid[NSLOT] = { 2, 2, 2, 2 };
// All link statistics are PER SLOT: each controller's polls/replies/errors are counted (and reported --
// serial stat line, WebUSB blob v13) against that controller only. The old scalar counters merged every
// slot into one number, so the panel couldn't tell "controller B is drowning" from "everything is slow".
// The legacy aggregate snapshots (g_pollsps & co) are now sums over slots, kept for the serial line and the
// blob's pre-v13 fields.
static uint32_t g_stPoll[NSLOT] = {}, g_stF1[NSLOT] = {};
static uint32_t g_stF3 = 0;
// g_stPoll counts true poll CYCLES (one E3 GET per warm slot per cycle). g_stRelay counts relay frames TX'd
// (host/haptic output reports). They were conflated before (every rfConnTx bumped one counter), which made
// "Polls/s" read ~540 (250 polls + ~290 relays) and hid that each relay steals a reply window from its poll.
static uint32_t g_stRelay[NSLOT] = {};
uint16_t g_relayps = 0;
// per-slot per-second snapshots (WebUSB blob v13 / per-controller panel stats)
uint16_t g_slotPollsps[NSLOT] = {}, g_slotF1ps[NSLOT] = {},
	 g_slotNewps[NSLOT] = {};
uint8_t g_slotCrcps[NSLOT] = {}, g_slotNoRxps[NSLOT] = {},
	g_slotRelayps[NSLOT] = {};
static unsigned long g_stMs = 0;
// Per-slot dedupe seq + per-slot new-report counter (the real puck sends 0x45 per controller; merging all
// slots into a single sequence makes one controller "swallow" the other's frame).
static uint8_t g_lastSeq[NSLOT] = { 0 };
static uint32_t g_stNew[NSLOT] = {};
static uint32_t g_stCrc[NSLOT] = {}, g_stNoRx[NSLOT] = {};
static uint32_t g_chF1[3] = { 0, 0, 0 };
// Cycle gate: fires once per g_pollUs; each fire polls every warm slot so all run at ~250 Hz (oversampling
// the controller's ~270 Hz report generation so no fresh trackpad sample is dropped -- see config.h).
static uint32_t g_lastPollUs = 0;
static uint32_t g_connRx = 0;
static unsigned long g_lastSessBeacon = 0, g_lastDisc = 0;
static unsigned long g_lastStream = 0;

// HOST FRAME the bonded controller waits for (IBEX FUN_00019000 verify: b[0]=0x12, b[5]=0xE1, b[6..10]=
// proteus_uuid, b[10..14]=ibex_uuid). Built like PROTEUS FUN_00027e9a. Sent on the shared rendezvous addr;
// the controller filters by the uuids in the payload, then connects.
// Transmit one host frame. `discovery`=true sends it on the SHARED rendezvous address ("ibex"/ch2) where a
// searching controller looks; =false sends it on this slot's unique SESSION address (the keepalive once the
// controller has adopted the session). EITHER way the payload advertises the session base/prefix/channel,
// so the controller always learns the unique address to connect on.

// Any-slot link helper: true if ANY bonded slot is currently hearing F-type replies (within 300 ms).
// Used for the "we're connected to at least one controller" decisions (beacon pacing, wake detect).
bool anySlotLinkUp()
{
	for (int s = 0; s < NSLOT; s++)
		if (g_slot[s].used && millis() - g_connReplyMs[s] < 300)
			return true;
	return false;
}

static void rfHostFrameOnce(int slot, bool discovery)
{
	if (slot < 0 || slot >= NSLOT || !g_slot[slot].used)
		return;
	// [proteus_uuid 4][ibex_uuid 4][serial 16]
	uint8_t *rec = g_slot[slot].rec;
	// CRC-VALIDATED frame (decoded from real puck): ESB-DPL RAM = [LENGTH][S1=PID][payload(18)]. payload:
	// [0]=0xE1, [1..5]=proteus_uuid LE, [5..9]=ibex_uuid LE, [9]=session channel, [10..13]=0, [13..17]=session
	// base, [17]=session prefix. Radio auto-appends CRC16 0x11021.
	memset(rftx, 0, sizeof rftx);
	// LENGTH = 18 (controller's buf[0]==0x12 check validates this)
	rftx[0] = 0x12;
	// S1 = PID<<1 | noack0  (matches real puck 00/02/04/06)
	rftx[1] = (uint8_t)((g_pid++ & 3) << 1);
	rftx[2] = 0xE1; // payload[0] marker
	// payload[1..5] proteus_uuid (LE, as bonded)
	memcpy(rftx + 3, rec + 0, 4);
	memcpy(rftx + 7, rec + 4, 4); // payload[5..9] ibex_uuid

	// payload[9] session channel: controller runs the session on this clean
	// channel (adopts buf[0xe]); discovery beacon still TXes on ch2
	rftx[11] = g_sessCh;
	// payload[13..17] session base  (the per-bond UNIQUE address; each controller adopts its own)
	memcpy(rftx + 15, g_sessBase[slot], 4);
	rftx[19] = g_sessPrefix[slot]; // payload[17] session prefix
	// TX address: discovery uses the shared "ibex" rendezvous; the session keepalive uses this slot's
	// unique address (where THIS controller now listens). The advertised session params (above) are
	// identical either way -- so the discovery frame can also double as a re-advertisement if needed.
	const uint8_t *txBase = discovery ? g_rfBase : g_sessBase[slot];
	uint8_t txPfx = discovery ? g_rfPrefix : g_sessPrefix[slot];
	rfConfig(g_rfCh);
	rfSetAddr(txBase, txPfx);
	NRF_RADIO->PACKETPTR = (uint32_t)rftx;
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_END_DISABLE_Msk;
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->TASKS_TXEN = 1;
	RWAIT_DISABLED();
	NRF_RADIO->EVENTS_DISABLED = 0;

	// Session keepalive: the controller answers E3 polls, not beacons.
	// No reply arrives here; radio is already disabled from the TX
	// END_DISABLE short, so skip the RX window entirely.
	if (!discovery)
		return;

	// Discovery/pairing beacons listen for the controller's response.
	NRF_RADIO->PACKETPTR = (uint32_t)rfrx;
	rfrx[0] = 0;
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk;
	NRF_RADIO->EVENTS_END = 0;
	NRF_RADIO->TASKS_RXEN = 1;
	uint32_t t0 = micros();
	while (!NRF_RADIO->EVENTS_END && (micros() - t0) < 800u) {
	}
	if (NRF_RADIO->EVENTS_END) {
		// any reception = controller answered our frame
		NRF_RADIO->EVENTS_END = 0;
		g_rfRxCount++;
		bool crcok = NRF_RADIO->CRCSTATUS & 1;
		uint8_t len = rfrx[0];
		// non-blocking: don't stall the loop on CDC backpressure (whole line ~165B; CDC write() has no timeout)
		if (Serial.availableForWrite() > 180) {
			Serial.printf(
				"*** RESP#%lu ch%u crc%d rxmatch%lu len%u: ",
				(unsigned long)g_rfRxCount, g_rfCh, crcok,
				(unsigned long)NRF_RADIO->RXMATCH, len);
			for (uint8_t i = 0; i < (len < 40 ? len + 2 : 40); i++)
				Serial.printf("%02X ", rfrx[i]);
			Serial.println();
		}
	}
	NRF_RADIO->TASKS_DISABLE = 1;
	RWAIT_DISABLED();
	NRF_RADIO->EVENTS_DISABLED = 0;
}

static uint8_t rfChannelLiveMask(unsigned long now)
{
	uint8_t mask = 0;
	for (uint8_t s = 0; s < NSLOT; s++) {
		if (!g_slot[s].used || !g_connReplyMs[s])
			continue;
		if ((uint32_t)(now - g_connReplyMs[s]) < 1200u)
			mask |= (uint8_t)(1u << s);
	}
	return mask;
}

static int rfChannelMaskSlot(uint8_t mask)
{
	for (int s = 0; s < NSLOT; s++)
		if (mask & (uint8_t)(1u << s))
			return s;
	return -1;
}

static void rfLinkQualityResetWindow(int slot)
{
	if (slot < 0 || slot >= NSLOT)
		return;
	g_linkQualityPolls[slot] = 0;
	g_linkQualityReplies[slot] = 0;
}

static void rfLinkQualityNotePoll(int slot, bool reply)
{
	if (slot < 0 || slot >= NSLOT)
		return;
	g_linkQualityPolls[slot]++;
	if (reply)
		g_linkQualityReplies[slot]++;
}

static bool rfChannelRecoverySetTarget(uint8_t ch)
{
	if (ch != 0u && (ch < 4u || ch > 80u || (ch & 1u)))
		return false;
	if (g_recoveryTargetChannel != ch) {
		g_recoveryTargetChannel = ch;
		g_recoveryResidenceChannel = g_sessCh;
		g_recoveryRequestedThisResidence = false;
	}
	return true;
}

static void rfChannelRecoverySyncResidence()
{
	if (g_recoveryResidenceChannel == g_sessCh)
		return;
	g_recoveryResidenceChannel = g_sessCh;
	g_recoveryRequestedThisResidence = false;
}

static int rfRecoveryChannelIndex(uint8_t ch)
{
	if (ch < RF_RECOVERY_CHANNEL_MIN || ch > RF_RECOVERY_CHANNEL_MAX ||
	    (ch & 1u))
		return -1;
	return (int)((ch - RF_RECOVERY_CHANNEL_MIN) >> 1);
}

static void rfStartupChannelBeginObservation(int slot)
{
	RfStartupChannelObservation &observation =
		g_startupChannelObservation[slot];
	memset(&observation, 0, sizeof observation);
	observation.active = true;
	observation.settledGood = true;
	observation.channel = g_sessCh;
	observation.priorGoodChannel = g_startupLastGoodChannel[slot];
}

static void rfStartupChannelTask()
{
	const unsigned long now = millis();
	for (int slot = 0; slot < NSLOT; slot++) {
		const bool up = g_slot[slot].used &&
				g_connReplyMs[slot] != 0u &&
				(uint32_t)(now - g_connReplyMs[slot]) < 300u;
		if (up && !g_startupWasUp[slot])
			rfStartupChannelBeginObservation(slot);
		if (!up && g_startupWasUp[slot])
			g_startupChannelObservation[slot].active = false;
		g_startupWasUp[slot] = up;
	}
}

static void rfStartupChannelObserveWindow(int slot, uint16_t successPermille,
					  bool valid)
{
	if (!valid || slot < 0 || slot >= NSLOT)
		return;
	RfStartupChannelObservation &observation =
		g_startupChannelObservation[slot];
	if (!observation.active || observation.channel != g_sessCh ||
	    observation.validWindows >= RF_STARTUP_CHANNEL_READY_WINDOWS)
		return;

	observation.validWindows++;
	if (observation.validWindows > RF_STARTUP_CHANNEL_SETTLE_WINDOWS &&
	    successPermille < RF_STARTUP_CHANNEL_GOOD_SUCCESS_PERMILLE)
		observation.settledGood = false;

	if (observation.validWindows != RF_STARTUP_CHANNEL_READY_WINDOWS)
		return;

	if (observation.settledGood)
		g_startupLastGoodChannel[slot] = observation.channel;
	rfStartupChannelMaybePersist(observation);
}

static void
rfStartupChannelMaybePersist(const RfStartupChannelObservation &observation)
{
	if (!observation.settledGood ||
	    observation.priorGoodChannel != observation.channel ||
	    g_rfStartupLastGoodChannel == observation.channel ||
	    g_startupPersistWrites >=
		    RF_STARTUP_CHANNEL_AUTO_PERSIST_MAX_WRITES_PER_BOOT)
		return;

	if (saveRfStartupLastGoodChannel(observation.channel))
		g_startupPersistWrites++;
}

static void rfChannelRecoveryRequest(bool wouldPending)
{
	rfChannelRecoverySyncResidence();
	if (!wouldPending || g_recoveryRequestedThisResidence)
		return;
	if (g_recoveryTargetChannel == 0u ||
	    g_recoveryTargetChannel == g_sessCh)
		return;
	if (g_rfChHandoffState != RF_CH_IDLE)
		return;

	// Allow one autonomous request per channel residence. Set the latch before
	// rfHopTo() so a failed stay-old result cannot hammer requests.
	g_recoveryRequestedThisResidence = true;
	// A recovery request requires a new decode-latched activity event followed
	// by at least 250 ms neutral before any E4 authorization attempt.
	rfHopTo(g_recoveryTargetChannel);
}

static int rfChannelHistoryPoolIndex(uint8_t ch)
{
	for (uint8_t i = 0; i < RF_CHANNEL_HISTORY_POOL_COUNT; i++)
		if (g_recoveryChannelPool[i] == ch)
			return (int)i;
	return -1;
}

static uint8_t rfAmbientMeasureChannel(uint8_t ch, uint16_t sampleUs)
{
	const uint8_t restoreCh = g_rfCh;
	rfConfig(ch);
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk;
	NRF_RADIO->EVENTS_READY = 0;
	NRF_RADIO->EVENTS_RSSIEND = 0;
	NRF_RADIO->TASKS_RXEN = 1;
	const uint32_t readyUs = micros();
	while (!NRF_RADIO->EVENTS_READY &&
	       (uint32_t)(micros() - readyUs) < 1000u) {
	}
	if (!NRF_RADIO->EVENTS_READY) {
		NRF_RADIO->TASKS_DISABLE = 1;
		RWAIT_DISABLED();
		NRF_RADIO->EVENTS_DISABLED = 0;
		NRF_RADIO->SHORTS = 0;
		rfConfig(restoreCh);
		return 0;
	}

	uint8_t strongest = 0;
	const uint32_t startUs = micros();
	do {
		NRF_RADIO->EVENTS_RSSIEND = 0;
		NRF_RADIO->TASKS_RSSISTART = 1;
		const uint32_t sampleStartUs = micros();
		while (!NRF_RADIO->EVENTS_RSSIEND &&
		       (uint32_t)(micros() - sampleStartUs) < 200u) {
		}
		if (NRF_RADIO->EVENTS_RSSIEND) {
			const uint8_t sample =
				(uint8_t)(NRF_RADIO->RSSISAMPLE & 0x7Fu);
			if (sample && (!strongest || sample < strongest))
				strongest = sample;
		}
		delayMicroseconds(80);
	} while ((uint32_t)(micros() - startUs) < sampleUs);

	NRF_RADIO->TASKS_DISABLE = 1;
	RWAIT_DISABLED();
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->SHORTS = 0;
	rfConfig(restoreCh);
	return strongest;
}

void rfRecoveryRequestAmbientSurvey()
{
	g_ambientSurveyPending = true;
}

static void rfAmbientSurveyAbort()
{
	g_ambientSurveyRunning = false;
	g_ambientSurveyIndex = 0;
	g_ambientSurveyPass = 0;
	memset(g_ambientWorkRssi, 0, sizeof g_ambientWorkRssi);
	memset(g_ambientWorkSamples, 0, sizeof g_ambientWorkSamples);
}

static void rfAmbientSurveyBegin(unsigned long now)
{
	memset(g_ambientWorkRssi, 0, sizeof g_ambientWorkRssi);
	memset(g_ambientWorkSamples, 0, sizeof g_ambientWorkSamples);
	g_ambientSurveyIndex = 0;
	g_ambientSurveyPass = 0;
	g_ambientSurveyLastStepMs = now - RF_AMBIENT_SURVEY_STEP_MS;
	g_ambientSurveyRunning = true;
	g_ambientSurveyPending = false;
}

static bool rfAmbientSurveyComplete()
{
	for (uint8_t i = 0; i < RF_CHANNEL_HISTORY_POOL_COUNT; i++)
		if (!g_ambientWorkSamples[i])
			return false;
	return true;
}

static void rfAmbientSurveyTask()
{
	const unsigned long now = millis();
	const bool live = rfChannelLiveMask(now) != 0u;
	const bool handoff = g_rfChHandoffState != RF_CH_IDLE ||
			     g_rfChGroupActive;
	if (live || handoff) {
		g_ambientSurveyIdleSinceMs = 0;
		if (g_ambientSurveyRunning)
			rfAmbientSurveyAbort();
		return;
	}
	if (!g_ambientSurveyIdleSinceMs)
		g_ambientSurveyIdleSinceMs = now;
	if ((uint32_t)(now - g_ambientSurveyIdleSinceMs) <
	    RF_AMBIENT_SURVEY_IDLE_GUARD_MS)
		return;

	const bool stale = !g_ambientStableValid ||
			   (uint32_t)(now - g_ambientSurveyLastCompleteMs) >=
				   RF_AMBIENT_SURVEY_REFRESH_MS;
	if (!g_ambientSurveyRunning) {
		if (!g_ambientSurveyPending && !stale)
			return;
		rfAmbientSurveyBegin(now);
	}
	if ((uint32_t)(now - g_ambientSurveyLastStepMs) <
	    RF_AMBIENT_SURVEY_STEP_MS)
		return;
	g_ambientSurveyLastStepMs = now;

	const uint8_t i = g_ambientSurveyIndex;
	const uint8_t sample = rfAmbientMeasureChannel(
		g_recoveryChannelPool[i], RF_AMBIENT_SURVEY_SAMPLE_US);
	if (sample) {
		if (!g_ambientWorkRssi[i] || sample < g_ambientWorkRssi[i])
			g_ambientWorkRssi[i] = sample;
		if (g_ambientWorkSamples[i] != 0xFFu)
			g_ambientWorkSamples[i]++;
	}
	if (++g_ambientSurveyIndex >= RF_CHANNEL_HISTORY_POOL_COUNT) {
		g_ambientSurveyIndex = 0;
		g_ambientSurveyPass++;
	}
	if (g_ambientSurveyPass < RF_AMBIENT_SURVEY_PASSES)
		return;

	if (rfAmbientSurveyComplete()) {
		memcpy(g_ambientStableRssi, g_ambientWorkRssi,
		       sizeof g_ambientStableRssi);
		g_ambientStableValid = true;
		g_ambientSurveyGeneration++;
		g_ambientSurveyLastCompleteMs = now;
	}
	rfAmbientSurveyAbort();
}

static uint8_t rfChannelHistoryDesignation(uint8_t index)
{
	if (index >= RF_CHANNEL_HISTORY_POOL_COUNT ||
	    !g_channelHistoryPersistentTrials[index])
		return RF_CHANNEL_UNEXPLORED;
	if (g_channelHistoryPersistentWorstPct[index] >= 80u &&
	    g_channelHistoryPersistentConfidence[index] >
		    g_channelHistoryPersistentPenalty[index])
		return RF_CHANNEL_GOOD;
	if (g_channelHistoryPersistentWorstPct[index] < 55u ||
	    g_channelHistoryPersistentPenalty[index] >
		    g_channelHistoryPersistentConfidence[index])
		return RF_CHANNEL_POOR;
	return RF_CHANNEL_MIXED;
}

static uint8_t rfChannelHistorySelectGoodPrior(uint8_t current)
{
	uint8_t best = 0;
	for (uint8_t i = 0; i < RF_CHANNEL_HISTORY_POOL_COUNT; i++) {
		const uint8_t ch = g_recoveryChannelPool[i];
		if (ch == current ||
		    rfChannelHistoryDesignation(i) != RF_CHANNEL_GOOD)
			continue;
		if (!best) {
			best = ch;
			continue;
		}
		const int bi = rfChannelHistoryPoolIndex(best);
		if (g_channelHistoryPersistentWorstPct[i] >
			    g_channelHistoryPersistentWorstPct[bi] ||
		    (g_channelHistoryPersistentWorstPct[i] ==
			     g_channelHistoryPersistentWorstPct[bi] &&
		     g_channelHistoryPersistentMeanPct[i] >
			     g_channelHistoryPersistentMeanPct[bi]) ||
		    (g_channelHistoryPersistentWorstPct[i] ==
			     g_channelHistoryPersistentWorstPct[bi] &&
		     g_channelHistoryPersistentMeanPct[i] ==
			     g_channelHistoryPersistentMeanPct[bi] &&
		     g_channelHistoryPersistentConfidence[i] >
			     g_channelHistoryPersistentConfidence[bi]))
			best = ch;
	}
	return best;
}

static uint8_t rfChannelHistorySelectUnexplored(uint8_t current)
{
	int best = -1;
	for (uint8_t step = 0; step < RF_CHANNEL_HISTORY_POOL_COUNT; step++) {
		const uint8_t i = (uint8_t)((g_hopIdx + step) %
					    RF_CHANNEL_HISTORY_POOL_COUNT);
		if (g_recoveryChannelPool[i] == current ||
		    g_channelHistoryPersistentTrials[i])
			continue;
		if (best < 0 ||
		    (g_ambientStableValid && g_ambientStableRssi[i] &&
		     (!g_ambientStableRssi[best] ||
		      g_ambientStableRssi[i] > g_ambientStableRssi[best])))
			best = i;
	}
	if (best < 0)
		return 0;
	g_hopIdx = (uint8_t)((best + 1) % RF_CHANNEL_HISTORY_POOL_COUNT);
	return g_recoveryChannelPool[best];
}

static uint8_t
rfChannelHistorySelectBestRemaining(uint8_t current,
				    uint16_t currentWorstPermille)
{
	int best = -1;
	for (uint8_t i = 0; i < RF_CHANNEL_HISTORY_POOL_COUNT; i++) {
		if (g_recoveryChannelPool[i] == current ||
		    !g_channelHistoryPersistentTrials[i])
			continue;
		const uint16_t priorWorst =
			(uint16_t)g_channelHistoryPersistentWorstPct[i] * 10u;
		if (priorWorst <
		    (uint16_t)(currentWorstPermille +
			       RF_CHANNEL_RECOVERY_MIN_IMPROVEMENT_PERMILLE))
			continue;
		if (best < 0 ||
		    g_channelHistoryPersistentWorstPct[i] >
			    g_channelHistoryPersistentWorstPct[best] ||
		    (g_channelHistoryPersistentWorstPct[i] ==
			     g_channelHistoryPersistentWorstPct[best] &&
		     g_channelHistoryPersistentPenalty[i] <
			     g_channelHistoryPersistentPenalty[best]))
			best = i;
	}
	return best < 0 ? 0 : g_recoveryChannelPool[best];
}

void rfRecoveryStatusSnapshot(RfRecoveryStatus *status)
{
	if (!status)
		return;
	memset(status, 0, sizeof *status);
	status->version = 1;
	if (g_ambientSurveyRunning)
		status->flags |= 0x01u;
	if (g_ambientSurveyPending)
		status->flags |= 0x02u;
	if (g_ambientStableValid)
		status->flags |= 0x04u;
	if (rfChannelLiveMask(millis()))
		status->flags |= 0x08u;
	if (g_rfChHandoffState != RF_CH_IDLE || g_rfChGroupActive)
		status->flags |= 0x10u;
	if (g_channelHistoryPersistentLoaded)
		status->flags |= 0x20u;
	if (g_channelHistoryPersistentDirty)
		status->flags |= 0x40u;
	if (g_channelJournalLiveWriteUnsafe)
		status->flags |= 0x80u;
	status->currentChannel = g_sessCh;
	status->targetChannel = g_recoveryTargetChannel;
	status->startupChannel =
		g_rfStartupLastGoodChannel ? g_rfStartupLastGoodChannel : 18u;
	status->channelCount = RF_CHANNEL_HISTORY_POOL_COUNT;
	status->journalWrites = g_channelHistoryPersistentWrites;
	status->ambientGeneration = g_ambientSurveyGeneration;
	status->journalSequence = g_channelJournalSequence;
	for (uint8_t i = 0; i < RF_CHANNEL_HISTORY_POOL_COUNT; i++) {
		RfChannelStatusEntry &entry = status->channel[i];
		entry.channel = g_recoveryChannelPool[i];
		entry.ambientRssi =
			g_ambientStableValid ? g_ambientStableRssi[i] : 0u;
		entry.designation = rfChannelHistoryDesignation(i);
		entry.worstPct = g_channelHistoryPersistentWorstPct[i];
		entry.meanPct = g_channelHistoryPersistentMeanPct[i];
		entry.confidence = g_channelHistoryPersistentConfidence[i];
		entry.trials = g_channelHistoryPersistentTrials[i];
		entry.penalty = g_channelHistoryPersistentPenalty[i];
		entry.recentOrder = g_channelHistoryPersistentRecentOrder[i];
	}
}

static uint32_t rfChannelJournalCrc32(const void *data, size_t len)
{
	const uint8_t *p = (const uint8_t *)data;
	uint32_t crc = 0xFFFFFFFFu;
	while (len--) {
		crc ^= *p++;
		for (uint8_t i = 0; i < 8u; i++)
			crc = (crc >> 1) ^
			      (0xEDB88320u & (uint32_t) - (int32_t)(crc & 1u));
	}
	return ~crc;
}

static uintptr_t rfChannelJournalBase()
{
	return (uintptr_t)&g_channelJournalFlash[0];
}

static uintptr_t rfChannelJournalSlotAddress(uint16_t slot)
{
	const uint16_t page = slot / RF_CHANNEL_JOURNAL_RECORDS_PER_PAGE;
	const uint16_t inPage = slot % RF_CHANNEL_JOURNAL_RECORDS_PER_PAGE;
	return rfChannelJournalBase() +
	       (uintptr_t)page * RF_CHANNEL_JOURNAL_PAGE_BYTES +
	       (uintptr_t)inPage * sizeof(RfChannelJournalRecord);
}

static bool rfChannelJournalSequenceNewer(uint32_t a, uint32_t b)
{
	return (int32_t)(a - b) > 0;
}

static bool rfChannelJournalSlotErased(uint16_t slot)
{
	const volatile uint32_t *p =
		(const volatile uint32_t *)rfChannelJournalSlotAddress(slot);
	for (uint8_t i = 0; i < sizeof(RfChannelJournalRecord) / 4u; i++)
		if (p[i] != 0xFFFFFFFFu)
			return false;
	return true;
}

static bool rfChannelJournalReadValid(uint16_t slot,
				      RfChannelJournalRecord *out)
{
	if (!out)
		return false;
	memcpy(out, (const void *)rfChannelJournalSlotAddress(slot),
	       sizeof *out);
	if (out->magic != RF_CHANNEL_JOURNAL_MAGIC ||
	    out->commit != RF_CHANNEL_JOURNAL_COMMIT ||
	    out->format != RF_CHANNEL_JOURNAL_FORMAT ||
	    out->poolCount != RF_CHANNEL_HISTORY_POOL_COUNT)
		return false;
	return out->crc32 ==
	       rfChannelJournalCrc32(out,
				     offsetof(RfChannelJournalRecord, crc32));
}

static void rfChannelJournalCheckSoftDevice()
{
	if (g_channelJournalSoftDeviceChecked)
		return;
	g_channelJournalSoftDeviceChecked = true;
	uint8_t enabled = 0;
	if (sd_softdevice_is_enabled(&enabled) != NRF_SUCCESS)
		enabled = 1;
	g_channelJournalSoftDeviceEnabled = enabled != 0;
}

static bool rfChannelJournalTimerReady()
{
	// TIMER3 is the hardware-validated 16-MHz RF timing substrate retained from
	// Channel-history flash timing borrows only unused CC[5]; CC[0..4] and PPI13..16 remain
	// untouched. Never initialize/reconfigure the timer here: if the retained
	// timing substrate is unavailable, live persistence fails closed to offline.
	return NRF_TIMER3->MODE ==
		       (TIMER_MODE_MODE_Timer << TIMER_MODE_MODE_Pos) &&
	       NRF_TIMER3->BITMODE == (TIMER_BITMODE_BITMODE_32Bit
				       << TIMER_BITMODE_BITMODE_Pos) &&
	       NRF_TIMER3->PRESCALER == 0u;
}

static bool rfChannelJournalCaptureTicks(uint32_t *ticks)
{
	if (!ticks || !rfChannelJournalTimerReady())
		return false;
	NRF_TIMER3->TASKS_CAPTURE[5] = 1;
	*ticks = NRF_TIMER3->CC[5];
	return true;
}

static bool rfChannelJournalProgramWord(uintptr_t address, uint32_t value,
					uint32_t *durationUs,
					bool *durationValid)
{
	rfChannelJournalCheckSoftDevice();
	if (durationUs)
		*durationUs = 0;
	if (durationValid)
		*durationValid = false;
	if (g_channelJournalSoftDeviceEnabled || (address & 3u) != 0u ||
	    *(const volatile uint32_t *)address != 0xFFFFFFFFu)
		return false;

	uint32_t t0Ticks = 0;
	const bool haveHiRes = rfChannelJournalCaptureTicks(&t0Ticks);
	const uint32_t primask = __get_PRIMASK();
	__disable_irq();
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Wen;
	while (!NRF_NVMC->READY) {
	}
	*(volatile uint32_t *)address = value;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {
	}
	uint32_t t1Ticks = 0;
	const bool haveHiResEnd = haveHiRes &&
				  rfChannelJournalCaptureTicks(&t1Ticks);
	if (!primask)
		__enable_irq();

	if (haveHiResEnd) {
		const uint32_t dtTicks = (uint32_t)(t1Ticks - t0Ticks);
		const uint32_t dtUs =
			(dtTicks + RF_CHANNEL_JOURNAL_TIMER3_TICKS_PER_US -
			 1u) /
			RF_CHANNEL_JOURNAL_TIMER3_TICKS_PER_US;
		if (durationUs)
			*durationUs = dtUs;
		if (durationValid)
			*durationValid = true;
	}
	return *(const volatile uint32_t *)address == value;
}

static bool rfChannelJournalErasePage(uint8_t page)
{
	rfChannelJournalCheckSoftDevice();
	if (g_channelJournalSoftDeviceEnabled ||
	    page >= RF_CHANNEL_JOURNAL_PAGE_COUNT)
		return false;
	const uintptr_t address =
		rfChannelJournalBase() +
		(uintptr_t)page * RF_CHANNEL_JOURNAL_PAGE_BYTES;
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Een;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->ERASEPAGE = (uint32_t)address;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {
	}
	const volatile uint32_t *p = (const volatile uint32_t *)address;
	for (uint16_t i = 0; i < RF_CHANNEL_JOURNAL_PAGE_BYTES / 4u; i++)
		if (p[i] != 0xFFFFFFFFu)
			return false;
	return true;
}

static int16_t rfChannelJournalFindFreeSlot()
{
	for (uint16_t slot = 0; slot < RF_CHANNEL_JOURNAL_TOTAL_RECORDS; slot++)
		if (rfChannelJournalSlotErased(slot))
			return (int16_t)slot;
	return -1;
}

static void rfChannelJournalLoad()
{
	if (g_channelHistoryPersistentLoaded)
		return;
	g_channelHistoryPersistentLoaded = true;
	rfChannelJournalCheckSoftDevice();
	const uintptr_t base = rfChannelJournalBase();
	if ((base & (RF_CHANNEL_JOURNAL_PAGE_BYTES - 1u)) != 0u ||
	    sizeof g_channelJournalFlash !=
		    RF_CHANNEL_JOURNAL_PAGE_BYTES *
			    RF_CHANNEL_JOURNAL_PAGE_COUNT) {
		g_channelJournalLiveWriteUnsafe = true;
		return;
	}
	RfChannelJournalRecord latest = {};
	bool haveLatest = false;
	for (uint16_t slot = 0; slot < RF_CHANNEL_JOURNAL_TOTAL_RECORDS;
	     slot++) {
		RfChannelJournalRecord rec = {};
		if (!rfChannelJournalReadValid(slot, &rec))
			continue;
		if (!haveLatest || rfChannelJournalSequenceNewer(
					   rec.sequence, latest.sequence)) {
			latest = rec;
			g_channelJournalLatestSlot = (int16_t)slot;
			haveLatest = true;
		}
	}
	if (haveLatest) {
		memcpy(g_channelHistoryPersistentWorstPct, latest.worstPct,
		       sizeof g_channelHistoryPersistentWorstPct);
		memcpy(g_channelHistoryPersistentMeanPct, latest.meanPct,
		       sizeof g_channelHistoryPersistentMeanPct);
		memcpy(g_channelHistoryPersistentConfidence, latest.confidence,
		       sizeof g_channelHistoryPersistentConfidence);
		memcpy(g_channelHistoryPersistentTrials, latest.trials,
		       sizeof g_channelHistoryPersistentTrials);
		memcpy(g_channelHistoryPersistentPenalty, latest.penalty,
		       sizeof g_channelHistoryPersistentPenalty);
		memcpy(g_channelHistoryPersistentRecentOrder,
		       latest.recentOrder,
		       sizeof g_channelHistoryPersistentRecentOrder);
		g_channelHistoryPersistentOrderCounter = latest.orderCounter;
		g_channelJournalSequence = latest.sequence;
	}
	g_channelJournalFreeSlot = rfChannelJournalFindFreeSlot();
}

static void rfChannelJournalBuildRecord(RfChannelJournalRecord *rec)
{
	memset(rec, 0, sizeof *rec);
	rec->magic = RF_CHANNEL_JOURNAL_MAGIC;
	rec->sequence = g_channelJournalSequence + 1u;
	rec->format = RF_CHANNEL_JOURNAL_FORMAT;
	rec->poolCount = RF_CHANNEL_HISTORY_POOL_COUNT;
	rec->orderCounter = g_channelHistoryPersistentOrderCounter;
	memcpy(rec->worstPct, g_channelHistoryPersistentWorstPct,
	       sizeof rec->worstPct);
	memcpy(rec->meanPct, g_channelHistoryPersistentMeanPct,
	       sizeof rec->meanPct);
	memcpy(rec->confidence, g_channelHistoryPersistentConfidence,
	       sizeof rec->confidence);
	memcpy(rec->trials, g_channelHistoryPersistentTrials,
	       sizeof rec->trials);
	memcpy(rec->penalty, g_channelHistoryPersistentPenalty,
	       sizeof rec->penalty);
	memcpy(rec->recentOrder, g_channelHistoryPersistentRecentOrder,
	       sizeof rec->recentOrder);
	rec->crc32 = rfChannelJournalCrc32(rec, offsetof(RfChannelJournalRecord,
							 crc32));
	rec->commit = RF_CHANNEL_JOURNAL_COMMIT;
}

static bool rfChannelJournalStartWrite()
{
	if (g_channelJournalJobActive || g_channelJournalFreeSlot < 0)
		return false;
	rfChannelJournalBuildRecord(&g_channelJournalJob);
	g_channelJournalJobSlot = g_channelJournalFreeSlot;
	g_channelJournalJobWord = 0;
	g_channelJournalJobGeneration = g_channelHistoryPersistentGeneration;
	g_channelJournalLastWordUs = 0;
	g_channelJournalJobActive = true;
	return true;
}

static void rfChannelJournalFinishWrite(uint32_t now)
{
	RfChannelJournalRecord verify = {};
	const bool valid =
		rfChannelJournalReadValid((uint16_t)g_channelJournalJobSlot,
					  &verify) &&
		verify.sequence == g_channelJournalJob.sequence;
	if (!valid) {
		g_channelJournalJobActive = false;
		g_channelJournalFreeSlot = rfChannelJournalFindFreeSlot();
		return;
	}
	g_channelJournalSequence = verify.sequence;
	g_channelJournalLatestSlot = g_channelJournalJobSlot;
	g_channelHistoryPersistentWrites++;
	g_channelHistoryPersistentLastWriteMs = now;
	if (g_channelHistoryPersistentGeneration ==
	    g_channelJournalJobGeneration)
		g_channelHistoryPersistentDirty = false;
	g_channelJournalJobActive = false;
	g_channelJournalFreeSlot = rfChannelJournalFindFreeSlot();
}

static void rfChannelJournalStep(uint32_t now, uint8_t liveMask)
{
	if (!g_channelJournalJobActive || g_rfChHandoffState != RF_CH_IDLE ||
	    g_rfChGroupActive)
		return;
	const bool live = liveMask != 0u;
	if (live && (g_channelJournalLiveWriteUnsafe ||
		     g_channelJournalSoftDeviceEnabled))
		return;
	const uint32_t us = micros();
	if (g_channelJournalLastWordUs &&
	    (uint32_t)(us - g_channelJournalLastWordUs) <
		    RF_CHANNEL_JOURNAL_WORD_INTERVAL_US)
		return;
	const uint8_t words = sizeof(RfChannelJournalRecord) / 4u;
	if (g_channelJournalJobWord >= words)
		return;
	const uint8_t word = g_channelJournalJobWord;
	// Commit is the last 32-bit word by construction. Sequential programming
	// therefore makes every partial/power-loss record invalid at boot.
	const uint32_t value = ((const uint32_t *)&g_channelJournalJob)[word];
	const uintptr_t address =
		rfChannelJournalSlotAddress((uint16_t)g_channelJournalJobSlot) +
		(uintptr_t)word * 4u;
	uint32_t durationUs = 0;
	bool durationValid = false;
	if (!rfChannelJournalProgramWord(address, value, &durationUs,
					 &durationValid)) {
		g_channelJournalJobActive = false;
		g_channelJournalFreeSlot = rfChannelJournalFindFreeSlot();
		return;
	}
	g_channelJournalLastWordUs = us;
	if (live && !durationValid)
		g_channelJournalLiveWriteUnsafe = true;
	else if (live && durationUs > RF_CHANNEL_JOURNAL_LIVE_WORD_MAX_US)
		g_channelJournalLiveWriteUnsafe = true;
	g_channelJournalJobWord++;
	if (g_channelJournalJobWord >= words)
		rfChannelJournalFinishWrite(now);
}

static bool rfChannelJournalMaybeCollect(uint32_t now, uint8_t liveMask)
{
	if (g_channelJournalFreeSlot >= 0)
		return true;
	if (liveMask || g_rfChHandoffState != RF_CH_IDLE || g_rfChGroupActive) {
		g_channelJournalNoLiveSinceMs = 0;
		return false;
	}
	if (!g_channelJournalNoLiveSinceMs) {
		g_channelJournalNoLiveSinceMs = now;
		return false;
	}
	if ((uint32_t)(now - g_channelJournalNoLiveSinceMs) <
	    RF_CHANNEL_JOURNAL_OFFLINE_GUARD_MS)
		return false;
	uint8_t keepPage = 0xFFu;
	if (g_channelJournalLatestSlot >= 0)
		keepPage = (uint8_t)g_channelJournalLatestSlot /
			   RF_CHANNEL_JOURNAL_RECORDS_PER_PAGE;
	const uint8_t erasePage = keepPage == 0u ? 1u : 0u;
	if (!rfChannelJournalErasePage(erasePage))
		return false;
	g_channelJournalFreeSlot = rfChannelJournalFindFreeSlot();
	g_channelJournalNoLiveSinceMs = now;
	return g_channelJournalFreeSlot >= 0;
}

static void rfChannelHistoryEnsureLoaded()
{
	rfChannelJournalLoad();
}

static void rfChannelHistorySyncResidence()
{
	if (g_channelHistoryResidenceChannel == g_sessCh)
		return;
	g_channelHistoryResidenceChannel = g_sessCh;
	g_channelHistoryResidenceOutcomeRecorded = false;
}

static void rfChannelHistoryRecordPersistentOutcome(uint8_t ch,
						    uint16_t worstPermille,
						    uint16_t meanPermille,
						    bool good)
{
	rfChannelHistoryEnsureLoaded();
	rfChannelHistorySyncResidence();
	if (g_channelHistoryResidenceOutcomeRecorded)
		return;
	const int idx = rfChannelHistoryPoolIndex(ch);
	if (idx < 0)
		return;
	g_channelHistoryResidenceOutcomeRecorded = true;
	const uint8_t worstPct =
		(uint8_t)(worstPermille > 1000u ? 100u : worstPermille / 10u);
	const uint8_t meanPct =
		(uint8_t)(meanPermille > 1000u ? 100u : meanPermille / 10u);
	if (!g_channelHistoryPersistentTrials[idx]) {
		g_channelHistoryPersistentWorstPct[idx] = worstPct;
		g_channelHistoryPersistentMeanPct[idx] = meanPct;
	} else if (good) {
		g_channelHistoryPersistentWorstPct[idx] =
			(uint8_t)(((uint16_t)g_channelHistoryPersistentWorstPct
						   [idx] *
					   3u +
				   worstPct) /
				  4u);
		g_channelHistoryPersistentMeanPct[idx] =
			(uint8_t)(((uint16_t)g_channelHistoryPersistentMeanPct
						   [idx] *
					   3u +
				   meanPct) /
				  4u);
	} else {
		// Bad current evidence must demote stale historical greatness quickly.
		g_channelHistoryPersistentWorstPct[idx] =
			(uint8_t)(((uint16_t)g_channelHistoryPersistentWorstPct
					   [idx] +
				   worstPct) /
				  2u);
		g_channelHistoryPersistentMeanPct[idx] =
			(uint8_t)(((uint16_t)
					   g_channelHistoryPersistentMeanPct[idx] +
				   meanPct) /
				  2u);
	}
	if (g_channelHistoryPersistentTrials[idx] != 0xFFu)
		g_channelHistoryPersistentTrials[idx]++;
	if (good) {
		if (g_channelHistoryPersistentConfidence[idx] < 15u)
			g_channelHistoryPersistentConfidence[idx]++;
		if (g_channelHistoryPersistentPenalty[idx])
			g_channelHistoryPersistentPenalty[idx]--;
	} else {
		if (g_channelHistoryPersistentConfidence[idx])
			g_channelHistoryPersistentConfidence[idx]--;
		if (g_channelHistoryPersistentPenalty[idx] < 10u)
			g_channelHistoryPersistentPenalty[idx] += 2u;
	}
	g_channelHistoryPersistentOrderCounter++;
	g_channelHistoryPersistentRecentOrder[idx] =
		g_channelHistoryPersistentOrderCounter;
	g_channelHistoryPersistentDirty = true;
	g_channelHistoryPersistentGeneration++;
}

static void rfChannelHistoryObserve(uint8_t ch, uint16_t worstPermille,
				    uint16_t meanPermille, bool valid)
{
	rfChannelHistoryEnsureLoaded();
	rfChannelHistorySyncResidence();
	const int idx = rfChannelHistoryPoolIndex(ch);
	if (idx < 0 || !valid)
		return;
	if (worstPermille >= RF_CHANNEL_HISTORY_GOOD_PERMILLE) {
		if (g_channelHistoryRuntimeGoodStreak[idx] != 0xFFu)
			g_channelHistoryRuntimeGoodStreak[idx]++;
		g_channelHistoryRuntimeBadStreak[idx] = 0;
		if (g_channelHistoryRuntimeGoodStreak[idx] >=
		    RF_CHANNEL_HISTORY_GOOD_WINDOWS) {
			rfChannelHistoryRecordPersistentOutcome(
				ch, worstPermille, meanPermille, true);
		}
	} else {
		g_channelHistoryRuntimeGoodStreak[idx] = 0;
		if (worstPermille < RF_CHANNEL_HISTORY_BAD_PERMILLE) {
			if (g_channelHistoryRuntimeBadStreak[idx] != 0xFFu)
				g_channelHistoryRuntimeBadStreak[idx]++;
			if (g_channelHistoryRuntimeBadStreak[idx] >=
			    RF_CHANNEL_HISTORY_BAD_WINDOWS)
				rfChannelHistoryRecordPersistentOutcome(
					ch, worstPermille, meanPermille, false);
		} else {
			g_channelHistoryRuntimeBadStreak[idx] = 0;
		}
	}
}

static void rfChannelHistoryMaybeCheckpoint(uint32_t now)
{
	rfChannelHistoryEnsureLoaded();
	const uint8_t liveMask = rfChannelLiveMask(now);
	if (!liveMask) {
		if (!g_channelJournalNoLiveSinceMs)
			g_channelJournalNoLiveSinceMs = now;
	} else {
		g_channelJournalNoLiveSinceMs = 0;
	}
	// An in-progress record is advanced in tiny, pre-erased word quanta. It is
	// paused across any channel handoff and automatically falls back to offline
	// completion if a live word ever exceeds the conservative stall budget.
	rfChannelJournalStep(now, liveMask);
	if (g_channelJournalJobActive || !g_channelHistoryPersistentDirty ||
	    g_channelHistoryPersistentWrites >=
		    RF_CHANNEL_HISTORY_PERSIST_MAX_WRITES_PER_BOOT ||
	    g_rfChHandoffState != RF_CH_IDLE || g_rfChGroupActive)
		return;
	if (g_channelHistoryPersistentLastWriteMs &&
	    (uint32_t)(now - g_channelHistoryPersistentLastWriteMs) <
		    RF_CHANNEL_HISTORY_PERSIST_MIN_INTERVAL_MS)
		return;
	if (g_channelJournalFreeSlot < 0 &&
	    !rfChannelJournalMaybeCollect(now, liveMask))
		return;
	if (!rfChannelJournalStartWrite())
		return;
	// Allow the first word immediately; later words are rate-shaped.
	rfChannelJournalStep(now, liveMask);
}

static void rfChannelEvidenceClearParticipant(uint8_t slot)
{
	if (slot >= NSLOT)
		return;
	for (unsigned i = 0; i < RF_RECOVERY_CHANNEL_COUNT; i++) {
		g_channelEvidenceGoodCount[slot][i] = 0;
		g_channelEvidenceGoodSum[slot][i] = 0;
		g_channelEvidenceMean[slot][i] = 0;
		g_channelEvidenceLastGoodMs[slot][i] = 0;
	}
}

static void rfChannelRecoveryResetForParticipantChange()
{
	g_channelEvidenceResidenceChannel = g_sessCh;
	g_channelRecoveryDecidedThisResidence = false;
	if (g_rfChHandoffState == RF_CH_IDLE)
		rfChannelRecoverySetTarget(0u);
}

static void rfChannelEvidenceSyncParticipants(uint8_t liveMask)
{
	if (liveMask == g_channelEvidenceParticipantMask)
		return;
	const uint8_t oldMask = g_channelEvidenceParticipantMask;
	const uint8_t changed = (uint8_t)(liveMask ^ oldMask);
	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (changed & bit)
			rfChannelEvidenceClearParticipant(s);
	}
	g_channelEvidenceParticipantMask = liveMask;
	rfChannelRecoveryResetForParticipantChange();
}

static void rfChannelEvidenceSyncResidence()
{
	if (g_channelEvidenceResidenceChannel == g_sessCh)
		return;
	g_channelEvidenceResidenceChannel = g_sessCh;
	g_channelRecoveryDecidedThisResidence = false;
}

static void rfChannelEvidenceObserve(uint8_t slot, uint8_t ch,
				     uint16_t successPermille, bool valid,
				     uint32_t now)
{
	if (slot >= NSLOT || !valid)
		return;
	const int idx = rfRecoveryChannelIndex(ch);
	if (idx < 0)
		return;
	if (successPermille < RF_CHANNEL_EVIDENCE_MIN_SUCCESS_PERMILLE) {
		g_channelEvidenceGoodCount[slot][idx] = 0;
		g_channelEvidenceGoodSum[slot][idx] = 0;
		g_channelEvidenceMean[slot][idx] = 0;
		g_channelEvidenceLastGoodMs[slot][idx] = 0;
		return;
	}
	if (g_channelEvidenceGoodCount[slot][idx] <
	    RF_CHANNEL_EVIDENCE_WINDOWS) {
		g_channelEvidenceGoodCount[slot][idx]++;
		g_channelEvidenceGoodSum[slot][idx] += successPermille;
		g_channelEvidenceMean[slot][idx] =
			(uint16_t)(g_channelEvidenceGoodSum[slot][idx] /
				   g_channelEvidenceGoodCount[slot][idx]);
	} else {
		g_channelEvidenceMean[slot][idx] =
			(uint16_t)(((uint32_t)g_channelEvidenceMean[slot][idx] *
					    4u +
				    successPermille) /
				   5u);
	}
	g_channelEvidenceLastGoodMs[slot][idx] = now;
}

static uint8_t rfCohortSelectRecoveryChannel(uint8_t liveMask,
					     uint16_t currentWorstPermille,
					     uint32_t now)
{
	uint8_t bestCh = 0;
	uint16_t bestWorst = 0;
	uint16_t bestCohortMean = 0;
	uint32_t bestWorstAge = 0xFFFFFFFFu;
	for (uint8_t ch = RF_RECOVERY_CHANNEL_MIN;
	     ch <= RF_RECOVERY_CHANNEL_MAX; ch += 2u) {
		if (ch == g_sessCh)
			continue;
		const int idx = rfRecoveryChannelIndex(ch);
		if (idx < 0)
			continue;
		bool eligible = true;
		uint16_t worst = 1000u;
		uint32_t sum = 0;
		uint32_t oldestAge = 0;
		uint8_t count = 0;
		for (uint8_t s = 0; s < NSLOT; s++) {
			const uint8_t bit = (uint8_t)(1u << s);
			if (!(liveMask & bit))
				continue;
			if (g_channelEvidenceGoodCount[s][idx] <
				    RF_CHANNEL_EVIDENCE_WINDOWS ||
			    g_channelEvidenceMean[s][idx] <
				    RF_CHANNEL_EVIDENCE_MIN_SUCCESS_PERMILLE) {
				eligible = false;
				break;
			}
			const uint32_t age =
				(uint32_t)(now -
					   g_channelEvidenceLastGoodMs[s][idx]);
			if (age > RF_CHANNEL_EVIDENCE_MAX_AGE_MS) {
				eligible = false;
				break;
			}
			const uint16_t mean = g_channelEvidenceMean[s][idx];
			if (mean < worst)
				worst = mean;
			if (age > oldestAge)
				oldestAge = age;
			sum += mean;
			count++;
		}
		if (!eligible || !count)
			continue;
		if (worst <
		    (uint16_t)(currentWorstPermille +
			       RF_CHANNEL_RECOVERY_MIN_IMPROVEMENT_PERMILLE))
			continue;
		const uint16_t cohortMean = (uint16_t)(sum / count);
		if (bestCh == 0u || worst > bestWorst ||
		    (worst == bestWorst && cohortMean > bestCohortMean) ||
		    (worst == bestWorst && cohortMean == bestCohortMean &&
		     oldestAge < bestWorstAge)) {
			bestCh = ch;
			bestWorst = worst;
			bestCohortMean = cohortMean;
			bestWorstAge = oldestAge;
		}
	}
	if (bestCh)
		return bestCh;

	// Current packet evidence is authoritative. When no alternate channel has
	// fresh proof yet, consult learned history; if history also has no proven
	// option, explore exactly one never-tried pool member. Cached idle RSSI may
	// rank only that unexplored set and never overrides an explored channel.
	rfChannelHistoryEnsureLoaded();
	bestCh = rfChannelHistorySelectGoodPrior(g_sessCh);
	if (bestCh)
		return bestCh;
	bestCh = rfChannelHistorySelectUnexplored(g_sessCh);
	if (bestCh)
		return bestCh;
	return rfChannelHistorySelectBestRemaining(g_sessCh,
						   currentWorstPermille);
}

static void rfCohortQualityWindow(uint8_t liveMask, uint32_t now)
{
	rfChannelEvidenceSyncResidence();
	bool allValid = true;
	bool wouldPending = false;
	uint16_t currentWorst = 1000u;

	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(liveMask & bit))
			continue;
		const uint32_t polls = g_linkQualityPolls[s];
		const uint32_t replies = g_linkQualityReplies[s];
		const uint16_t successPermille =
			polls ? (uint16_t)((replies * 1000u) / polls) : 0u;
		const bool valid = polls >= RF_LINK_QUALITY_MIN_POLLS;
		const bool bad = valid &&
				 successPermille <
					 RF_LINK_QUALITY_BAD_SUCCESS_PERMILLE;
		if (bad) {
			if (g_linkQualityBadStreak[s] != 0xFF)
				g_linkQualityBadStreak[s]++;

		} else {
			g_linkQualityBadStreak[s] = 0;
		}
		rfChannelEvidenceObserve(s, g_sessCh, successPermille, valid,
					 now);
		rfStartupChannelObserveWindow(s, successPermille, valid);
		if (!valid)
			allValid = false;
		else if (successPermille < currentWorst)
			currentWorst = successPermille;
		const bool residency = (uint32_t)(now - g_qosLastHopMs) >=
				       RF_LINK_QUALITY_MIN_RESIDENCY_MS;
		if (valid && residency &&
		    g_linkQualityBadStreak[s] >=
			    RF_LINK_QUALITY_BAD_STREAK_WINDOWS)
			wouldPending = true;
	}

	uint32_t historySum = 0;
	uint8_t historyCount = 0;
	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(liveMask & bit))
			continue;
		const uint32_t polls = g_linkQualityPolls[s];
		const uint32_t replies = g_linkQualityReplies[s];
		if (polls >= RF_LINK_QUALITY_MIN_POLLS) {
			historySum += (uint16_t)((replies * 1000u) / polls);
			historyCount++;
		}
	}
	const uint16_t historyMean =
		historyCount ? (uint16_t)(historySum / historyCount) : 0u;
	rfChannelHistoryObserve(g_sessCh, currentWorst, historyMean,
				allValid && historyCount != 0u);
	for (int s = 0; s < NSLOT; s++)
		rfLinkQualityResetWindow(s);
	if (!allValid || !wouldPending)
		return;
	if (g_channelRecoveryDecidedThisResidence)
		return;

	g_channelRecoveryDecidedThisResidence = true;
	const uint8_t target =
		rfCohortSelectRecoveryChannel(liveMask, currentWorst, now);
	rfChannelRecoverySetTarget(target);
	rfChannelRecoveryRequest(wouldPending);
}

static void rfLinkQualityTask()
{
	const unsigned long now = millis();
	rfChannelHistoryEnsureLoaded();
	rfChannelHistoryMaybeCheckpoint(now);
	if (!g_qos)
		return;
	if ((uint32_t)(now - g_qosCheckMs) < RF_LINK_QUALITY_WINDOW_MS)
		return;
	g_linkQualityCheckMs = now;
	g_qosCheckMs = now;

	const uint8_t liveMask = rfChannelLiveMask(now);
	rfChannelEvidenceSyncParticipants(liveMask);
	if (!liveMask) {
		for (int s = 0; s < NSLOT; s++)
			rfLinkQualityResetWindow(s);
		return;
	}
	rfCohortQualityWindow(liveMask, now);
}

#define RF_HOP_ACT_DIGITAL 0x01u
#define RF_HOP_ACT_LSTICK 0x02u
#define RF_HOP_ACT_RSTICK 0x04u
#define RF_HOP_ACT_LT 0x08u
#define RF_HOP_ACT_RT 0x10u
#define RF_HOP_ACT_LPAD 0x20u
#define RF_HOP_ACT_RPAD 0x40u

static int32_t rfHopAbs16(int16_t v)
{
	return v == (int16_t)0x8000 ? 32768 :
				      (v < 0 ? -(int32_t)v : (int32_t)v);
}

static uint8_t rfChannelDecodedActivity(int slot, uint32_t buttons)
{
	if (slot < 0 || slot >= NSLOT)
		return 0;
	const PuckInput &in = g_in[slot];
	const uint32_t digitalMask =
		TB_A | TB_B | TB_X | TB_Y | TB_QAM | TB_R3 | TB_VIEW | TB_R4 |
		TB_R5 | TB_RB | TB_DDN | TB_DRT | TB_DLF | TB_DUP | TB_MENU |
		TB_L3 | TB_STEAM | TB_L4 | TB_L5 | TB_LB | TB_RPADC | TB_LPADC |
		TB_R2 | TB_L2 | TB_TOUCH | TB_MUTE;
	uint8_t activity = 0;
	if (buttons & digitalMask)
		activity |= RF_HOP_ACT_DIGITAL;
	if (rfHopAbs16(in.lx) > RF_CHANNEL_HANDOFF_STICK_DEADZONE ||
	    rfHopAbs16(in.ly) > RF_CHANNEL_HANDOFF_STICK_DEADZONE)
		activity |= RF_HOP_ACT_LSTICK;
	if (rfHopAbs16(in.rx) > RF_CHANNEL_HANDOFF_STICK_DEADZONE ||
	    rfHopAbs16(in.ry) > RF_CHANNEL_HANDOFF_STICK_DEADZONE)
		activity |= RF_HOP_ACT_RSTICK;
	if (in.lt > RF_CHANNEL_HANDOFF_TRIGGER_THRESHOLD)
		activity |= RF_HOP_ACT_LT;
	if (in.rt > RF_CHANNEL_HANDOFF_TRIGGER_THRESHOLD)
		activity |= RF_HOP_ACT_RT;

	// Only decoded touch bits are authoritative pad activity. Coordinates and
	// pressure may remain noisy or undefined at idle and are not handoff evidence.
	if (buttons & TB_LPADT)
		activity |= RF_HOP_ACT_LPAD;
	if (buttons & TB_RPADT)
		activity |= RF_HOP_ACT_RPAD;
	return activity;
}

static void rfChannelNoteDecodedInput(int slot, uint32_t buttons)
{
	if (slot < 0 || slot >= NSLOT)
		return;
	const uint8_t activity = rfChannelDecodedActivity(slot, buttons);
	const unsigned long reportNow = millis();
	g_rfHopInputLastMask[slot] = activity;
	g_rfHopInputLastReportMs[slot] = reportNow;
	g_rfHopInputReportSeq[slot]++;
	if (activity)
		g_rfHopInputSeq[slot]++;
}

bool rfChannelHandoffHostGrace(int slot)
{
	if (g_rfChHandoffState == RF_CH_IDLE ||
	    g_rfChHandoffState == RF_CH_HOP_PENDING || slot < 0 ||
	    slot >= NSLOT)
		return false;
	if (!(g_rfChHandoffMask & (uint8_t)(1u << slot)))
		return false;
	return (uint32_t)(millis() - g_rfChHandoffStartedMs) <
	       RF_CHANNEL_HANDOFF_HOST_GRACE_MS;
}

static bool rfChannelHandoffOwnsRadio()
{
	return g_rfChHandoffState == RF_CH_QUIET_DWELL ||
	       g_rfChHandoffState == RF_CH_ROLLBACK_QUIET_DWELL;
}

static void rfChannelSnapshotReplies(uint8_t mask)
{
	for (uint8_t s = 0; s < NSLOT; s++)
		if (mask & (uint8_t)(1u << s))
			g_rfChHandoffReplyBaseline[s] = g_connReplyMs[s];
}

static bool rfChannelFreshReply(uint8_t mask, unsigned long now)
{
	if (!mask)
		return false;
	for (uint8_t s = 0; s < NSLOT; s++) {
		if (!(mask & (uint8_t)(1u << s)))
			continue;
		if (!g_connReplyMs[s] ||
		    g_connReplyMs[s] == g_rfChHandoffReplyBaseline[s] ||
		    (uint32_t)(now - g_connReplyMs[s]) >= 80u)
			return false;
	}
	return true;
}

static uint8_t rfE4FastResponseTxn(uint8_t fromCh, uint8_t toCh, uint8_t mask)
{
	int slot = rfChannelMaskSlot(mask);
	if (slot < 0)
		return RF_E4_RESP_NONE;

	const uint8_t txS1 = (uint8_t)(((g_pollPid[slot]++ & 3u) << 1) | 1u);

	// Use the validated EasyDMA TX-to-RX response-turn sequence.
	memset(rftx, 0, sizeof rftx);
	rftx[0] = 4;
	rftx[1] = txS1;
	rftx[2] = 0xE4;
	rftx[3] = toCh;
	rftx[4] = 0x02;
	rftx[5] = RF_E4_TIMING_CONTROL;

	rfConfig(fromCh);
	rfSetAddr(g_sessBase[slot], g_sessPrefix[slot]);
	NRF_RADIO->PACKETPTR = (uint32_t)rftx;
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_END_DISABLE_Msk |
			    RADIO_SHORTS_DISABLED_RXEN_Msk;

	NRF_RADIO->EVENTS_READY = 0;
	NRF_RADIO->EVENTS_ADDRESS = 0;
	NRF_RADIO->EVENTS_PAYLOAD = 0;
	NRF_RADIO->EVENTS_END = 0;
	NRF_RADIO->EVENTS_DISABLED = 0;
#if defined(RADIO_EVENTS_CRCOK_EVENTS_CRCOK_Msk)
	NRF_RADIO->EVENTS_CRCOK = 0;
#endif
#if defined(RADIO_EVENTS_CRCERROR_EVENTS_CRCERROR_Msk)
	NRF_RADIO->EVENTS_CRCERROR = 0;
#endif

	const uint32_t txStartUs = micros();
	NRF_RADIO->TASKS_TXEN = 1;

	// Synchronize on TX END and clear TX-owned latches before RX observation.
	while (!NRF_RADIO->EVENTS_END &&
	       (uint32_t)(micros() - txStartUs) < 2500u) {
	}

	if (!NRF_RADIO->EVENTS_END) {
		NRF_RADIO->SHORTS = 0;
		NRF_RADIO->EVENTS_DISABLED = 0;
		NRF_RADIO->TASKS_DISABLE = 1;
		const uint32_t stopUs = micros();
		while (!NRF_RADIO->EVENTS_DISABLED &&
		       (uint32_t)(micros() - stopUs) < 500u) {
		}
		NRF_RADIO->EVENTS_DISABLED = 0;
		NRF_RADIO->PACKETPTR = (uint32_t)rfrx;
		return RF_E4_RESP_NONE;
	}

	const uint32_t e4Primask = __get_PRIMASK();
	__disable_irq();
	NRF_RADIO->EVENTS_READY = 0;
	NRF_RADIO->EVENTS_ADDRESS = 0;
	NRF_RADIO->EVENTS_PAYLOAD = 0;
	NRF_RADIO->EVENTS_END = 0;
#if defined(RADIO_EVENTS_CRCOK_EVENTS_CRCOK_Msk)
	NRF_RADIO->EVENTS_CRCOK = 0;
#endif
#if defined(RADIO_EVENTS_CRCERROR_EVENTS_CRCERROR_Msk)
	NRF_RADIO->EVENTS_CRCERROR = 0;
#endif
	__set_PRIMASK(e4Primask);

	bool sawEnd = false;
	const uint32_t rxWaitStartUs = micros();
	while ((uint32_t)(micros() - rxWaitStartUs) < RF_E4_RESPONSE_WAIT_US) {
		if (NRF_RADIO->EVENTS_END) {
			sawEnd = true;
			break;
		}
	}

	uint8_t kind = RF_E4_RESP_NONE;
	if (sawEnd && (NRF_RADIO->CRCSTATUS & 1u) != 0) {
		const uint8_t rxLen = rftx[0];
		const uint8_t rxS1 = rftx[1];
		if ((rxS1 & 0x07u) == (txS1 & 0x07u)) {
			if (rxLen == 0u)
				kind = RF_E4_RESP_ZERO;
			else if (rxLen <= 96u && rftx[2] == 0xF1u)
				kind = RF_E4_RESP_F1;
			else
				kind = RF_E4_RESP_OTHER;
		}
	}

	NRF_RADIO->SHORTS = 0;
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->TASKS_DISABLE = 1;
	const uint32_t stopUs = micros();
	while (!NRF_RADIO->EVENTS_DISABLED &&
	       (uint32_t)(micros() - stopUs) < 500u) {
	}
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->PACKETPTR = (uint32_t)rfrx;

	return kind;
}

static void rfChannelGroupReset()
{
	g_rfChGroupActive = false;
	g_rfChGroupPhase = RF_GROUP_IDLE;
	g_rfChGroupParticipants = 0;
	g_rfChGroupNeutralSeenMask = 0;
	g_rfChGroupSawActivitySincePending = false;
	g_rfChGroupNeutralStartValid = false;
	g_rfChGroupNeutralStartMs = 0;
	memset(g_rfChGroupActivitySeqSeen, 0,
	       sizeof g_rfChGroupActivitySeqSeen);
	memset(g_rfChGroupReportSeqSeen, 0, sizeof g_rfChGroupReportSeqSeen);
}

static void rfChannelGroupSnapshotInputSeqs(uint8_t mask)
{
	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(mask & bit))
			continue;
		g_rfChGroupActivitySeqSeen[s] = g_rfHopInputSeq[s];
		g_rfChGroupReportSeqSeen[s] = g_rfHopInputReportSeq[s];
	}
}

static void rfChannelGroupResetNeutralProof()
{
	g_rfChGroupNeutralSeenMask = 0;
	g_rfChGroupNeutralStartValid = false;
	g_rfChGroupNeutralStartMs = 0;
}

static void rfChannelGroupRearmPending()
{
	g_rfChGroupPhase = RF_GROUP_HOP_PENDING;
	g_rfChHandoffState = RF_CH_HOP_PENDING;
	g_rfChHandoffPhaseMs = millis();
	g_rfChGroupSawActivitySincePending = false;
	rfChannelGroupResetNeutralProof();
	rfChannelGroupSnapshotInputSeqs(g_rfChGroupParticipants);
}

static void rfChannelGroupAbort()
{
	g_rfChHandoffState = RF_CH_IDLE;
	rfChannelGroupReset();
}

static bool rfChannelGroupBegin(uint8_t oldCh, uint8_t newCh, uint8_t mask,
				unsigned long now)
{
	if (!mask)
		return false;

	g_rfChHandoffOld = oldCh;
	g_rfChHandoffTarget = newCh;
	g_rfChHandoffMask = mask;
	g_rfChHandoffStartedMs = now;
	g_rfChHandoffPhaseMs = now;
	g_rfChHandoffRequireActivityCycle = true;

	g_rfChGroupActive = true;
	g_rfChGroupPhase = RF_GROUP_HOP_PENDING;
	g_rfChGroupParticipants = mask;
	g_rfChGroupSawActivitySincePending = false;
	rfChannelGroupResetNeutralProof();
	rfChannelGroupSnapshotInputSeqs(mask);
	g_rfChHandoffState = RF_CH_HOP_PENDING;
	return true;
}

static bool rfChannelGroupFreshNeutral(unsigned long now)
{
	// The participant set is frozen.  A join/leave while authorization is still
	// pending aborts rather than silently producing a cohort that excludes a live
	// controller or waits on one that has disappeared.
	const uint8_t liveMask = rfChannelLiveMask(now);
	if (liveMask != g_rfChGroupParticipants) {
		rfChannelGroupAbort();
		return false;
	}

	bool sawActivity = false;
	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(g_rfChGroupParticipants & bit))
			continue;
		if (g_rfHopInputSeq[s] != g_rfChGroupActivitySeqSeen[s]) {
			g_rfChGroupActivitySeqSeen[s] = g_rfHopInputSeq[s];
			g_rfChGroupReportSeqSeen[s] = g_rfHopInputReportSeq[s];
			sawActivity = true;
			g_rfChGroupSawActivitySincePending = true;
		}
	}
	if (sawActivity) {
		rfChannelGroupResetNeutralProof();
		return false;
	}

	// Preserve the fail-closed activity-cycle prerequisite. In the
	// group case, a meaningful post-request event from any participant opens the
	// shared neutral-qualification phase; every participant must then prove fresh
	// neutral input after the most recent activity reset.
	if (g_rfChHandoffRequireActivityCycle &&
	    !g_rfChGroupSawActivitySincePending)
		return false;

	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(g_rfChGroupParticipants & bit))
			continue;
		if (g_rfHopInputReportSeq[s] != g_rfChGroupReportSeqSeen[s]) {
			g_rfChGroupReportSeqSeen[s] = g_rfHopInputReportSeq[s];
			if (g_rfHopInputLastMask[s] != 0u) {
				rfChannelGroupResetNeutralProof();
				return false;
			}
			g_rfChGroupNeutralSeenMask |= bit;
		}
	}

	if (g_rfChGroupNeutralSeenMask != g_rfChGroupParticipants)
		return false;

	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(g_rfChGroupParticipants & bit))
			continue;
		if (g_rfHopInputLastMask[s] != 0u ||
		    (uint32_t)(now - g_rfHopInputLastReportMs[s]) >
			    RF_CHANNEL_HANDOFF_INPUT_REPORT_FRESH_MS) {
			rfChannelGroupResetNeutralProof();
			return false;
		}
	}

	if (!g_rfChGroupNeutralStartValid) {
		g_rfChGroupNeutralStartValid = true;
		g_rfChGroupNeutralStartMs = now;
		return false;
	}
	if ((uint32_t)(now - g_rfChGroupNeutralStartMs) <
	    RF_CHANNEL_HANDOFF_QUIESCENT_MS)
		return false;
	return true;
}

static bool rfChannelGroupAuthorizeAll()
{
	g_rfChHandoffStartedMs = millis();
	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(g_rfChGroupParticipants & bit))
			continue;

		const uint8_t kind = rfE4FastResponseTxn(
			g_rfChHandoffOld, g_rfChHandoffTarget, bit);
		if (kind != RF_E4_RESP_ZERO && kind != RF_E4_RESP_F1)
			return false;
	}
	return true;
}

static void rfChannelGroupRollback(uint8_t mask)
{
	for (uint8_t s = 0; s < NSLOT; s++) {
		const uint8_t bit = (uint8_t)(1u << s);
		if (!(mask & bit))
			continue;
		(void)rfE4FastResponseTxn(g_rfChHandoffTarget, g_rfChHandoffOld,
					  bit);
	}
}

static void rfChannelGroupHandoffTask(unsigned long now)
{
	if (!g_rfChGroupActive)
		return;

	if (g_rfChGroupPhase == RF_GROUP_HOP_PENDING) {
		if (!rfChannelGroupFreshNeutral(now))
			return;
		g_rfChHandoffRequireActivityCycle = false;
		g_rfChGroupSawActivitySincePending = false;
		rfChannelGroupResetNeutralProof();

		if (!rfChannelGroupAuthorizeAll()) {
			// A missing/invalid E4 response never proves that a participant
			// stayed on the old channel.  Treat the whole frozen cohort as
			// potentially moved, allow the 5-ms switch interval, then issue
			// target->old reconciliation attempts to every participant.
			g_rfChGroupPhase = RF_GROUP_PARTIAL_WAIT_ROLLBACK;
			g_rfChHandoffState = RF_CH_ROLLBACK_QUIET_DWELL;
			g_rfChHandoffPhaseMs = millis();
			return;
		}

		g_rfChGroupPhase = RF_GROUP_AUTHORIZED_WAIT_SWITCH;
		g_rfChHandoffState = RF_CH_QUIET_DWELL;
		g_rfChHandoffPhaseMs = millis();
		return;
	}

	if (g_rfChGroupPhase == RF_GROUP_AUTHORIZED_WAIT_SWITCH) {
		if ((uint32_t)(now - g_rfChHandoffPhaseMs) <
		    RF_CHANNEL_HANDOFF_EARLY_SWITCH_MS)
			return;
		rfChannelSnapshotReplies(g_rfChGroupParticipants);
		g_sessCh = g_rfChHandoffTarget;
		g_rfChHandoffPhaseMs = now;
		g_rfChHandoffState = RF_CH_ACQUIRE;
		g_rfChGroupPhase = RF_GROUP_TARGET_ACQUIRE;
		return;
	}

	if (g_rfChGroupPhase == RF_GROUP_TARGET_ACQUIRE) {
		if (rfChannelFreshReply(g_rfChGroupParticipants, now)) {
			g_rfChHandoffState = RF_CH_IDLE;
			g_lastChannelHopMs = now;
			g_qosLastHopMs = now;
			rfChannelGroupReset();
			return;
		}
		if ((uint32_t)(now - g_rfChHandoffPhaseMs) <
		    RF_CHANNEL_HANDOFF_TARGET_OBSERVE_MS)
			return;
		rfChannelGroupRollback(g_rfChGroupParticipants);
		g_rfChGroupPhase = RF_GROUP_ROLLBACK_WAIT_SWITCH;
		g_rfChHandoffState = RF_CH_ROLLBACK_QUIET_DWELL;
		g_rfChHandoffPhaseMs = millis();
		return;
	}

	if (g_rfChGroupPhase == RF_GROUP_PARTIAL_WAIT_ROLLBACK) {
		if ((uint32_t)(now - g_rfChHandoffPhaseMs) <
		    RF_CHANNEL_HANDOFF_EARLY_SWITCH_MS)
			return;
		rfChannelSnapshotReplies(g_rfChGroupParticipants);
		rfChannelGroupRollback(g_rfChGroupParticipants);
		g_rfChGroupPhase = RF_GROUP_PARTIAL_ACQUIRE_OLD;
		g_rfChHandoffState = RF_CH_ROLLBACK_ACQUIRE;
		g_rfChHandoffPhaseMs = millis();
		return;
	}

	if (g_rfChGroupPhase == RF_GROUP_PARTIAL_ACQUIRE_OLD) {
		if (rfChannelFreshReply(g_rfChGroupParticipants, now)) {
			// Everyone is confirmed back on the old session. Keep the same recovery
			// request alive, but require a brand-new shared activity cycle
			// before another group authorization attempt.
			rfChannelGroupRearmPending();
			return;
		}
		if ((uint32_t)(now - g_rfChHandoffPhaseMs) <
		    RF_CHANNEL_HANDOFF_ROLLBACK_ACQUIRE_MS)
			return;
		g_lastDisc = 0;
		g_lastSessBeacon = 0;
		rfChannelGroupAbort();
		return;
	}

	if (g_rfChGroupPhase == RF_GROUP_ROLLBACK_WAIT_SWITCH) {
		if ((uint32_t)(now - g_rfChHandoffPhaseMs) <
		    RF_CHANNEL_HANDOFF_ROLLBACK_QUIET_MS)
			return;
		rfChannelSnapshotReplies(g_rfChGroupParticipants);
		g_sessCh = g_rfChHandoffOld;
		g_rfChHandoffState = RF_CH_ROLLBACK_ACQUIRE;
		g_rfChGroupPhase = RF_GROUP_ROLLBACK_ACQUIRE_OLD;
		g_rfChHandoffPhaseMs = now;
		return;
	}

	if (g_rfChGroupPhase == RF_GROUP_ROLLBACK_ACQUIRE_OLD) {
		if (rfChannelFreshReply(g_rfChGroupParticipants, now)) {
			g_rfChHandoffState = RF_CH_IDLE;
			rfChannelGroupReset();
			return;
		}
		if ((uint32_t)(now - g_rfChHandoffPhaseMs) <
		    RF_CHANNEL_HANDOFF_ROLLBACK_ACQUIRE_MS)
			return;
		g_lastDisc = 0;
		g_lastSessBeacon = 0;
		rfChannelGroupAbort();
	}
}

static void rfChannelHandoffTask()
{
	if (!g_rfChGroupActive)
		return;
	rfChannelGroupHandoffTask(millis());
}

// QoS hop is shared across all slots -- we run all connected sessions on the same channel for simplicity.
// The per-slot session ADDRESS is what isolates the controllers from each other; the channel is global.
void rfHopTo(uint8_t newCh)
{
	if (newCh == g_sessCh || g_rfChHandoffState != RF_CH_IDLE)
		return;
	if (newCh < 4u || newCh > 80u || (newCh & 1u))
		return;

	unsigned long now = millis();
	uint8_t mask = rfChannelLiveMask(now);
	if (!mask)
		return;

	(void)rfChannelGroupBegin(g_sessCh, newCh, mask, now);
}

bool rfRecoveryRequestManualHop(uint8_t channel)
{
	if (rfChannelHistoryPoolIndex(channel) < 0)
		return false;
	if (channel == g_sessCh || g_rfChHandoffState != RF_CH_IDLE ||
	    g_rfChGroupActive)
		return false;
	if (!rfChannelLiveMask(millis()))
		return false;

	rfHopTo(channel);
	return g_rfChHandoffState != RF_CH_IDLE || g_rfChGroupActive;
}

// TX one connected packet [LEN][S1][payload] on channel ch, then RX the reply into rfrx; decodes 0xF1.
// rxWinUs overrides the reply-wait window (0 = use g_rxWin). Pass a tiny value for NO-ACK relays that expect
// no reply, so they don't burn a full ~1.2ms window of dead air per haptic. Per-slot: the connected poll runs
// on this slot's UNIQUE session address (one address per bonded controller); replies are demuxed by which
// address the controller answers on (each controller only hears its own).
uint8_t rfConnTx(uint8_t ch, uint8_t s1, const uint8_t *payload, uint8_t plen,
		 uint16_t rxWinUs)
{
	// relays pass a tiny window (no reply expected); polls use g_rxWin
	uint16_t win = rxWinUs ? rxWinUs : g_rxWin;
	memset(rftx, 0, sizeof rftx);
	rftx[0] = plen; // LENGTH = payload byte count
	rftx[1] = s1; // S1 (type-specific)
	memcpy(rftx + 2, payload, plen); // payload[0]=type byte, then data/TLVs
	rfConfig(ch);
	// connected poll runs on this slot's UNIQUE session addr (per-bond). g_curSlot is set by rfConnStep
	// before each call; fall back to slot 0 if not (e.g. rf_diag paths).
	int slot = (g_curSlot >= 0 && g_curSlot < NSLOT) ? g_curSlot : 0;
	rfSetAddr(g_sessBase[slot], g_sessPrefix[slot]);
	NRF_RADIO->PACKETPTR = (uint32_t)rftx;
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_END_DISABLE_Msk;
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->TASKS_TXEN = 1;
	RWAIT_DISABLED();
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->PACKETPTR = (uint32_t)rfrx;
	rfrx[0] = 0;
	// RXEN->READY->START; catch the reply. ADDRESS->RSSISTART samples the reply's signal strength (read from
	// RSSISAMPLE below, surfaced to Steam via report 0x7B); DISABLED->RSSISTOP closes the measurement.
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_ADDRESS_RSSISTART_Msk |
			    RADIO_SHORTS_DISABLED_RSSISTOP_Msk;
	NRF_RADIO->EVENTS_END = 0;
	NRF_RADIO->TASKS_RXEN = 1;
	uint32_t t0 = micros();
	while (!NRF_RADIO->EVENTS_END && (micros() - t0) < win) {
	} // RX window (tunable 'r'; or relay override)
	uint8_t rxlen = 0;
	if (NRF_RADIO->EVENTS_END) {
		NRF_RADIO->EVENTS_END = 0;
		bool crcok = NRF_RADIO->CRCSTATUS & 1;
		rxlen = rfrx[0];
		// reply arrived but CRC failed -> RF quality (channel/interference)
		if (!crcok) {
			g_stCrc[slot]++;
			g_qosBad++;
		}
		// F1 input ~46B; 0x43-augmented ~66B -> allow up to MAXLEN(96)
		if (crcok && rxlen && rxlen <= 96) {
			// reply type byte (proven offset from captures)
			uint8_t rtype = rfrx[2];
			// Only OUR controller's replies (F-type: 0xF1 input / 0xF2 disconnect / 0xF3 status) mark the link
			// alive. Every OpenPuck shares the same RF address "ibex" + CRC config, and a puck transmits host-frame
			// beacons (0xE1) + polls (0xE2/E3/E7) -- all E-type. Without this gate, puck A receives a SECOND puck's
			// 0xE1 beacon (e.g. one just plugged into another computer), bumps g_connReplyMs, and the "new RF
			// connection" wake in rfLinkTask() fires -> the second puck spuriously wakes this sleeping host.
			if (rtype >= 0xF0) {
				int s = (g_curSlot >= 0 && g_curSlot < NSLOT) ?
						g_curSlot :
						0;
				// A reply after a long gap (or the first ever) = a (re)connect. Arm the haptic block + re-init HERE,
				// directly off the reply stream -- reliable even when hapticTask's 300ms link-up edge doesn't fire
				// (e.g. a power-cycled controller that reconnects without us cleanly seeing the link drop).
				if (g_connReplyMs[s] == 0 ||
				    (uint32_t)(millis() - g_connReplyMs[s]) >
					    1500u) {
					// Lifecycle log (CDC debug boot): distinguish a first-ever connect from a reconnect and
					// print the silent gap -- lets a long session of connect/disconnect cycles be diffed to
					// see whether each cycle re-establishes (churn / boot-haptic click) vs stays linked.
					if (Serial.availableForWrite() > 130) {
						uint32_t gap =
							g_connReplyMs[s] ?
								(uint32_t)(millis() -
									   g_connReplyMs
										   [s]) :
								0;
						Serial.printf(
							"# LC t=%lu slot%d %s gap=%lums rtype=%02X cd=%lums\n",
							(unsigned long)millis(),
							s,
							g_connReplyMs[s] ?
								"RECONNECT" :
								"CONNECT",
							(unsigned long)gap,
							rtype,
							(unsigned long)(millis() -
									g_connCooldown));
					}
					hapticOnReconnect(s);
					faultDiagTrace(FR_RFUP, s);
				}
				g_connRx++;
				// link alive -> loop() suppresses the redundant E1 beacon
				g_connReplyMs[s] = millis();
				// |dBm| of this reply (started by the ADDRESS short)
				uint8_t rs =
					(uint8_t)(NRF_RADIO->RSSISAMPLE & 0x7F);
				// EWMA, ~8-sample horizon, per-slot
				if (rs)
					g_linkRssi[s] =
						g_linkRssi[s] ?
							(uint8_t)((g_linkRssi[s] *
									   7u +
								   rs + 4u) /
								  8u) :
							rs;
			}
			if (rtype == 0xF1)
				g_stF1[slot]++;
			// controller disconnecting/powering off -> back off 2.5s so we don't immediately re-wake it.
			// BUT only when no OTHER slot is still live: g_connCooldown is global and gates ALL polling +
			// beacons, so backing off because ONE controller powered off would drop every other connected
			// controller for 2.5s (a real multi-controller disconnect). The powering-off slot goes silent
			// and ages out via SLOT_COLD on its own.
			if (rtype == 0xF2) {
				int others = 0;
				for (int i = 0; i < NSLOT; i++)
					if (i != g_curSlot && g_slot[i].used &&
					    millis() - g_connReplyMs[i] < 300)
						others++;
				faultDiagTrace(FR_RFDN,
					       (uint16_t)((g_curSlot << 8) |
							  (others & 0xFF)));
				if (others == 0)
					g_connCooldown = millis();
				// Lifecycle log: the controller sent F2 (disconnect/power-off). Note whether it armed the
				// 2.5s cooldown (which pauses ALL beacon+poll -> the controller can lose the session and
				// reboot on the next reconnect = a boot-haptic click). Prime suspect for the connect buzz.
				if (Serial.availableForWrite() > 130)
					Serial.printf(
						"# LC t=%lu slot%d F2 DISCONNECT others=%d%s\n",
						(unsigned long)millis(),
						g_curSlot, others,
						others == 0 ?
							" -> cooldown 2.5s (beacon+poll paused)" :
							"");
			}
			// F3 = controller status/version reply (reply to E7 handshake, byte[6]=version)
			if (rtype == 0xF3) {
				g_stF3++;
				g_connF3v = rfrx[6];
				if (g_connVerbose &&
				    Serial.availableForWrite() > 40) {
					Serial.print("  F3 ");
					for (uint8_t i = 0;
					     i <
					     (rxlen + 2 < 32 ? rxlen + 2 : 32);
					     i++)
						Serial.printf("%02X", rfrx[i]);
					Serial.println();
				}
			}
			bool isF1 = (rtype == 0xF1);
			// Every rfConnTx caller (rfConnStep) sets g_curSlot to a valid 0..NSLOT-1 before a poll, so it
			// IS in range here today. But this block does ~50 unguarded g_curSlot array writes (g_in[],
			// g_lastSeq[], and several static per-slot arrays) -- if any future/edge caller ever left
			// g_curSlot at -1, those become out-of-bounds writes that corrupt RAM (the stack-smash / LOCKUP
			// class we're chasing). Guard once at the top so the decode is robust by construction.
			if (isF1 && (g_curSlot < 0 || g_curSlot >= NSLOT))
				isF1 = false;
			if (isF1) {
				g_connF1++;
				// walk ALL type6 TLVs (= HID report 0x45); taking only [0] halves the rate. idx is INT,
				// not uint8_t: tlen 0xFE would make idx+=tlen+2 wrap mod-256 -> infinite loop -> USB hang.
				int idx = 3, end = rxlen + 2;
				const uint8_t *lastRep = nullptr;
				uint8_t lastTlen = 0;
				while (idx + 1 < end) {
					uint8_t tlen = rfrx[idx],
						ttype = rfrx[idx + 1];
					if (tlen == 0)
						break;
					// Only a FULL input report that fits entirely in rfrx: a short or late/garbled TLV must not let
					// the decode read past the RF buffer (corrupts rftx/RAM -> eventual crash).
					// Main input report id: 0x45 (legacy, 45B body) OR 0x42 (SC2 beta update ~2026-07, 53B body).
					// VERIFIED from live captures of both: the 0x42 body [0..45] is byte-for-byte the SAME layout as
					// 0x45 (buttons/triggers/sticks/pads/IMU at identical offsets) -- it just adds 8 trailing bytes
					// ([46..47]=0x7FFF const, [48..53]=0) and sets two extra always-on status bits (28/29) that no
					// mode reads. So both decode through this ONE path unchanged; rep[0] carries the id downstream
					// (Steam forwards it verbatim under the right id/length in onReport45).
					if (ttype == 6 && tlen >= 28 &&
					    (size_t)(idx + 2) + tlen <=
						    sizeof(rfrx) &&
					    (rfrx[idx + 2] == 0x45 ||
					     rfrx[idx + 2] == 0x42)) {
						// report 0x45/0x42: [id][seq][buttons u32]...
						const uint8_t *rep =
							&rfrx[idx + 2];
						bool fresh =
							(rep[1] !=
							 g_lastSeq[g_curSlot]);
						// genuine new report vs stale poll-repeat
						if (fresh) {
							g_stNew[g_curSlot]++;
							g_lastSeq[g_curSlot] =
								rep[1];
						}
						uint32_t bb = btnsOf(rep);
						// USB remote wakeup on Steam button short press (down + up within 1 s). A long press likely means
						// the user is powering off the controller, so we ignore it.
						{
							// per-slot: with round-robin polling, a shared static gets
							// reset by other slots' reports between press and release.
							static bool steamWasDown
								[NSLOT] = {};
							static unsigned long steamDownMs
								[NSLOT] = {};
							if (fresh) {
								bool steamNow =
									(bb &
									 TB_STEAM) !=
									0;
								if (steamNow &&
								    !steamWasDown
									    [g_curSlot])
									steamDownMs[g_curSlot] =
										millis();
								if (!steamNow &&
								    steamWasDown
									    [g_curSlot] &&
								    millis() - steamDownMs[g_curSlot] <
									    1000u &&
								    USBDevice
									    .suspended()) {
									USBDevice
										.remoteWakeup();
									ledWakePulse();
									if (g_active)
										g_active->wakeEvent();
								}
								steamWasDown[g_curSlot] =
									steamNow;
							}
						}
						// Decode the report into the shared g_in (one source, read by every IController).
						g_in[g_curSlot].buttons = bb;
						// Global power-off chord: Steam + Y held 2 s -> shut the controller down (any mode). Detect on the raw
						// `bb` (pre-mask), time-based (poll rate varies), fires once per hold, re-arms only after release. While
						// held, mask Steam+Y out of g_in[g_curSlot].buttons so the press doesn't leak to the host -- in EVERY mode except
						// regular Steam (mode 0 forwards the raw 0x45 to Steam, which owns the Steam button). Runs before
						// onReport45 below so push modes (Xbox) see the mask too; stream modes read g_in in task() (also masked).
						{
							// Per-slot: each controller's Steam+Y hold is independent, so the debounce timer must
							// be per-slot. With multiple controllers, a shared timer gets reset every time ANOTHER
							// slot's poll (without the hold) runs -- and the round-robin poll cycles through every
							// used slot, so the timer never reaches 2s.
							static unsigned long
								offHoldMs[NSLOT] = {
									0, 0, 0,
									0
								};
							static bool offFired
								[NSLOT] = {
									false,
									false,
									false,
									false
								};
							if ((bb & (TB_STEAM |
								   TB_Y)) ==
							    (TB_STEAM | TB_Y)) {
								if (offHoldMs[g_curSlot] ==
								    0)
									offHoldMs[g_curSlot] =
										millis();
								else if (
									!offFired[g_curSlot] &&
									(unsigned long)(millis() -
											offHoldMs[g_curSlot]) >=
										2000u) {
									offFired[g_curSlot] =
										true;
									hapticSendShutdown();
								}
								if (g_usbMode !=
								    MODE_STEAM) {
									// stream modes read g_in
									g_in[g_curSlot]
										.buttons &=
										~(uint32_t)(TB_STEAM |
											    TB_Y);
									// push modes read btnsOf(rep): TB_Y in rep[2],
									((uint8_t *)
										 rep)
										[2] &=
										~(uint8_t)
											TB_Y;
									// TB_STEAM in rep[4]
									((uint8_t *)
										 rep)
										[4] &=
										~(uint8_t)(TB_STEAM >>
											   16);
								}
							} else {
								offHoldMs[g_curSlot] =
									0;
								offFired[g_curSlot] =
									false;
							}
						}
						g_in[g_curSlot].lx =
							(int16_t)s16off(rep, 8);
						g_in[g_curSlot].ly =
							(int16_t)s16off(rep,
									10);
						g_in[g_curSlot].rx =
							(int16_t)s16off(rep,
									12);
						g_in[g_curSlot].ry =
							(int16_t)s16off(rep,
									14);
						g_in[g_curSlot].lt =
							trigU8(u16off(rep, 4));
						// for the Switch digital-trigger threshold
						g_in[g_curSlot].rt =
							trigU8(u16off(rep, 6));
						g_in[g_curSlot].lpx =
							(int16_t)s16off(rep,
									16);
						g_in[g_curSlot].lpy =
							(int16_t)s16off(rep,
									18);
						g_in[g_curSlot].rpx =
							(int16_t)s16off(rep,
									22);
						g_in[g_curSlot].rpy =
							(int16_t)s16off(rep,
									24);
						// IMU lives at report bytes 0x22..0x2D (rep[34..45]). Decode it ONLY when a FULL 46-byte report was
						// actually received -- bounded by `end` (the received length), NOT sizeof(rfrx). The outer gate is
						// tlen>=28 (enough for buttons/sticks/pads, which end at rep[27]), so a short 0x45 (button-only, or
						// one whose IMU tail was lost) still passes it; without this guard imuFrom45 would read STALE bytes
						// past the received data and clobber g_in's gyro/accel. On a short frame, hold the last good IMU.
						if (tlen >= 46 &&
						    (size_t)(idx + 2) + 46 <=
							    (size_t)end)
							imuFrom45(
								rep,
								&g_in[g_curSlot]
									 .ax,
								&g_in[g_curSlot]
									 .ay,
								&g_in[g_curSlot]
									 .az,
								&g_in[g_curSlot]
									 .gx,
								&g_in[g_curSlot]
									 .gy,
								&g_in[g_curSlot]
									 .gz);
						// Mode-switch chord (all 4 back + face/dpad): don't leak the press to the host. g_in[g_curSlot].buttons stays
						// intact so the chord detector still fires; per-mode builders mask the same bits while back-4 held.
						if ((bb & CHORD_BACK4) ==
						    CHORD_BACK4) {
							((uint8_t *)rep)[2] &= ~(
								uint8_t)(TB_A |
									 TB_B |
									 TB_X |
									 TB_Y);
							((uint8_t *)rep)[3] &= ~(
								uint8_t)((TB_DDN |
									  TB_DRT |
									  TB_DLF |
									  TB_DUP) >>
									 8);
						}
						// Hand the report to the active controller. STREAM modes ignore it (they emit from task() reading
						// g_in); PUSH modes (Xbox, puck/lizard) build + send their host report here.
						if (g_active)
							g_active->onReport45(
								g_curSlot, rep,
								fresh, tlen);
						lastRep = rep;
						lastTlen = tlen;
						if (fresh)
							rfChannelNoteDecodedInput(
								g_curSlot, bb);
					} else if (ttype == 6 &&
						   (size_t)(idx + 2) + tlen <=
							   sizeof(rfrx) &&
						   tlen >= 2 &&
						   (rfrx[idx + 2] == 0x43 ||
						    rfrx[idx + 2] == 0x44)) {
						// Controller STATUS reports (0x43 = periodic power/battery, ~every 2s; 0x44 = status event). The real
						// puck forwards these verbatim (onAuxReport) -- that's how Steam reads battery; also snapshot the
						// battery % for the WebUSB panel.
						// [rid][body...]
						const uint8_t *rep =
							&rfrx[idx + 2];
						// 0x43 body[0] = ucChargeState (EChargeState), body[1] = ucBatteryLevel % (sniff-derived).
						// rep[0]=rid, rep[1]=body[0], rep[2]=body[1]. Snapshot both for the WebUSB panel and the
						// synthesized full-length 0x43 the puck pushes for SDL (see puck_hid.cpp task()).
						if (rep[0] == 0x43 &&
						    tlen >= 3 &&
						    g_curSlot >= 0 &&
						    g_curSlot < NSLOT) {
							g_batteryState[g_curSlot] =
								rep[1];
							g_battery[g_curSlot] =
								rep[2];
						}
						if (g_active)
							g_active->onAuxReport(
								g_curSlot,
								rep[0], rep + 1,
								(uint8_t)(tlen -
									  1));
					} else if (ttype == 6 &&
						   (size_t)(idx + 2) + tlen <=
							   sizeof(rfrx) &&
						   tlen >= 1) {
						// DIAGNOSTIC (beta-update RE): a type-6 HID-report TLV whose report id we
						// DON'T decode (not 0x45 input, not 0x43/0x44 status). If the new controller
						// firmware moved input off 0x45, its record shows up here. Log rid + full body,
						// rate-limited + non-blocking so it can't stall the loop. Remove once pinned.
						static unsigned long lastUnk =
							0;
						if (Serial.availableForWrite() >
							    150 &&
						    millis() - lastUnk >= 200) {
							lastUnk = millis();
							Serial.printf(
								"UNK rid=%02X tlen=%u: ",
								rfrx[idx + 2],
								tlen);
							for (uint8_t i = 0;
							     i < tlen; i++)
								Serial.printf(
									"%02X",
									rfrx[idx +
									     2 +
									     i]);
							Serial.println();
						}
					} else if ((ttype == 2 || ttype == 4) &&
						   tlen >= 1 &&
						   (size_t)(idx + 2) + tlen <=
							   sizeof(rfrx)) {
						// tag 0x02 ("control/status field") and tag 0x04 ("bulk data blob") --
						// docs/PROTOCOL.md sec 7.3. CONFIRMED from a real puck<->controller capture
						// (2026-08-10): tag-2 (`00 00 00 00`) is an immediate "request received" ack
						// for a landed feature-01 query; tag-4, arriving on a LATER poll, carries the
						// query's real answer as `[echoed report_id][len][payload]`. This is the reply
						// channel for the feature-01 queries (0x83/0xAE/0xED) puck_hid.cpp now relays
						// for real when rid==1 -- route it into whichever slot is waiting on exactly
						// this cmd (pendingQueryCmd, bonds.h), so a stray/late/mismatched tag-4 can't
						// clobber a slot that has moved on to a different query.
						const uint8_t *rec =
							&rfrx[idx + 2];
						if (ttype == 4 && tlen >= 2 &&
						    rec[0] != 0 &&
						    (uint16_t)(2 + rec[1]) <=
							    tlen &&
						    rec[1] <= 61 &&
						    g_curSlot >= 0 &&
						    g_curSlot < NSLOT &&
						    g_slot[g_curSlot].pendingQueryCmd ==
							    rec[0]) {
							// `resp`/`resp_len` are also written from handleSet (switch(cmd)) and
							// read from handleGet -- both on the usbd task. Match the PRIMASK-guard
							// pattern the rest of this file uses for usbd<->loop shared state
							// (relayEnqueue/hapLogAdd/fcPush) so a GET_FEATURE can't observe a torn
							// write mid-memcpy.
							Slot &S =
								g_slot[g_curSlot];
							uint32_t pm =
								__get_PRIMASK();
							__disable_irq();
							S.resp[0] = rec[0];
							S.resp[1] = rec[1];
							memcpy(S.resp + 2,
							       rec + 2, rec[1]);
							S.resp_len = 63;
							S.pendingQueryCmd = 0;
							__set_PRIMASK(pm);
						}
					}

					idx += tlen + 2;
				}
				// mode-switch chord (back4 + face/dpad): A=always Steam; B/X/Y=configurable (g_chordBtn[]);
				// dpad left/up/right/down=configurable (g_chordDpad[], defaults PS3/DS4/PS5/Switch). Debounced.
				{
					// Per-slot debounce: the chord input is per-slot (g_in[g_curSlot]), so the debounce counter
					// must be too. The shared-static form worked with 1 controller because slot 0 polled
					// back-to-back; with N>1, the round-robin poll cycles through every used slot, and the OTHER
					// slots' non-chord reports reset the counter on every iteration. The counter could never
					// reach 12 with multiple controllers, making the chord effectively dead.
					static uint8_t chWant[NSLOT] = {
						0xFF, 0xFF, 0xFF, 0xFF
					};
					static uint8_t chCnt[NSLOT] = { 0, 0, 0,
									0 };
					uint8_t want = 0xFF;
					if ((g_in[g_curSlot].buttons &
					     CHORD_BACK4) == CHORD_BACK4) {
						if (g_in[g_curSlot].buttons &
						    TB_A)
							want = MODE_STEAM;
						else if (g_in[g_curSlot].buttons &
							 TB_B)
							want = g_chordBtn[0];
						else if (g_in[g_curSlot].buttons &
							 TB_X)
							want = g_chordBtn[1];
						else if (g_in[g_curSlot].buttons &
							 TB_Y)
							want = g_chordBtn[2];
						else if (g_in[g_curSlot].buttons &
							 TB_DLF)
							want = g_chordDpad
								[CHD_LEFT];
						else if (g_in[g_curSlot].buttons &
							 TB_DUP)
							want = g_chordDpad
								[CHD_UP];
						else if (g_in[g_curSlot].buttons &
							 TB_DRT)
							want = g_chordDpad
								[CHD_RIGHT];
						else if (g_in[g_curSlot].buttons &
							 TB_DDN)
							want = g_chordDpad
								[CHD_DOWN];
					}
					if (want != 0xFF &&
					    want == chWant[g_curSlot]) {
						if (++chCnt[g_curSlot] >= 12 &&
						    want != g_usbMode &&
						    modeValid(want) &&
						    !USBDevice.suspended()) {
							// clean detach + reboot into the new mode (releases any held
							// input on the outgoing device -- see modeSwitchReboot)
							modeSwitchReboot(want);
						}
					} else {
						chWant[g_curSlot] = want;
						chCnt[g_curSlot] =
							(want != 0xFF) ? 1 : 0;
					}
				}
				// compact stream for rf_controller_ui.py -- NON-BLOCKING: skip if CDC TX is backed up (a blocking
				// Serial.print stalls the RF+USB loop -> jaggy input). One line/frame using the last record.
				if (lastRep && !g_connVerbose &&
				    !g_cmdCapture &&
				    Serial.availableForWrite() > 150 &&
				    millis() - g_lastStream >= 4) {
					g_lastStream = millis();
					Serial.print("I45 ");
					for (uint8_t i = 0; i < lastTlen; i++)
						Serial.printf("%02X",
							      lastRep[i]);
					Serial.println();
				}
			}
			if (g_connVerbose && Serial.availableForWrite() > 180) {
				Serial.printf(
					"%s CRX#%lu txtype%02X ch%u len%u: ",
					isF1 ? "<<<F1" :
					       (rtype == 0xF3 ? "  F3" :
								"  rx"),
					(unsigned long)g_connRx, payload[0], ch,
					rxlen);
				for (uint8_t i = 0;
				     i < (rxlen + 2 <= 66 ? rxlen + 2 : 66);
				     i++)
					Serial.printf("%02X", rfrx[i]);
				Serial.println();
			}
		} else
			rxlen = 0;
		// RX window expired with no packet at all
	} else {
		g_stNoRx[slot]++;
		g_qosBad++;
	}
	NRF_RADIO->TASKS_DISABLE = 1;
	RWAIT_DISABLED();
	NRF_RADIO->EVENTS_DISABLED = 0;
	if (plen && payload[0] == 0xE3 && g_curSlot >= 0 && g_curSlot < NSLOT)
		rfLinkQualityNotePoll(g_curSlot, rxlen != 0);
	return rxlen;
}

// Throttle: bonded slots that haven't replied in SLOT_COLD_MS are polled at most every SLOT_COLD_RETRY_MS
// instead of every cycle. This keeps the online controllers at full 250 Hz while barely touching offline ones.
#define SLOT_COLD_MS 5000u
#define SLOT_COLD_RETRY_MS 2000u
// Quiet tier: a slot that WAS replying but has been silent past SLOT_QUIET_MS (controller powering off, out
// of range) backs off to SLOT_QUIET_RETRY_MS retries instead of full-rate polling until SLOT_COLD_MS demotes
// it. Without this, a power-off left the slot at 250 Hz for 5 s with EVERY poll burning the whole g_rxWin
// (~2 ms) waiting for a reply that never comes -- with two controllers powered off together that is ~100%
// radio duty, the churn window the power-off watchdog hang (issue #72 repro) lives in. Recovery stays snappy:
// the first reply re-warms the slot to full rate, so a controller returning from a fade waits <= one retry.
#define SLOT_QUIET_MS 300u
#define SLOT_QUIET_RETRY_MS 50u
static unsigned long g_slotLastAttemptMs[NSLOT] = {};

// Drive the connected-mode sequence. The cycle gate fires once per g_pollUs (250 Hz); each fire
// polls EVERY warm slot back-to-back so all bonded controllers run at full rate regardless of count.
// "Cold" means the slot WAS connected but has been silent for > SLOT_COLD_MS; slots that have never
// replied stay warm so new controllers can connect at any time after boot. Cold slots retry every
// SLOT_COLD_RETRY_MS.
static void rfConnStep()
{
	int firstUsed = -1;
	for (int k = 0; k < NSLOT; k++)
		if (g_slot[k].used) {
			firstUsed = k;
			break;
		}
	if (firstUsed < 0) {
		g_curSlot = -1;
		return;
	}

	uint8_t ch = g_sessCh;
	// announce HOST AWAKE: E7 00 00, a few times. The real puck does NOT do this (the controller streams F1 to a
	// bare E3 with no E7) -- skipped unless g_e7announce ('n') re-enables the legacy handshake.
	if (g_connSt == 0) {
		g_curSlot = firstUsed;
		if (g_e7announce) {
			uint8_t p[3] = { 0xE7, 0x00, g_e7b };
			rfConnTx(ch, 0x01, p, 3);
			if (++g_connStep >= 4) {
				g_connSt = 1;
				g_connStep = 0;
				Serial.println(
					"# CONN: awake announced -> polling");
			}
		} else {
			// real-puck path: straight to the bare-E3 poll loop, no E7
			g_connSt = 1;
			g_connStep = 0;
		}
		return;
	}

	// Cycle gate: fires once per g_pollUs (250 Hz). On each fire we poll EVERY warm slot
	// back-to-back so all bonded controllers run at full rate -- the real puck services all
	// controllers per cycle. Polling one-slot-per-call instead tied the per-slot rate to the
	// loop frequency AND split it across slots, collapsing 2 controllers to ~90 Hz.
	uint32_t nowUs = micros();
	if ((uint32_t)(nowUs - g_lastPollUs) < (uint32_t)g_pollUs)
		return;
	{
		// Cycle period stat: time between gate fires (= each slot's poll period, intended g_pollUs).
		static uint32_t lastCycleUs = 0;
		if (lastCycleUs) {
			g_pollDtSum += (uint32_t)(nowUs - lastCycleUs);
			g_pollDtCnt++;
		}
		lastCycleUs = nowUs;
	}
	g_lastPollUs += g_pollUs;
	if ((uint32_t)(nowUs - g_lastPollUs) >= (uint32_t)g_pollUs)
		g_lastPollUs = nowUs; // catch-up reset when a cycle overran

	unsigned long nowMs = millis();

	// Inline poll helper; emits E7 re-assert (every 32 polls, bounded reply window so a
	// missed F3 doesn't burn the whole slot budget), queues haptics, flushes relay, sends E3 GET.
	auto doPoll = [&](int k) {
		g_slotLastAttemptMs[k] = nowMs;
		g_curSlot = k;
		// re-assert awake/version every 32 polls (legacy; real puck never sends E7 -- gated by g_e7announce)
		if (g_e7announce && (g_connPoll & 0x1F) == 0) {
			uint8_t pa[3] = { 0xE7, 0x00, g_e7b };
			rfConnTx(ch, 0x01, pa, 3, 600);
		}
		rfConnQueueHapticRelay();
		{
			uint8_t rs1 =
				(uint8_t)((((g_relayPid[k]++) & 3) << 1) | 1);
			if (rfConnFlushRelay(ch, rs1))
				g_stRelay[k]++;
		}
		// per-slot PID cycle so each bonded controller's polls stay distinct
		uint8_t pidv = g_pollPid[k]++;
		uint8_t s1 = (g_e3mode == 1) ?
				     (uint8_t)(((pidv & 3) << 1) | 1) :
			     (g_e3mode == 2) ? (uint8_t)((pidv & 3) << 1) :
					       0x07;
		uint8_t rx;
		if (g_pollGet) {
			// legacy: E3 + TLV [len=02][subtype=01 GET][id=0x45][param]
			uint8_t p[5] = { 0xE3, 0x02, 0x01, 0x45, g_getParam };
			rx = rfConnTx(ch, s1, p, 5);
		} else {
			// real puck: BARE E3 (just the opcode) -- the controller streams F1 to any E3 ack
			uint8_t p[1] = { 0xE3 };
			rx = rfConnTx(ch, s1, p, 1);
		}
		if (rx)
			g_chF1[0]++;
		g_stPoll[k]++; // one true poll cycle for this slot
		g_connPoll++;
	};

	bool linkUp = anySlotLinkUp();
	if (!linkUp) {
		// (RE)ACQUIRE MODE -- nothing is linked. Poll used slots to catch a (re)connecting controller fast,
		// but ROUND-ROBIN: exactly ONE slot per cycle, so radio duty stays bounded to a single ~g_rxWin no-reply
		// wait per cycle no matter how many bonds are absent.
		//
		// Why not poll every absent slot per cycle: doing so was the fix for the solid-light reconnect livelock
		// (a slot silent > SLOT_COLD_MS had dropped to a 2s poll that kept missing the controller's re-adopt
		// window), BUT with two bonds absent it put TWO full ~g_rxWin no-reply waits + the every-loop beaconing
		// on every cycle -- a radio-duty spike that starved loop()/USB into a watchdog reset. The puck then
		// re-enumerated on every disconnect, so Steam saw a "new controller" and popped its setup wizard every
		// time. One slot per cycle keeps acquire snappy (N bonds => each polled at 250/N Hz, still far faster
		// than the old 2s cold cadence) while capping duty. A single used slot is still polled every cycle.
		static int acqIdx = 0;
		for (int n = 0; n < NSLOT; n++) {
			int k = (acqIdx + n) % NSLOT;
			if (g_slot[k].used) {
				acqIdx = (k + 1) % NSLOT;
				doPoll(k);
				break;
			}
		}
	} else {
		// CONNECTED -- at least one controller is live. Poll every WARM slot per cycle (all bonded controllers
		// at full rate -- the real puck services them all per cycle), and throttle the SILENT ones so they don't
		// steal reply windows from the live controller(s) (the issue-#72 radio-duty concern):
		//   - "cold": WAS connected but silent > SLOT_COLD_MS (controller powered off / out of range);
		//   - "quiet": briefly silent (fade) -> back off to SLOT_QUIET_RETRY_MS until it recovers or goes cold;
		//   - "phantom": NEVER replied while another controller is live (e.g. a stale bond from a cloned backup).
		for (int k = 0; k < NSLOT; k++) {
			if (!g_slot[k].used)
				continue;
			bool everReplied = g_connReplyMs[k] != 0;
			unsigned long silentMs =
				everReplied ? (nowMs - g_connReplyMs[k]) : 0;
			bool cold = everReplied && silentMs > SLOT_COLD_MS;
			bool quiet = everReplied && !cold &&
				     silentMs > SLOT_QUIET_MS;
			bool phantom = !everReplied;
			unsigned long retry = (cold || phantom) ?
						      SLOT_COLD_RETRY_MS :
					      quiet ? SLOT_QUIET_RETRY_MS :
						      0;
			if (retry && nowMs - g_slotLastAttemptMs[k] < retry)
				continue;
			doPoll(k);
		}
	}
}

void rfLinkTask()
{
	rfChannelHandoffTask();
	if (rfChannelHandoffOwnsRadio())
		return;
	rfStartupChannelTask();
	// Poll before beacons: the cycle gate must fire as close to its
	// 4 ms deadline as possible; beacon TX (up to 3.6 ms for 4 slots)
	// runs after so it never delays the current poll.
	if (g_connOn && millis() - g_connCooldown > 2500) {
		rfConnStep();
	} // connected-mode: poll controller, read input

	// Host-frame beacon: sent continuously, INCLUDING while connected. The controller uses the periodic E1 (the
	// real puck's per-hop-cycle announce) to stay synced and keep answering polls at full rate; suppressing it
	// drops the reply rate from ~210/s to ~38/s. Paused only during the post-disconnect cooldown so a controller
	// that's powering off isn't immediately re-woken/reconnected.
	if (g_rfHost && millis() - g_connCooldown > 2500) {
		bool connNow = anySlotLinkUp();
		// session keepalive on the clean channel: every loop while connecting (fast), every 25ms once connected
		// (every-loop beaconing also hammers the session ch and steals reply slots from the poll). The real puck
		// sends NO E1 on its session channel; gated by g_e1keepalive ('m') so this can be A/B'd on hardware --
		// but it stays ON by default because OpenPuck's shared-address model relies on E1 to advertise the session.
		if (g_e1keepalive &&
		    millis() - g_lastSessBeacon >= (connNow ? 25u : 0u)) {
			g_lastSessBeacon = millis();
			g_rfCh = g_sessCh;
			for (int s = 0; s < NSLOT; s++)
				rfHostFrameOnce(s, false);
		}
		// discovery beacon on ch2 (where a searching controller looks): every loop when nothing is
		// connected (fastest cold-boot/late-joiner connect), every 200ms once ANY controller is linked.
		// Matches main: while a slot is connected, ch2 discovery shares g_sessCh's air budget, so beaconing
		// faster than 200ms (the old allUp-gated 40ms path) just steals reply windows from the connected
		// controller -> reply-rate sag -> >1500ms gaps -> spurious hapticOnReconnect re-init. A late joiner
		// still enumerates within ~1s at 200ms.
		if (millis() - g_lastDisc >= (connNow ? 200u : 0u)) {
			g_lastDisc = millis();
			g_rfCh = 2;
			for (int s = 0; s < NSLOT; s++)
				rfHostFrameOnce(s, true);
		}
	}

	// Release stale input on a per-slot link-drop edge. g_in[s] is refreshed ONLY
	// by the 0x45 decode on a fresh reply, so once a controller goes silent the
	// last-decoded input is frozen in place: STREAM modes (Switch Hori/Pro, PS5,
	// DS4-gyro) keep emitting it every cycle, and PUSH modes (Steam/puck, Xbox)
	// leave the host holding their last report -- a feathered trigger, or a
	// "release" frame that was the one lost in the gap, stays asserted for the
	// whole outage (the stuck / false-trigger symptom, most visible on the analog
	// triggers). On the up->down edge, zero g_in[s] (neutralizes the stream modes)
	// and push one synthetic neutral 0x45 through the active push mode's normal
	// build path (neutralizes Steam/puck -- including held lizard keys/mouse --
	// and Xbox; a no-op for stream modes, which don't override onReport45). The
	// next real 0x45 on reconnect refills everything. PS3 already streams its own
	// neutral when no slot is live, so it needs nothing here.
	{
		static bool wasUp[NSLOT] = {};
		static const uint8_t neutral45[46] = { 0x45 };
		for (int s = 0; s < NSLOT; s++) {
			bool up = g_slot[s].used && g_connReplyMs[s] != 0 &&
				  (millis() - g_connReplyMs[s] < 300u);
			if (wasUp[s] && !up) {
				memset(&g_in[s], 0, sizeof g_in[s]);
				if (g_active)
					g_active->onReport45(s, neutral45, true,
							     sizeof neutral45);
			}
			wasUp[s] = up;
		}
	}

	// ---- RF stall self-heal -------------------------------------------------------------------------------
	// Field wedge: the controllers stay powered and show a SOLID (connected) light, the puck keeps issuing E3
	// polls + E1 beacons (radio TX is provably alive -- a power-cycled controller still re-adopts the session
	// and goes solid against this puck), yet NOT ONE slot decodes a reply for seconds. The link reads down, no
	// input reaches the host, and it never recovers on its own -- only a puck REPLUG fixes it. rfConfig() already
	// re-disables (TASKS_DISABLE) the radio before every poll, so whatever this is survives a TASKS_DISABLE; the
	// only thing that clears it is a full peripheral reset -- exactly what the replug does. So when the WHOLE
	// link has been silent past RF_STALL_MS while we're still actively polling a slot that WAS connected, do the
	// replug's job for the radio: power-cycle NRF_RADIO (POWER=0/1 clears every RADIO register; the next
	// rfConnTx/rfHostFrameOnce re-applies all config via rfConfig()) and drop the connected-mode latches so
	// polling/beaconing resume and the handshake re-runs from a clean slate. Gated on EVERY used+previously-
	// connected slot being stalled, so one controller walking off (others still live) never trips it; the
	// cooldown gate keeps it from firing while a controller is intentionally powering off; rate-limited so it
	// cannot thrash. g_rfStallRecover is surfaced to the panel so the wedge -- and its recovery -- is observable.
	if (g_connOn && g_curSlot >= 0 && millis() - g_connCooldown > 2500) {
		static unsigned long lastRecoverMs = 0;
		static uint8_t consecStall = 0;
		unsigned long nowMs2 = millis();
		bool anyEverConnected = false, allStalled = true;
		for (int s = 0; s < NSLOT; s++) {
			if (!(g_slot[s].used && g_connReplyMs[s] != 0))
				continue;
			anyEverConnected = true;
			if ((uint32_t)(nowMs2 - g_connReplyMs[s]) < RF_STALL_MS)
				allStalled = false;
		}
		// Any slot alive -> a recovery worked (or we were never stalled): reset the give-up counter.
		if (!allStalled)
			consecStall = 0;
		// Back off once we've power-cycled RF_STALL_GIVEUP times with nothing coming back (controller absent,
		// not a wedged radio): slow the retry to RF_STALL_BACKOFF_MS instead of hammering every RF_RECOVER_MS.
		uint32_t interval = (consecStall < RF_STALL_GIVEUP) ?
					    RF_RECOVER_MS :
					    RF_STALL_BACKOFF_MS;
		if (anyEverConnected && allStalled &&
		    (uint32_t)(nowMs2 - lastRecoverMs) > interval) {
			lastRecoverMs = nowMs2;
			g_rfStallRecover++;
			faultDiagTrace(FR_HEAL, g_rfStallRecover);
			if (consecStall < 255)
				consecStall++;
			NRF_RADIO->POWER = 0;
			NRF_RADIO->POWER = 1;
			g_connCooldown = 0;
			g_connSt = 0;
			g_connStep = 0;
			if (Serial.availableForWrite() > 110)
				Serial.printf(
					"# RF STALL (#%u consec=%u%s) -> radio power-cycle + reconnect\n",
					g_rfStallRecover, consecStall,
					consecStall >= RF_STALL_GIVEUP ?
						" BACKOFF" :
						"");
		}
	}

	{
		// remote wakeup on new RF controller connection (any slot)
		static bool wasRfConn = false;
		bool nowRfConn = anySlotLinkUp();
		if (nowRfConn && !wasRfConn && USBDevice.suspended()) {
			USBDevice.remoteWakeup();
			ledWakePulse();
			// post-resume nudge (host needs real input to actually wake)
			if (g_active)
				g_active->wakeEvent();
		}
		wasRfConn = nowRfConn;
	}
	// Evaluate the completed link-quality window and request recovery only through the policy gate.
	rfLinkQualityTask();
	rfAmbientSurveyTask();
	if (g_connOn && millis() - g_stMs >= 1000) {
		// Per-slot snapshots first (blob v13 / per-controller panel stats), then the legacy aggregates as
		// their sums (serial stat line + pre-v13 blob fields).
		uint32_t tPoll = 0, tF1 = 0, tNew = 0, tCrc = 0, tNoRx = 0,
			 tRelay = 0;
		for (int s = 0; s < NSLOT; s++) {
			g_slotPollsps[s] = (uint16_t)g_stPoll[s];
			g_slotF1ps[s] = (uint16_t)g_stF1[s];
			g_slotNewps[s] = (uint16_t)g_stNew[s];
			g_slotCrcps[s] =
				(uint8_t)(g_stCrc[s] > 255 ? 255 : g_stCrc[s]);
			g_slotNoRxps[s] = (uint8_t)(g_stNoRx[s] > 255 ?
							    255 :
							    g_stNoRx[s]);
			g_slotRelayps[s] = (uint8_t)(g_stRelay[s] > 255 ?
							     255 :
							     g_stRelay[s]);
			tPoll += g_stPoll[s];
			tF1 += g_stF1[s];
			tNew += g_stNew[s];
			tCrc += g_stCrc[s];
			tNoRx += g_stNoRx[s];
			tRelay += g_stRelay[s];
			g_stPoll[s] = g_stF1[s] = g_stNew[s] = 0;
			g_stCrc[s] = g_stNoRx[s] = g_stRelay[s] = 0;
		}
		g_f1ps = (uint16_t)tF1;
		g_newps = (uint16_t)tNew;
		g_pollsps = (uint16_t)tPoll;
		g_relayps = (uint16_t)tRelay;
		g_crcps = (uint16_t)tCrc;
		g_norxps = (uint16_t)tNoRx;
		g_pollPeriodUs =
			g_pollDtCnt ? (uint16_t)(g_pollDtSum / g_pollDtCnt) : 0;
		g_pollDtSum = 0;
		g_pollDtCnt = 0;
		// Require room for the WHOLE line (~85B): CDC write() has NO timeout -- it spins yield() until the host
		// drains, so a guard smaller than the line lets write() start, fill the FIFO mid-line, then spin loop()
		// forever if the serial host stalls -> watchdog hang. (This exact line, guarded at >70 for an ~85B line,
		// was the confirmed diagnostic-induced hang: the capture ended truncated mid-"# stat".)
		if (Serial.availableForWrite() > 130)
			Serial.printf(
				"# stat polls=%lu/s F1=%lu/s new=%lu/s F3=%lu/s(v%d) e7b=%u crcfail=%lu noRx=%lu slot=%d\n",
				(unsigned long)tPoll, (unsigned long)tF1,
				(unsigned long)tNew, (unsigned long)g_stF3,
				(int8_t)g_connF3v, g_e7b, (unsigned long)tCrc,
				(unsigned long)tNoRx, g_curSlot);
		g_stF3 = 0;
		g_chF1[0] = g_chF1[1] = g_chF1[2] = 0;
		g_stMs = millis();
	}
}
