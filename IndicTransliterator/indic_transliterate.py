#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Indic Script Transliterator
===========================

Converts a plain-text (.txt) file written in one Indian script into another,
character by character.  Supported scripts:

    Devanagari  (Hindi, Marathi, Sanskrit, Nepali, Konkani)
    Bengali     (Bengali)
    Telugu      (Telugu)
    Kannada     (Kannada)
    Tamil       (Tamil)

This is *transliteration*, not translation: the sounds are carried over,
the meaning is not.  "namaste" written in Devanagari becomes the same word
spelled with Kannada letters.

The app needs nothing but a standard Python 3 install - no pip packages.
Double-click "Run Transliterator.bat" (Windows) or run this file directly
for the graphical window; pass command-line options for batch use.

    python indic_transliterate.py -i input.txt -o output.txt -t tamil
    python indic_transliterate.py --list
    python indic_transliterate.py --selftest

How it works
------------
The Unicode blocks for these scripts are laid out in parallel: the Nth slot
of the Devanagari block is the same letter as the Nth slot of the Kannada
block.  So every conversion is routed through Devanagari as a pivot:

    source script  ->  Devanagari  ->  target script

Where the target script has no equivalent letter (Tamil has no separate
'gha', Bengali has no 'va', ...) a fallback chain substitutes the closest
available sound.  Those substitutions are lossy and are listed in README.md.
"""

import argparse
import os
import re
import sys
import unicodedata

APP_NAME = "Indic Script Transliterator"
VERSION = "1.0"

DEV = 0x0900          # start of the Devanagari block, used as the pivot
BLOCK = 0x80          # every supported script occupies 0x80 code points


# --------------------------------------------------------------------------
# Script definitions
# --------------------------------------------------------------------------
# "src" = overrides applied when this script is the SOURCE.  Keys are code
#         points of this script, values are Devanagari strings.
# "tgt" = overrides applied when this script is the TARGET.  Keys are
#         Devanagari code points, values are strings in this script.

SCRIPTS = {
    "devanagari": {
        "name": "Devanagari",
        "languages": "Hindi, Marathi, Sanskrit, Nepali, Konkani",
        "base": 0x0900,
        "src": {},
        "tgt": {},
    },
    "bengali": {
        "name": "Bengali",
        "languages": "Bengali",
        "base": 0x0980,
        "src": {
            0x09CE: "त्",   # khanda ta  ->  त + virama
            0x09F0: "र",    # Assamese ra
            0x09F1: "व",    # Assamese wa
        },
        "tgt": {},
    },
    "telugu": {
        "name": "Telugu",
        "languages": "Telugu",
        "base": 0x0C00,
        "src": {},
        "tgt": {
            0x093C: "",     # the nukta exists in Unicode but is not written in Telugu
        },
    },
    "kannada": {
        "name": "Kannada",
        "languages": "Kannada",
        "base": 0x0C80,
        "src": {
            0x0CDE: "ऴ",    # archaic Kannada "fa"/llla letter
        },
        "tgt": {
            0x093C: "",     # the nukta exists in Unicode but is not written in Kannada
        },
    },
    "tamil": {
        "name": "Tamil",
        "languages": "Tamil",
        "base": 0x0B80,
        "src": {
            0x0BD0: "ॐ",    # Tamil om sign
        },
        "tgt": {},
    },
}

SCRIPT_ORDER = ["devanagari", "bengali", "telugu", "kannada", "tamil"]

# Friendly aliases accepted on the command line and in the drop-downs.
ALIASES = {
    "hindi": "devanagari",
    "marathi": "devanagari",
    "sanskrit": "devanagari",
    "nepali": "devanagari",
    "konkani": "devanagari",
    "deva": "devanagari",
    "hi": "devanagari",
    "bangla": "bengali",
    "bn": "bengali",
    "assamese": "bengali",
    "te": "telugu",
    "kn": "kannada",
    "kannad": "kannada",
    "ta": "tamil",
}

# Characters shared by all Indic scripts - never remapped.
PASS_THROUGH = {
    0x0964,   # danda
    0x0965,   # double danda
    0x0970,   # abbreviation sign
    0x0971,   # high spacing dot
}

# Closest-sound substitutes, expressed entirely in Devanagari.  Used only
# when the target script genuinely lacks the letter.  Resolution is
# recursive: घ -> ग -> क, so Tamil (which has none of these) lands on क.
FALLBACK = {
    # nasals / signs
    "ऀ": "ँ", "ँ": "ं", "ऄ": "अ",
    "ऽ": "",                                    # avagraha
    "़": "",                                    # nukta
    "॑": "", "॒": "", "॓": "", "॔": "",         # Vedic accents
    "ॐ": "ओम्",
    # vowels that only some scripts have
    "ऍ": "ए", "ऎ": "ए", "ऑ": "ओ", "ऒ": "ओ",
    "ऋ": "रि", "ॠ": "री", "ऌ": "लि", "ॡ": "ली",
    # vowel signs
    "ॅ": "े", "ॆ": "े", "ॉ": "ो", "ॊ": "ो",
    "ृ": "्रि", "ॄ": "्री", "ॢ": "्लि", "ॣ": "्ली",
    "ऺ": "ा", "ऻ": "ा", "ॎ": "े", "ॏ": "ो", "ॕ": "े", "ॖ": "", "ॗ": "",
    # nukta consonants -> plain consonants
    "क़": "क", "ख़": "ख", "ग़": "ग", "ज़": "ज", "ड़": "ड",
    "ढ़": "ढ", "फ़": "फ", "य़": "य",
    "ऩ": "न", "ऱ": "र", "ऴ": "ळ", "ळ": "ल",
    # consonant simplification (mainly for Tamil)
    "ख": "क", "ग": "क", "घ": "क", "ङ": "न",
    "छ": "च", "झ": "ज", "ञ": "न",
    "ठ": "ट", "ड": "ट", "ढ": "ट",
    "थ": "त", "द": "त", "ध": "त",
    "फ": "प", "ब": "प", "भ": "प",
    "श": "स", "ष": "श",
    "व": "ब",                                   # Bengali has no separate va
    # Devanagari extensions used by minority languages
    "ॲ": "अ", "ॳ": "अ", "ॴ": "आ", "ॵ": "ओ", "ॶ": "ए", "ॷ": "ओ",
    "ॸ": "", "ॹ": "झ", "ॺ": "य", "ॻ": "ग", "ॼ": "ज", "ॽ": "",
    "ॾ": "ड", "ॿ": "ब",
}


# --------------------------------------------------------------------------
# Unicode helpers
# --------------------------------------------------------------------------

def _assigned(cp):
    """True if the code point is a real character in this Python's Unicode data."""
    try:
        unicodedata.name(chr(cp))
        return True
    except ValueError:
        return False


