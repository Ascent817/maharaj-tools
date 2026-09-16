# Indic Script Transliterator

Rewrites a plain-text file written in one Indian script into another Indian
script. It converts **sounds, not meaning** — this is transliteration, not
translation. `भारत` becomes `பாரத` / `ಭಾರತ` / `ভারত`, all still reading
"bhārata".

Supported scripts:

| Script | Languages |
|---|---|
| Devanagari | Hindi, Marathi, Sanskrit, Nepali, Konkani |
| Bengali | Bengali (also reads Assamese ৰ / ৱ) |
| Telugu | Telugu |
| Kannada | Kannada |
| Tamil | Tamil |

Any of the 5 can convert to any of the other 4 — 20 combinations.

## Running it

**Just double-click `Run Transliterator.bat`.** The window opens; nothing to
install beyond Python 3 itself (the app uses only the standard library, no
`pip install` of anything).

If Windows says Python is missing, get it from
<https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**
during setup.

In the window:

1. **Browse…** for the input `.txt` file. The script is auto-detected and the
   text appears on the left.
2. Pick the target script in the **To** box. The output filename is filled in
   for you (`myfile_tamil.txt`) — change it if you like.
3. Press **Transliterate**. The result appears on the right and is written to
   the output file. `Ctrl+Enter` does the same thing.

You can also type or paste text straight into the left pane without opening a
file, and use **Save result as…** to choose where it goes.

## Command line

Useful for converting many files from a script or a scheduled job.

```bash
python indic_transliterate.py -i input.txt -t tamil
```

| Option | Meaning |
|---|---|
| `-i`, `--input` | input `.txt` file |
| `-o`, `--output` | output file (default: `<input>_<target>.txt`) |
| `-f`, `--from` | source script; defaults to `auto` (detected from the text) |
| `-t`, `--to` | target script — required |
| `--no-digits` | leave digits exactly as they appear in the source |
| `--list` | show script names and accepted aliases |
| `--selftest` | run the built-in correctness checks |
| `--gui` | force the window open even with other arguments |

Script names accept aliases, so `-t hindi`, `-t deva` and `-t devanagari` are
the same thing, as are `-t bangla` and `-t bengali`.

Convert a whole folder (PowerShell):

```powershell
Get-ChildItem *.txt | ForEach-Object { python indic_transliterate.py -i $_.FullName -t kannada }
```

## Files

| File | Purpose |
|---|---|
| `indic_transliterate.py` | the entire application — GUI, command line and conversion engine |
| `Run Transliterator.bat` | double-click launcher for Windows |
| `samples/` | example input files in each script, plus converted outputs |
| `README.md` | this file |

## How it works

The Unicode blocks for these scripts are laid out in parallel — the *N*th slot
of the Devanagari block holds the same letter as the *N*th slot of the Kannada
block. Every conversion therefore routes through Devanagari as a pivot:

```
source script  →  Devanagari  →  target script
```

Where the target script has no equivalent letter, a fallback chain substitutes
the nearest available sound (`घ → ग → क`), so Tamil — which has none of the
three — lands on `க`. Anything outside the Indic blocks (English words,
punctuation, `2024`) passes through untouched, so mixed-language files are
safe.

Input is read as UTF-8, UTF-16 or Windows-1252, whichever decodes; output is
always written as UTF-8.

## Things to know about accuracy

Indian scripts do not all carry the same set of sounds, so some conversions
lose information. These are the deliberate choices the app makes:

**Into Tamil** — Tamil has one letter per consonant group, so the distinctions
collapse:

- `क ख ग घ` → `க`, `च छ ज झ` → `ச` (except `ज` → `ஜ`), `ट ठ ड ढ` → `ட`,
  `त थ द ध` → `த`, `प फ ब भ` → `ப`
- vocalic `ऋ` is written out as `ரி` (`कृष्ण` → `க்ரிஷ்ண`)
- the anusvara dot is spelled out as the nasal it stands for, which is how
  Tamil actually writes it: `गंगा` → `கங்கா`, not `கஂகா`

Converting Tamil *out* to another script is therefore not reversible — the
information was never in the Tamil text.

**Into Bengali** — Bengali has no separate `व`, so `व` → `ব` (`विवेक` →
`বিবেক`). Going the other way, `ব` always comes back as `ब`.

**Into Kannada and Telugu** — these two carry the full consonant inventory, so
Devanagari ↔ Kannada ↔ Telugu round-trips cleanly. The nukta dot is dropped
because, although Unicode defines one, neither script writes it.

**Everywhere** — short `ऎ ऒ` (which Devanagari barely uses but the southern
scripts need) and long `े ो` are kept distinct, so `तेलुगु` and `तॆलुगु` give
different Telugu spellings. Vedic accent marks and the avagraha `ऽ` are dropped
for scripts that lack them.

**Digits** are converted to the target script by default (`१२३` → `೧೨೩`).
Untick the box, or pass `--no-digits`, to leave them as they are. Plain ASCII
digits (`2024`) are never touched.

Orthographic conventions beyond the letters themselves are not applied — the
output is a faithful letter-by-letter respelling, which is what you want for
names, addresses and lists, but a native speaker would spell some loanwords
differently.

## Verifying it

```bash
python indic_transliterate.py --selftest
```

This checks round trips, per-script special cases, digit handling and script
detection, and prints `Self-test passed.` when everything holds.
