"""Generate PostMessage deferral pattern diagram as PNG."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_PATH = Path(__file__).resolve().parent.parent / "images" / "natlink_postmsg_deferral.png"

# --- Config ---
SCALE = 2
_W, _H = 1500, 1800
W, H = _W * SCALE, _H * SCALE
BG = "#1e1e2e"
BOX_FILL = "#313244"
BOX_OUTLINE = "#585b70"
ACCENT = "#89b4fa"
ACCENT2 = "#a6e3a1"
ACCENT3 = "#f9e2af"
RED = "#f38ba8"
MAUVE = "#cba6f7"
PEACH = "#fab387"
TEXT = "#cdd6f4"
SUBTLE = "#6c7086"
ARROW = "#7f849c"
DARK_FILL = "#2a2a3a"

FONT_TITLE = ImageFont.truetype("segoeui.ttf", 28 * SCALE)
FONT_SECTION = ImageFont.truetype("segoeuib.ttf", 20 * SCALE)
FONT_BOLD = ImageFont.truetype("segoeuib.ttf", 15 * SCALE)
FONT = ImageFont.truetype("segoeui.ttf", 14 * SCALE)
FONT_SMALL = ImageFont.truetype("segoeui.ttf", 12 * SCALE)
FONT_MONO = ImageFont.truetype("consola.ttf", 12 * SCALE)
FONT_MONO_B = ImageFont.truetype("consolab.ttf", 13 * SCALE)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# --- Helpers (all coords are in logical units, scaled by SCALE) ---
def s(*vals):
    """Scale one or more values."""
    if len(vals) == 1:
        return int(vals[0] * SCALE)
    return tuple(int(v * SCALE) for v in vals)

def rbox(x, y, w, h, fill=BOX_FILL, outline=BOX_OUTLINE, r=10, lw=2):
    x, y, w, h, r, lw = s(x), s(y), s(w), s(h), s(r), max(1, s(lw))
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=outline, width=lw)

def ctext(text, x, y, w, font=FONT_BOLD, fill=TEXT):
    x, y, w = s(x), s(y), s(w)
    bb = d.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    d.text((x + (w - tw) // 2, y), text, font=font, fill=fill)

def txt(text, x, y, font=FONT, fill=TEXT):
    d.text((s(x), s(y)), text, font=font, fill=fill)

def arrow_down(x, y1, y2, color=ARROW, w=2):
    x, y1, y2 = s(x), s(y1), s(y2)
    d.line([(x, y1), (x, y2)], fill=color, width=max(1, s(w)))
    a = s(5)
    d.polygon([(x - a, y2 - s(7)), (x + a, y2 - s(7)), (x, y2)], fill=color)

def arrow_right(x1, x2, y, color=ARROW, w=2):
    x1, x2, y = s(x1), s(x2), s(y)
    d.line([(x1, y), (x2, y)], fill=color, width=max(1, s(w)))
    a = s(5)
    d.polygon([(x2 - s(7), y - a), (x2 - s(7), y + a), (x2, y)], fill=color)

def arrow_left(x1, x2, y, color=ARROW, w=2):
    x1, x2, y = s(x1), s(x2), s(y)
    d.line([(x1, y), (x2, y)], fill=color, width=max(1, s(w)))
    a = s(5)
    d.polygon([(x2 + s(7), y - a), (x2 + s(7), y + a), (x2, y)], fill=color)

def arrow_bend_right(x1, y1, x2, y2, color=ARROW, w=2):
    x1, y1, x2, y2 = s(x1), s(y1), s(x2), s(y2)
    lw = max(1, s(w))
    d.line([(x1, y1), (x1, y2)], fill=color, width=lw)
    d.line([(x1, y2), (x2, y2)], fill=color, width=lw)
    a = s(5)
    d.polygon([(x2 - s(7), y2 - a), (x2 - s(7), y2 + a), (x2, y2)], fill=color)

def dashed_h(x1, x2, y, color=SUBTLE, w=1):
    x1, x2, y = s(x1), s(x2), s(y)
    for x in range(x1, x2, s(12)):
        d.line([(x, y), (min(x + s(6), x2), y)], fill=color, width=max(1, s(w)))

# ============================================================
# TITLE
# ============================================================
ctext("PostMessage Deferral Pattern", 0, 20, _W, font=FONT_TITLE, fill=TEXT)
ctext("How COM sink callbacks avoid deadlock by deferring Python execution", 0, 56, _W, font=FONT, fill=SUBTLE)

# ============================================================
# SECTION 1: Main Flow Diagram
# ============================================================
SEC1_Y = 90
ctext("Message Flow", 0, SEC1_Y, _W, font=FONT_SECTION, fill=ACCENT)

# Three swim lanes
LANE_W = 360
GAP = 40
LANE1_X = 80                          # Dragon (COM RPC)
LANE2_X = LANE1_X + LANE_W + GAP     # Sink Callbacks
LANE3_X = LANE2_X + LANE_W + GAP     # Main Thread (Pump)

LANE_TOP = SEC1_Y + 30
LANE_H = 560

# Lane headers
for lx, label, color in [
    (LANE1_X, "Dragon (COM RPC)", ACCENT2),
    (LANE2_X, "Sink Callbacks", ACCENT3),
    (LANE3_X, "Main Thread (Pump)", ACCENT),
]:
    rbox(lx, LANE_TOP, LANE_W, 30, fill="#3b3d52", outline=color)
    ctext(label, lx, LANE_TOP + 6, LANE_W, font=FONT_BOLD, fill=color)

# Vertical lane lines
for lx in [LANE1_X + LANE_W // 2, LANE2_X + LANE_W // 2, LANE3_X + LANE_W // 2]:
    for yy in range(LANE_TOP + 35, LANE_TOP + LANE_H, 8):
        d.line([(s(lx), s(yy)), (s(lx), s(min(yy + 4, LANE_TOP + LANE_H)))], fill="#3b3d52", width=s(1))

# Step 1: Dragon fires PhraseFinish
s1y = LANE_TOP + 60
rbox(LANE1_X + 20, s1y, LANE_W - 40, 50, fill="#2a3a2a", outline=ACCENT2)
ctext("PhraseFinish()", LANE1_X + 20, s1y + 6, LANE_W - 40, font=FONT_MONO_B, fill=ACCENT2)
txt("RPC call to sink", LANE1_X + 20, s1y + 28, font=FONT_SMALL, fill=SUBTLE)

# Arrow to sink
arrow_right(LANE1_X + LANE_W - 20, LANE2_X + 20, s1y + 25, color=ACCENT2)

# Step 2: Sink processes
s2y = s1y
rbox(LANE2_X + 10, s2y, LANE_W - 20, 120, fill="#3a3520", outline=ACCENT3)
txt("1. Parse SRPHRASEW", LANE2_X + 20, s2y + 8, font=FONT_MONO, fill=ACCENT3)
txt("2. Wrap in ComResObj", LANE2_X + 20, s2y + 28, font=FONT_MONO, fill=ACCENT3)
txt("3. AddRef(pUnknown)", LANE2_X + 20, s2y + 48, font=FONT_MONO, fill=ACCENT3)
txt("4. pause_recog++", LANE2_X + 20, s2y + 68, font=FONT_MONO, fill=RED)
txt("5. PostMessage", LANE2_X + 20, s2y + 88, font=FONT_MONO, fill=ACCENT)
txt("   (WM_SENDRESULTS)", LANE2_X + 20, s2y + 103, font=FONT_MONO, fill=ACCENT)

# Arrow: PostMessage to hidden window
s3y = s2y + 90
arrow_right(LANE2_X + LANE_W - 10, LANE3_X + 20, s3y + 7, color=ACCENT)

# Step 3: return 0
s4y = s2y + 128
rbox(LANE2_X + 30, s4y, LANE_W - 60, 32, fill="#2a3a2a", outline=ACCENT2)
ctext("return 0", LANE2_X + 30, s4y + 4, LANE_W - 60, font=FONT_MONO_B, fill=ACCENT2)

# Arrow back to Dragon
arrow_left(LANE2_X + 30, LANE1_X + LANE_W - 20, s4y + 16, color=ACCENT2)

# Dragon unblocks
s5y = s4y + 4
rbox(LANE1_X + 30, s5y, LANE_W - 60, 28, fill="#2a3a2a", outline="#585b70")
ctext("COM call returns", LANE1_X + 30, s5y + 4, LANE_W - 60, font=FONT_SMALL, fill=SUBTLE)

# Step 4: Main thread receives
s6y = s3y + 40
rbox(LANE3_X + 10, s6y, LANE_W - 20, 140, fill=DARK_FILL, outline=ACCENT)
txt("MsgWait unblocks", LANE3_X + 20, s6y + 8, font=FONT_MONO, fill=ACCENT)
txt("PeekMessage", LANE3_X + 20, s6y + 30, font=FONT_MONO, fill=TEXT)
txt("  (WM_SENDRESULTS)", LANE3_X + 20, s6y + 46, font=FONT_MONO, fill=TEXT)
txt("  trigger_message()", LANE3_X + 20, s6y + 64, font=FONT_MONO, fill=SUBTLE)
txt("DispatchMessage", LANE3_X + 20, s6y + 84, font=FONT_MONO, fill=TEXT)
txt("  → wndproc → handler", LANE3_X + 20, s6y + 100, font=FONT_MONO, fill=SUBTLE)
txt("  → stash_pop(key)", LANE3_X + 20, s6y + 118, font=FONT_MONO, fill=ACCENT3)

# Step 5: User callback
s7y = s6y + 152
rbox(LANE3_X + 10, s7y, LANE_W - 20, 95, fill="#2a2a40", outline=MAUVE)
txt("_do_phrase_finish()", LANE3_X + 20, s7y + 8, font=FONT_MONO_B, fill=MAUVE)
txt("  → user gotResults()", LANE3_X + 20, s7y + 30, font=FONT_MONO, fill=TEXT)
txt("  → pause_recog--", LANE3_X + 20, s7y + 50, font=FONT_MONO, fill=RED)
txt("  → if 0: process", LANE3_X + 20, s7y + 68, font=FONT_MONO, fill=ACCENT2)
txt("    deferred Paused", LANE3_X + 20, s7y + 82, font=FONT_MONO, fill=ACCENT2)

# Step 6: Resume
s8y = s7y + 105
rbox(LANE3_X + 20, s8y, LANE_W - 40, 32, fill="#2a3a2a", outline=ACCENT2)
ctext("Resume(cookie)", LANE3_X + 20, s8y + 6, LANE_W - 40, font=FONT_MONO_B, fill=ACCENT2)

# Arrow back to Dragon
arrow_left(LANE3_X + 20, LANE1_X + LANE_W - 20, s8y + 16, color=ACCENT2)

# Dragon resumes
rbox(LANE1_X + 20, s8y, LANE_W - 40, 32, fill="#2a3a2a", outline=ACCENT2)
ctext("Recognition resumes", LANE1_X + 20, s8y + 6, LANE_W - 40, font=FONT_SMALL, fill=ACCENT2)

# ============================================================
# SECTION 2: Stash Mechanism
# ============================================================
SEC2_Y = LANE_TOP + LANE_H + 40
ctext("Stash Mechanism", 0, SEC2_Y, _W, font=FONT_SECTION, fill=ACCENT3)

sy = SEC2_Y + 30
# Stash flow
rbox(80, sy, 300, 90, outline=ACCENT3)
txt("stash_put(data)", 100, sy + 8, font=FONT_MONO_B, fill=ACCENT3)
txt("  key = next(itertools.count(1))", 100, sy + 28, font=FONT_MONO, fill=TEXT)
txt("  _stash[key] = data", 100, sy + 44, font=FONT_MONO, fill=TEXT)
txt("  return key  → lparam", 100, sy + 62, font=FONT_MONO, fill=SUBTLE)

arrow_right(380, 480, sy + 45, color=ACCENT3)

rbox(480, sy, 300, 90, outline=ACCENT3)
txt("PostMessageW(hwnd, WM, wp, key)", 500, sy + 8, font=FONT_MONO_B, fill=ACCENT3)
txt("  if fails:", 500, sy + 30, font=FONT_MONO, fill=RED)
txt("    _stash.pop(key)  # cleanup", 500, sy + 46, font=FONT_MONO, fill=RED)
txt("    return False", 500, sy + 62, font=FONT_MONO, fill=RED)

arrow_right(780, 930, sy + 45, color=ACCENT3)

rbox(930, sy, 350, 90, outline=ACCENT3)
txt("stash_pop(key)", 950, sy + 8, font=FONT_MONO_B, fill=ACCENT3)
txt("  data = _stash.pop(key, None)", 950, sy + 28, font=FONT_MONO, fill=TEXT)
txt("  return data  # or None", 950, sy + 44, font=FONT_MONO, fill=TEXT)
txt("  (consumed, removed from dict)", 950, sy + 62, font=FONT_MONO, fill=SUBTLE)

# Data types
sy2 = sy + 105
rbox(80, sy2, 1340, 55, fill=DARK_FILL, outline="#4a4d68")
txt("Stashed payloads:", 100, sy2 + 5, font=FONT_BOLD, fill=TEXT)
txt("WM_SENDRESULTS: (gram_handle, dwFlags, ComResObj)    WM_PAUSED: qCookie    WM_PHRASE_HYPO: (gram_handle, words)",
    100, sy2 + 24, font=FONT_MONO, fill=SUBTLE)
txt("WM_DICT_TEXTCHANGED: (dict_handle, old_start, old_end, text, sel_start, sel_end)    WM_DEFERRED_CALL: (fn, args)",
    100, sy2 + 38, font=FONT_MONO, fill=SUBTLE)

# ============================================================
# SECTION 3: pause_recog Guard
# ============================================================
SEC3_Y = sy2 + 75
ctext("pause_recog Guard", 0, SEC3_Y, _W, font=FONT_SECTION, fill=RED)

py = SEC3_Y + 30
# Timeline boxes
steps_pr = [
    ("PhraseFinish #1 arrives", "pause_recog: 0 → 1", ACCENT3, 200),
    ("PhraseFinish #2 arrives", "pause_recog: 1 → 2", ACCENT3, 200),
    ("Paused(cookie) arrives", "pause_recog > 0\n→ defer cookie", RED, 180),
    ("WM_SENDRESULTS #1\ndispatched → user callback", "pause_recog: 2 → 1", ACCENT, 220),
    ("WM_SENDRESULTS #2\ndispatched → user callback", "pause_recog: 1 → 0\n→ process deferred!", ACCENT, 220),
    ("Begin callback\n+ Resume(cookie)", "Dragon unfreezes", ACCENT2, 180),
]

px = 50
for label, detail, color, bw in steps_pr:
    rbox(px, py, bw, 58, outline=color, fill=DARK_FILL)
    txt(label, px + 8, py + 4, font=FONT_SMALL, fill=color)
    txt(detail, px + 8, py + 32, font=FONT_SMALL, fill=SUBTLE)
    if px + bw < 50 + sum(s[3] + 15 for s in steps_pr) - 15:
        arrow_right(px + bw, px + bw + 15, py + 29, color=ARROW)
    px += bw + 15

# ============================================================
# SECTION 4: Sync Op Message Stack
# ============================================================
SEC4_Y = SEC3_Y + 115
ctext("Sync Op Message Stack  (mimic / playString / execScript)", 0, SEC4_Y, _W, font=FONT_SECTION, fill=MAUVE)

sy = SEC4_Y + 30

# Left: the blocking pattern
rbox(80, sy, 600, 190, outline=MAUVE)
txt("_sync_op() pattern:", 100, sy + 8, font=FONT_BOLD, fill=MAUVE)
lines = [
    ("code = next_client_code()", TEXT),
    ("entry = push_message_entry(WM_xxx, code)", TEXT),
    ("", TEXT),
    ("message_loop(entry, start=COM_call):", ACCENT),
    ("  dispatch_pending()    # flush Paused→Resume", SUBTLE),
    ("  start()               # issue COM call", TEXT),
    ("  while not entry.triggered:", TEXT),
    ("    MsgWaitForMultipleObjects(timeout)", SUBTLE),
    ("    PeekMessage → trigger_message()  # BEFORE dispatch", ACCENT3),
    ("    DispatchMessage → wndproc → trigger_message()", ACCENT3),
    ("  return entry.lparam   # error info or 0=ok", ACCENT2),
]
for i, (line, color) in enumerate(lines):
    txt(line, 100, sy + 28 + i * 15, font=FONT_MONO, fill=color)

# Right: pre-consumed case
rbox(720, sy, 560, 190, outline=PEACH)
txt("Pre-consumed case:", 740, sy + 8, font=FONT_BOLD, fill=PEACH)
lines2 = [
    "COM outgoing calls (e.g. RecognitionMimic)",
    "trigger a modal message loop inside ole32.dll.",
    "",
    "This loop may DispatchMessage our WM_MIMICDONE",
    "before message_loop() ever calls PeekMessage.",
    "",
    "trigger_message() is called from BOTH:",
    "  1. wndproc handler (during any Dispatch)",
    "  2. PeekMessage loop (before Dispatch)",
    "",
    "So entry gets triggered either way.",
    "message_loop checks entry.triggered at top.",
]
for i, line in enumerate(lines2):
    color = PEACH if "trigger_message" in line or "BOTH" in line else SUBTLE
    txt(line, 740, sy + 28 + i * 15, font=FONT_MONO, fill=color)

# ============================================================
# SECTION 5: All Message Types
# ============================================================
SEC5_Y = SEC4_Y + 240
ctext("Message Types (WM_USER + offset)", 0, SEC5_Y, _W, font=FONT_SECTION, fill=TEXT)

sy = SEC5_Y + 30
msgs = [
    ("345", "WM_PLAYBACK", "playString / playEvents done", "_action_sink::Playback{Done,Aborted}", ACCENT2),
    ("346", "WM_EXECUTION", "execScript done / aborted", "_action_sink::Execution{Done,Aborted}", ACCENT2),
    ("347", "WM_ATTRIBCHANGED", "mic, user, playback state change", "_engine_sink::AttribChanged2", ACCENT3),
    ("348", "WM_PAUSED", "recognition begin (→ Begin cb + Resume)", "_engine_sink::Paused", RED),
    ("349", "WM_SENDRESULTS", "grammar recognition result", "_grammar_sink::PhraseFinish", ACCENT),
    ("350", "WM_MIMICDONE", "recognitionMimic completed", "_engine_sink::MimicDone", MAUVE),
    ("351", "WM_PHRASE_HYPO", "partial hypothesis (Python-only)", "_grammar_sink::PhraseHypothesis", SUBTLE),
    ("352", "WM_DICT_TEXTCHANGED", "dictation text changed (Python-only)", "_dict_sink::{TextSelChanged,TextChanged}", SUBTLE),
    ("353", "WM_DEFERRED_CALL", "cross-thread callable (Python-only)", "_hidden_wnd::push_to_com", SUBTLE),
]

# Header
rbox(80, sy, 1340, 24, fill="#3b3d52", outline="#4a4d68")
txt("Offset", 95, sy + 4, font=FONT_BOLD, fill=TEXT)
txt("Name", 160, sy + 4, font=FONT_BOLD, fill=TEXT)
txt("Purpose", 450, sy + 4, font=FONT_BOLD, fill=TEXT)
txt("Source", 950, sy + 4, font=FONT_BOLD, fill=TEXT)

sy += 28
for offset, name, purpose, source, color in msgs:
    rbox(80, sy, 1340, 22, fill=DARK_FILL, outline="#3b3d52", r=4, lw=1)
    txt(offset, 100, sy + 3, font=FONT_MONO, fill=SUBTLE)
    txt(name, 160, sy + 3, font=FONT_MONO_B, fill=color)
    txt(purpose, 450, sy + 3, font=FONT, fill=TEXT)
    txt(source, 950, sy + 3, font=FONT_MONO, fill=SUBTLE)
    sy += 24

# ============================================================
# SECTION 6: Error Handling
# ============================================================
SEC6_Y = sy + 20
ctext("Error Handling & Edge Cases", 0, SEC6_Y, _W, font=FONT_SECTION, fill=RED)

sy = SEC6_Y + 30
cases = [
    ("PostMessageW fails", "stash cleaned via pop(lparam); caller calls reset_pause_recog()", RED),
    ("Grammar gone at dispatch", "handler checks _grammar_sinks.get(); calls reset_pause_recog() if missing", ACCENT3),
    ("Stash key orphaned", "_stash.clear() on window destroy catches all orphans", SUBTLE),
    ("Dragon paused at disconnect", "unregister_sinks() calls Resume(cookie) before unregistering", ACCENT2),
    ("Sync op in-flight at disconnect", "drains _message_stack with pump(timeout_ms=2000)", MAUVE),
    ("execScript aborted", "error string stashed; _sync_op pops it, raises NatlinkCOMError", PEACH),
]

for label, handling, color in cases:
    rbox(80, sy, 1340, 28, fill=DARK_FILL, outline="#3b3d52", r=6, lw=1)
    txt(label, 100, sy + 5, font=FONT_BOLD, fill=color)
    txt(handling, 380, sy + 6, font=FONT, fill=SUBTLE)
    sy += 32

img.save(OUT_PATH, dpi=(144, 144))
print(f"Saved: {OUT_PATH}")