def _build_nukta_maps():
    """Split/join maps for pre-composed nukta letters (क़, ড়, ...).

    Only decompositions whose second element is a nukta are used, so
    two-part vowel signs such as Bengali ো are left intact.
    """
    split, join = {}, {}
    for key in SCRIPTS:
        base = SCRIPTS[key]["base"]
        for cp in range(base, base + BLOCK):
            if not _assigned(cp):
                continue
            dec = unicodedata.decomposition(chr(cp))
            if not dec or "<" in dec:
                continue
            parts = dec.split()
            if len(parts) != 2:
                continue
            a, b = int(parts[0], 16), int(parts[1], 16)
            if b & 0x7F != 0x3C:            # 0x3C is the nukta slot in every block
                continue
            split[cp] = chr(a) + chr(b)
            join.setdefault(key, {})[chr(a) + chr(b)] = chr(cp)
    return split, join


_NUKTA_SPLIT, _NUKTA_JOIN = _build_nukta_maps()


def _split_nukta(text):
    return "".join(_NUKTA_SPLIT.get(ord(ch), ch) for ch in text)


def _join_nukta(text, script):
    for pair, single in _NUKTA_JOIN.get(script, {}).items():
        text = text.replace(pair, single)
    return text


# --------------------------------------------------------------------------
# Translation tables
# --------------------------------------------------------------------------

_TABLE_CACHE = {}


def _to_target_char(cp, script, depth=0):
    """Render one Devanagari code point in `script`, following FALLBACK."""
    spec = SCRIPTS[script]
    if spec["base"] == DEV:
        return chr(cp)
    override = spec["tgt"].get(cp)
    if override is not None:
        return override
    candidate = spec["base"] + (cp - DEV)
    if _assigned(candidate):
        return chr(candidate)
    replacement = FALLBACK.get(chr(cp))
    if replacement is None or depth >= 8:
        return ""                                # nothing sensible to write
    return "".join(_to_target_char(ord(c), script, depth + 1) for c in replacement)


def _dev_to_script_table(script, digits):
    key = ("out", script, digits)
    if key in _TABLE_CACHE:
        return _TABLE_CACHE[key]
    table = {}
    for cp in range(DEV, DEV + BLOCK):
        if cp in PASS_THROUGH:
            continue                             # absent key = leave unchanged
        if 0x0966 <= cp <= 0x096F:               # digits
            if digits:
                d = SCRIPTS[script]["base"] + (cp - DEV)
                table[cp] = chr(d) if _assigned(d) else chr(cp)
            continue
        table[cp] = _to_target_char(cp, script)
    _TABLE_CACHE[key] = table
    return table


def _script_to_dev_table(script, digits):
    key = ("in", script, digits)
    if key in _TABLE_CACHE:
        return _TABLE_CACHE[key]
    spec = SCRIPTS[script]
    table = {}
    for i in range(BLOCK):
        cp = spec["base"] + i
        if cp in spec["src"]:
            table[cp] = spec["src"][cp]
            continue
        if not _assigned(cp):
            continue
        if 0x66 <= i <= 0x6F:                    # digits
            if digits:
                table[cp] = chr(DEV + i)
            continue
        dev = DEV + i
        if _assigned(dev):
            table[cp] = chr(dev)
    _TABLE_CACHE[key] = table
    return table


# --------------------------------------------------------------------------
# Script-specific touch-ups applied to the Devanagari pivot
# --------------------------------------------------------------------------

# Tamil writing does not use the anusvara dot the way the northern scripts
# do; it spells the nasal out.  So "गंगा" should become "கங்கா", not "கஂகா".
_NASAL_BY_CLASS = [
    ("कखगघङ", "ङ"),
    ("चछजझञ", "ञ"),
    ("टठडढण", "ण"),
    ("तथदधन", "न"),
    ("पफबभम", "म"),
]
_NASAL_OF = {c: nasal for group, nasal in _NASAL_BY_CLASS for c in group}
_ANUSVARA_RE = re.compile("ं([क-हक़-य़])")


def _tamil_nasals(dev_text):
    """Replace anusvara with the nasal consonant it stands for."""
    def expand(match):
        following = match.group(1)
        return _NASAL_OF.get(following, "म") + "्" + following

    dev_text = _ANUSVARA_RE.sub(expand, dev_text)
    # Anything left (end of word, before a vowel) becomes a plain "m".
    return dev_text.replace("ं", "म्")


PIVOT_TOUCHUPS = {"tamil": _tamil_nasals}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def resolve_script(name):
    """Turn a user-supplied name/alias into a canonical script key."""
    if not name:
        raise ValueError("no script given")
    key = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    key = ALIASES.get(key, key)
    if key not in SCRIPTS:
        raise ValueError(
            "unknown script %r (choose from: %s)"
            % (name, ", ".join(SCRIPT_ORDER))
        )
    return key


def detect_script(text):
    """Guess which supported script `text` is written in, or None."""
    counts = {key: 0 for key in SCRIPTS}
    for ch in text:
        cp = ord(ch)
        if cp < 0x0900 or cp > 0x0D7F:
            continue
        for key, spec in SCRIPTS.items():
            if spec["base"] <= cp < spec["base"] + BLOCK:
                if 0x0964 <= cp <= 0x0965:       # shared danda proves nothing
                    break
                counts[key] += 1
                break
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] else None


def transliterate(text, source, target, digits=True):
    """Convert `text` from `source` script to `target` script."""
    source = resolve_script(source)
    target = resolve_script(target)
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _split_nukta(text)
    dev = text.translate(_script_to_dev_table(source, digits))
    touch_up = PIVOT_TOUCHUPS.get(target)
    if touch_up is not None:
        dev = touch_up(dev)
    out = dev.translate(_dev_to_script_table(target, digits))
    out = _join_nukta(out, target)
    return unicodedata.normalize("NFC", out)


# --------------------------------------------------------------------------
# File I/O
# --------------------------------------------------------------------------

READ_ENCODINGS = ("utf-8-sig", "utf-16", "utf-32", "cp1252", "latin-1")


def read_text_file(path):
    """Read a .txt file, trying the encodings Indic text usually arrives in."""
    with open(path, "rb") as handle:
        raw = handle.read()
    for enc in READ_ENCODINGS:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (with replacements)"


def write_text_file(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def suggest_output_path(input_path, target):
    stem, ext = os.path.splitext(input_path)
    return "%s_%s%s" % (stem, target, ext or ".txt")


def convert_file(input_path, output_path, source, target, digits=True):
    """Convert one file; returns (source_key, characters_written)."""
    text, _ = read_text_file(input_path)
    if source in (None, "", "auto"):
        source = detect_script(text)
        if source is None:
            raise ValueError(
                "could not detect the script of %s - it contains no "
                "Devanagari, Bengali, Telugu, Kannada or Tamil text."
                % os.path.basename(input_path)
            )
    else:
        source = resolve_script(source)
    result = transliterate(text, source, target, digits)
    write_text_file(output_path, result)
    return source, len(result)


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

def selftest():
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append("%s\n    got  %r\n    want %r" % (label, got, want))

    # Round trip through scripts that carry the full consonant inventory.
    text = "भारत एक विशाल देश है। ज्ञान और विज्ञान।"
    for script in ("bengali", "telugu", "kannada"):
        # Bengali has no 'va', so use a va-free sentence for it.
        probe = "भारत एक शाल देश है। ज्ञान और ज्ञान।" if script == "bengali" else text
        there = transliterate(probe, "devanagari", script)
        back = transliterate(there, script, "devanagari")
        check("round trip devanagari -> %s -> devanagari" % script, back, probe)

    check("hindi alias", transliterate("नमस्ते", "hindi", "kannada"), "ನಮಸ್ತೇ")
    check("kannada -> devanagari", transliterate("ಕನ್ನಡ", "kannada", "devanagari"), "कन्नड")
    check("telugu -> devanagari", transliterate("తెలుగు", "telugu", "devanagari"), "तॆलुगु")
    check("devanagari -> telugu", transliterate("तॆलुगु", "devanagari", "telugu"), "తెలుగు")
    check("devanagari -> bengali", transliterate("बांग्ला", "devanagari", "bengali"), "বাংগ্লা")
    check("bengali -> devanagari", transliterate("বাংলা", "bengali", "devanagari"), "बांला")

    # Tamil is lossy on purpose: gha/ga/kha/ka all collapse to ka.
    check("tamil nasal", transliterate("गंगा", "devanagari", "tamil"), "கங்கா")
    check("kannada keeps anusvara", transliterate("गंगा", "devanagari", "kannada"), "ಗಂಗಾ")
    check("tamil -> devanagari", transliterate("தமிழ்", "tamil", "devanagari"), "तमिऴ्")
    check("tamil vocalic r", transliterate("कृष्ण", "devanagari", "tamil"), "க்ரிஷ்ண")

    # Bengali khanda-ta and 'va'.
    check("khanda ta", transliterate("ভবিষ্যৎ", "bengali", "devanagari"), "भबिष्यत्")
    check("va -> ba", transliterate("विवेक", "devanagari", "bengali"), "বিবেক")

    # Two-part vowel signs must survive intact.
    check("two-part vowel", transliterate("কোথায়", "bengali", "devanagari"), "कोथाय़")

    # Nukta letters.
    check("nukta drop in tamil", transliterate("ज़रूर", "devanagari", "tamil"), "ஜரூர")
    check("nukta keep in bengali", transliterate("ज़", "devanagari", "bengali"), "জ়")
    check("nukta drop in kannada", transliterate("पढ़ीं", "devanagari", "kannada"), "ಪಢೀಂ")
    check("nukta drop in telugu", transliterate("ज़रूर", "devanagari", "telugu"), "జరూర")

    # Vocalic r and om.
    check("om", transliterate("ॐ", "devanagari", "tamil"), "ௐ")
    check("om via bengali", transliterate("ॐ", "devanagari", "bengali"), "ওম্")
    check("rri", transliterate("ऋषि", "devanagari", "kannada"), "ಋಷಿ")

    # Digits on and off.
    check("digits on", transliterate("१२३", "devanagari", "telugu", True), "౧౨౩")
    check("digits off", transliterate("१२३", "devanagari", "telugu", False), "१२३")
    check("ascii digits untouched", transliterate("2024 में", "devanagari", "tamil"), "2024 மேம்")

    # Non-Indic text passes through untouched.
    check("latin passthrough",
          transliterate("India (भारत) 2024!", "devanagari", "kannada"),
          "India (ಭಾರತ) 2024!")

    # Identity conversion.
    check("identity", transliterate(text, "devanagari", "devanagari"), text)

    # Detection.
    check("detect tamil", detect_script("தமிழ் நாடு"), "tamil")
    check("detect devanagari", detect_script("Hello नमस्ते"), "devanagari")
    check("detect none", detect_script("Hello world"), None)

    if failures:
        print("SELF-TEST FAILED (%d)" % len(failures))
        for item in failures:
            print("  " + item)
        return 1
    print("Self-test passed.")
    return 0


# --------------------------------------------------------------------------
# Graphical interface
# --------------------------------------------------------------------------

PREVIEW_LIMIT = 40000       # characters shown in the text panes


def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, font as tkfont

    choices = ["%s  (%s)" % (SCRIPTS[k]["name"], SCRIPTS[k]["languages"])
               for k in SCRIPT_ORDER]
    auto_choice = "Auto-detect"

    def key_from_choice(label):
        if label == auto_choice:
            return None
        return SCRIPT_ORDER[choices.index(label)]

    root = tk.Tk()
    root.title("%s %s" % (APP_NAME, VERSION))
    root.geometry("980x660")
    root.minsize(760, 520)

    # An Indic-capable font if the system has one.
    available = set(tkfont.families())
    for candidate in ("Nirmala UI", "Noto Sans", "Arial Unicode MS", "Segoe UI"):
        if candidate in available:
            text_font = tkfont.Font(family=candidate, size=13)
            break
    else:
        text_font = tkfont.Font(size=13)

    in_path = tk.StringVar()
    out_path = tk.StringVar()
    src_choice = tk.StringVar(value=auto_choice)
    tgt_choice = tk.StringVar(value=choices[SCRIPT_ORDER.index("tamil")])
    digits_var = tk.BooleanVar(value=True)
    status = tk.StringVar(value="Choose a .txt file, pick the target script, then press Transliterate.")

    state = {"full_text": "", "truncated": False}

    outer = ttk.Frame(root, padding=12)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text=APP_NAME,
              font=(text_font.actual("family"), 15, "bold")).grid(
        row=0, column=0, columnspan=4, sticky="w")
    ttk.Label(outer,
              text="Rewrites Indian-language text in another Indian script. "
                   "The sounds are converted, not the meaning.",
              foreground="#555").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

    # --- file row -------------------------------------------------------
    ttk.Label(outer, text="Input file").grid(row=2, column=0, sticky="w", pady=3)
    ttk.Entry(outer, textvariable=in_path).grid(row=2, column=1, columnspan=2, sticky="ew", padx=6)
    ttk.Button(outer, text="Browse...", command=lambda: pick_input()).grid(row=2, column=3, sticky="ew")

    ttk.Label(outer, text="Output file").grid(row=3, column=0, sticky="w", pady=3)
    ttk.Entry(outer, textvariable=out_path).grid(row=3, column=1, columnspan=2, sticky="ew", padx=6)
    ttk.Button(outer, text="Browse...", command=lambda: pick_output()).grid(row=3, column=3, sticky="ew")

    # --- script row -----------------------------------------------------
    opts = ttk.Frame(outer)
    opts.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 6))
    ttk.Label(opts, text="From").pack(side="left")
    src_box = ttk.Combobox(opts, textvariable=src_choice, values=[auto_choice] + choices,
                           state="readonly", width=34)
    src_box.pack(side="left", padx=(6, 14))
    ttk.Label(opts, text="To").pack(side="left")
    tgt_box = ttk.Combobox(opts, textvariable=tgt_choice, values=choices,
                           state="readonly", width=34)
    tgt_box.pack(side="left", padx=(6, 14))
    ttk.Checkbutton(opts, text="Convert digits to target script",
                    variable=digits_var).pack(side="left")

    # --- text panes -----------------------------------------------------
    panes = ttk.Panedwindow(outer, orient="horizontal")
    panes.grid(row=5, column=0, columnspan=4, sticky="nsew", pady=8)

    left = ttk.Labelframe(panes, text="Source text", padding=4)
    right = ttk.Labelframe(panes, text="Result", padding=4)
    panes.add(left, weight=1)
    panes.add(right, weight=1)

    src_text = tk.Text(left, wrap="word", font=text_font, undo=True, height=10)
    src_scroll = ttk.Scrollbar(left, command=src_text.yview)
    src_text.configure(yscrollcommand=src_scroll.set)
    src_scroll.pack(side="right", fill="y")
    src_text.pack(side="left", fill="both", expand=True)

    out_text = tk.Text(right, wrap="word", font=text_font, height=10)
    out_scroll = ttk.Scrollbar(right, command=out_text.yview)
    out_text.configure(yscrollcommand=out_scroll.set)
    out_scroll.pack(side="right", fill="y")
    out_text.pack(side="left", fill="both", expand=True)

    # --- buttons + status ----------------------------------------------
    buttons = ttk.Frame(outer)
    buttons.grid(row=6, column=0, columnspan=4, sticky="ew")
    ttk.Button(buttons, text="Transliterate", command=lambda: do_convert()).pack(side="left")
    ttk.Button(buttons, text="Save result as...", command=lambda: save_as()).pack(side="left", padx=6)
    ttk.Button(buttons, text="Clear", command=lambda: clear_all()).pack(side="left")
    ttk.Button(buttons, text="Quit", command=root.destroy).pack(side="right")

    ttk.Label(outer, textvariable=status, foreground="#1a5c2a",
              wraplength=930, justify="left").grid(
        row=7, column=0, columnspan=4, sticky="w", pady=(8, 0))

    outer.columnconfigure(1, weight=1)
    outer.columnconfigure(2, weight=1)
    outer.rowconfigure(5, weight=1)

    # --- behaviour ------------------------------------------------------
    status_label = outer.grid_slaves(row=7, column=0)[0]

    def set_status(message, ok=True):
        status.set(message)
        status_label.configure(foreground="#1a5c2a" if ok else "#a11")

    def load_file(path):
        try:
            text, enc = read_text_file(path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Could not read the file:\n%s" % exc)
            return
        state["full_text"] = text
        state["truncated"] = len(text) > PREVIEW_LIMIT
        src_text.delete("1.0", "end")
        src_text.insert("1.0", text[:PREVIEW_LIMIT])
        out_text.delete("1.0", "end")
        detected = detect_script(text)
        if detected:
            src_choice.set(choices[SCRIPT_ORDER.index(detected)])
        note = " (showing the first %d characters)" % PREVIEW_LIMIT if state["truncated"] else ""
        set_status("Loaded %s - %d characters, %s%s. Detected script: %s."
                   % (os.path.basename(path), len(text), enc, note,
                      SCRIPTS[detected]["name"] if detected else "none found"))

    def pick_input():
        path = filedialog.askopenfilename(
            title="Choose the text file to transliterate",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        in_path.set(path)
        refresh_output_name()
        load_file(path)

    def pick_output():
        path = filedialog.asksaveasfilename(
            title="Save the result as",
            defaultextension=".txt",
            initialfile=os.path.basename(out_path.get()) or "output.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            out_path.set(path)

    def refresh_output_name(*_):
        source = in_path.get()
        target = key_from_choice(tgt_choice.get())
        if source and target:
            out_path.set(suggest_output_path(source, target))

    def current_source_text():
        if state["truncated"]:
            return state["full_text"]
        return src_text.get("1.0", "end-1c")

    def do_convert():
        text = current_source_text()
        if not text.strip():
            set_status("Nothing to convert - load a file or type some text on the left.", False)
            return
        source = key_from_choice(src_choice.get())
        if source is None:
            source = detect_script(text)
            if source is None:
                set_status("Could not detect the source script. Pick it manually in the "
                           "'From' box.", False)
                return
        target = key_from_choice(tgt_choice.get())
        try:
            result = transliterate(text, source, target, digits_var.get())
        except Exception as exc:                          # pragma: no cover
            messagebox.showerror(APP_NAME, "Conversion failed:\n%s" % exc)
            return
        out_text.delete("1.0", "end")
        out_text.insert("1.0", result[:PREVIEW_LIMIT])
        state["result"] = result

        message = "Converted %s -> %s (%d characters)." % (
            SCRIPTS[source]["name"], SCRIPTS[target]["name"], len(result))
        destination = out_path.get().strip()
        if destination:
            try:
                write_text_file(destination, result)
                message += "  Saved to %s" % destination
            except OSError as exc:
                set_status(message + "  Could not save: %s" % exc, False)
                return
        else:
            message += "  Use 'Save result as...' to write it to a file."
        set_status(message)

    def save_as():
        result = state.get("result")
        if not result:
            result = out_text.get("1.0", "end-1c")
        if not result.strip():
            set_status("There is no result to save yet - press Transliterate first.", False)
            return
        target = key_from_choice(tgt_choice.get())
        default = os.path.basename(suggest_output_path(in_path.get() or "output.txt", target))
        path = filedialog.asksaveasfilename(
            title="Save the result as", defaultextension=".txt",
            initialfile=default,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            write_text_file(path, result)
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Could not save the file:\n%s" % exc)
            return
        out_path.set(path)
        set_status("Saved %d characters to %s" % (len(result), path))

    def clear_all():
        state["full_text"] = ""
        state["truncated"] = False
        state.pop("result", None)
        src_text.delete("1.0", "end")
        out_text.delete("1.0", "end")
        in_path.set("")
        out_path.set("")
        set_status("Cleared.")

    def on_source_edit(_event=None):
        state["truncated"] = False

    src_text.bind("<KeyRelease>", on_source_edit)
    tgt_box.bind("<<ComboboxSelected>>", refresh_output_name)
    root.bind("<Control-Return>", lambda _e: do_convert())

    root.mainloop()


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="indic_transliterate",
        description="Transliterate a .txt file from one Indian script to another.")
    parser.add_argument("-i", "--input", help="input .txt file")
    parser.add_argument("-o", "--output", help="output .txt file (default: <input>_<target>.txt)")
    parser.add_argument("-f", "--from", dest="source", default="auto",
                        help="source script, or 'auto' (default)")
    parser.add_argument("-t", "--to", dest="target", help="target script")
    parser.add_argument("--no-digits", action="store_true",
                        help="leave digits exactly as they are in the source")
    parser.add_argument("--list", action="store_true", help="list the supported scripts")
    parser.add_argument("--selftest", action="store_true", help="run the built-in checks")
    parser.add_argument("--gui", action="store_true", help="force the graphical window")
    parser.add_argument("--version", action="version", version="%s %s" % (APP_NAME, VERSION))
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):          # Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)

    if args.list:
        print("Supported scripts:\n")
        for key in SCRIPT_ORDER:
            print("  %-12s %-12s %s" % (key, SCRIPTS[key]["name"], SCRIPTS[key]["languages"]))
        print("\nAliases: " + ", ".join(sorted(ALIASES)))
        return 0

    if args.selftest:
        return selftest()

    if args.gui or not argv:
        try:
            run_gui()
        except ImportError:
            print("Tkinter is not available in this Python installation, so the "
                  "window cannot open.\nUse the command line instead, for example:\n"
                  "    python indic_transliterate.py -i input.txt -t tamil")
            return 1
        return 0

    if not args.input or not args.target:
        build_parser().print_help()
        print("\nBoth --input and --to are required in command-line mode.")
        return 2

    try:
        target = resolve_script(args.target)
    except ValueError as exc:
        print("Error: %s" % exc)
        return 2

    output = args.output or suggest_output_path(args.input, target)
    try:
        source, count = convert_file(args.input, output, args.source, target,
                                     digits=not args.no_digits)
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc)
        return 1

    print("%s -> %s: wrote %d characters to %s"
          % (SCRIPTS[source]["name"], SCRIPTS[target]["name"], count, output))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                     # pragma: no cover
        import traceback
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log")
        try:
            with open(log, "w", encoding="utf-8") as handle:
                traceback.print_exc(file=handle)
        except OSError:
            pass
        traceback.print_exc()
        try:
            import tkinter.messagebox as mb
            mb.showerror(APP_NAME, "Something went wrong. Details were written to:\n%s" % log)
        except Exception:
            pass
        sys.exit(1)
