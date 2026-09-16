#!/usr/bin/env python3
"""
Find & Replace  -  batch text replacement driven by a CSV dictionary.

    Input      : a plain-text .txt file
    Reference  : a .csv file, column A = word to find, column B = replacement
    Output     : a new .txt file with every replacement applied

Double-click "Find and Replace.bat" to launch the GUI.

Command line (headless) use:

    python find_replace_app.py input.txt replacements.csv output.txt
                               [--whole-word] [--ignore-case]

Standard library only - no pip installs required.
"""

import codecs
import csv
import os
import re
import sys
import threading
import traceback

APP_NAME = "Find & Replace"
VERSION = "1.0"

# Encodings tried, in order, when a file carries no byte-order mark.
ENCODINGS = ("utf-8", "cp1252", "latin-1")

# Byte-order marks Notepad and Excel produce, longest first.
BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

# Words that mark the first CSV row as a header rather than real data.
HEADER_HINTS = {
    "find", "search", "old", "from", "word", "source", "original",
    "find word", "word to find", "search for", "old word", "old value",
}


# --------------------------------------------------------------------------
# Core engine (no GUI - importable and testable on its own)
# --------------------------------------------------------------------------

def read_text(path):
    """
    Read a text file, returning (text, encoding_used).

    A byte-order mark decides the encoding when one is present (Notepad writes
    these); otherwise UTF-8 is tried first, then the Windows fallbacks.  The
    encoding is reported so the output file can be written the same way - in
    particular, a file that had no BOM must not gain one.
    """
    with open(path, "rb") as fh:
        raw = fh.read()

    for bom, enc in BOMS:
        if raw.startswith(bom):
            return raw.decode(enc), enc

    last_error = None
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(
        "Could not decode %s with any of: %s (%s)"
        % (path, ", ".join(ENCODINGS), last_error)
    )


def looks_like_header(row):
    """True if the first CSV row appears to be column titles."""
    if not row:
        return False
    return str(row[0]).strip().lower() in HEADER_HINTS


def load_pairs(csv_path, skip_header=None):
    """
    Load (find, replace) pairs from a CSV file.

    Column A is the word to find, column B the replacement.  Extra columns are
    ignored.  A missing or blank column B means "delete the word".  Rows with a
    blank column A are skipped.

    skip_header: True = always skip row 1, False = never, None = auto-detect.

    Returns (pairs, warnings).
    """
    warnings = []
    pairs = []
    seen = {}

    raw, _enc = read_text(csv_path)
    lines = raw.splitlines()
    if not lines:
        return pairs, ["Reference file is empty."]

    # Comma is the norm, but fall back to semicolon when that is clearly the
    # delimiter in use (common on European Excel installs).
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    rows = list(csv.reader(lines, delimiter=delimiter))

    start = 0
    if skip_header is True or (skip_header is None and looks_like_header(rows[0])):
        start = 1

    for line_no, row in enumerate(rows[start:], start=start + 1):
        if not row or all(not str(c).strip() for c in row):
            continue                                    # blank line
        find = str(row[0]).strip()
        repl = str(row[1]).strip() if len(row) > 1 else ""
        if not find:
            warnings.append("Row %d: column A is empty - row skipped." % line_no)
            continue
        if find in seen:
            warnings.append(
                'Row %d: "%s" already listed on row %d - first entry kept.'
                % (line_no, find, seen[find])
            )
            continue
        seen[find] = line_no
        pairs.append((find, repl))

    return pairs, warnings


def build_pattern(pairs, whole_word=False, ignore_case=False):
    """
    Build one regex that matches every search term.

    A single combined pattern means the text is scanned once and each region is
    replaced at most once, so replacements can never cascade into one another:
    "cat"->"dog" followed by "dog"->"fox" leaves "dog", not "fox".  Longer terms
    are placed first so the longest match always wins.
    """
    if not pairs:
        return None
    terms = sorted((p[0] for p in pairs), key=len, reverse=True)
    body = "|".join(re.escape(t) for t in terms)
    if whole_word:
        # Lookarounds rather than \b, so terms that start or end with
        # punctuation (C++, $total) still behave sensibly.
        body = r"(?<!\w)(?:%s)(?!\w)" % body
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(body, flags)


def replace_text(text, pairs, whole_word=False, ignore_case=False):
    """
    Apply every replacement in a single pass.

    Returns (new_text, counts) where counts maps each search term to the number
    of times it was replaced.
    """
    counts = {find: 0 for find, _ in pairs}
    pattern = build_pattern(pairs, whole_word, ignore_case)
    if pattern is None:
        return text, counts

    if ignore_case:
        lookup = {}
        for find, repl in pairs:
            lookup.setdefault(find.lower(), (find, repl))
    else:
        lookup = {find: (find, repl) for find, repl in pairs}

    def substitute(match):
        key = match.group(0)
        entry = lookup.get(key.lower() if ignore_case else key)
        if entry is None:                               # should not happen
            return key
        original, replacement = entry
        counts[original] += 1
        return replacement

    return pattern.sub(substitute, text), counts


def run_job(input_path, csv_path, output_path,
            whole_word=False, ignore_case=False, skip_header=None):
    """Do the whole job.  Returns a result dict for reporting."""
    pairs, warnings = load_pairs(csv_path, skip_header)
    if not pairs:
        raise ValueError(
            "No find/replace pairs found in the reference file.\n"
            "Column A must hold the word to find and column B the replacement."
        )

    text, encoding = read_text(input_path)
    new_text, counts = replace_text(text, pairs, whole_word, ignore_case)

    # Write back in the encoding we read, unless that was a lossy fallback.
    out_encoding = "utf-8" if encoding in ("cp1252", "latin-1") else encoding
    with open(output_path, "w", encoding=out_encoding, newline="") as fh:
        fh.write(new_text)

    return {
        "pairs": pairs,
        "counts": counts,
        "warnings": warnings,
        "total": sum(counts.values()),
        "applied": sum(1 for v in counts.values() if v),
        "encoding": encoding,
        "output": output_path,
        "chars_in": len(text),
        "chars_out": len(new_text),
    }


def default_output_path(input_path):
    base, ext = os.path.splitext(input_path)
    return base + "_replaced" + (ext or ".txt")


def _clip(value, width):
    value = str(value)
    return value if len(value) <= width else value[: width - 1] + "..."


def format_report(result, input_path, csv_path):
    """Human-readable summary of a completed job."""
    lines = []
    add = lines.append
    add("=" * 62)
    add("  RESULT")
    add("=" * 62)
    add("Input file      : %s" % input_path)
    add("Reference file  : %s" % csv_path)
    add("Output file     : %s" % result["output"])
    add("File encoding   : %s" % result["encoding"])
    add("")
    add("Replacement pairs loaded : %d" % len(result["pairs"]))
    add("Pairs that matched       : %d" % result["applied"])
    add("Total replacements made  : %d" % result["total"])
    add("Characters in / out      : %d / %d"
        % (result["chars_in"], result["chars_out"]))
    add("")
    add("-" * 62)
    add("  PER-WORD BREAKDOWN")
    add("-" * 62)
    counts = result["counts"]
    for find, repl in result["pairs"]:
        n = counts[find]
        shown = repl if repl else "(deleted)"
        mark = " " if n else "!"
        add("%s %-28s -> %-24s %5d" % (mark, _clip(find, 28), _clip(shown, 24), n))
    if result["applied"] < len(result["pairs"]):
        add("")
        add('Lines marked "!" were never found in the input file.')
    if result["warnings"]:
        add("")
        add("-" * 62)
        add("  NOTES ON THE REFERENCE FILE")
        add("-" * 62)
        for w in result["warnings"]:
            add("- " + w)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("%s  v%s" % (APP_NAME, VERSION))
    root.geometry("840x660")
    root.minsize(720, 560)

    input_var = tk.StringVar()
    csv_var = tk.StringVar()
    output_var = tk.StringVar()
    whole_word_var = tk.BooleanVar(value=False)
    ignore_case_var = tk.BooleanVar(value=False)
    header_var = tk.StringVar(value="auto")
    open_after_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(
        value="Choose an input file and a reference file to begin.")

    style = ttk.Style(root)
    for theme in ("vista", "winnative", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    style.configure("Run.TButton", font=("Segoe UI", 10, "bold"))

    outer = ttk.Frame(root, padding=14)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="Find & Replace",
              font=("Segoe UI", 15, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text="Replace words in a text file using a CSV list "
             "(column A = find, column B = replace with).",
        foreground="#555555",
    ).pack(anchor="w", pady=(0, 12))

    # ---- file pickers ----------------------------------------------------
    files = ttk.LabelFrame(outer, text=" Files ", padding=10)
    files.pack(fill="x")
    files.columnconfigure(1, weight=1)

    def add_row(row, label, var, command, hint):
        ttk.Label(files, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(files, textvariable=var).grid(
            row=row, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(files, text="Browse...", width=11,
                   command=command).grid(row=row, column=2, pady=4)
        ttk.Label(files, text=hint, foreground="#777777",
                  font=("Segoe UI", 8)).grid(row=row + 1, column=1,
                                             sticky="w", padx=8)

    def pick_input():
        path = filedialog.askopenfilename(
            title="Select the input text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            path = os.path.normpath(path)
            input_var.set(path)
            if not output_var.get().strip():
                output_var.set(default_output_path(path))
            status_var.set("Input file selected.")

    def pick_csv():
        path = filedialog.askopenfilename(
            title="Select the reference CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            csv_var.set(os.path.normpath(path))
            preview_pairs()

    def pick_output():
        initial = output_var.get().strip()
        if not initial:
            src = input_var.get().strip()
            initial = default_output_path(src) if src else "output.txt"
        path = filedialog.asksaveasfilename(
            title="Save the output file as",
            defaultextension=".txt",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or None,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            output_var.set(os.path.normpath(path))

    add_row(0, "1.  Input file (.txt)", input_var, pick_input,
            "The text file you want to change.")
    add_row(2, "2.  Reference file (.csv)", csv_var, pick_csv,
            "Column A = word to find, column B = word to replace with.")
    add_row(4, "3.  Output file (.txt)", output_var, pick_output,
            "Created for you; the input file is never modified.")

    # ---- options ---------------------------------------------------------
    opts = ttk.LabelFrame(outer, text=" Options ", padding=10)
    opts.pack(fill="x", pady=(12, 0))

    ttk.Checkbutton(opts,
                    text="Whole words only  (do not match inside longer words)",
                    variable=whole_word_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(opts, text="Ignore upper/lower case when matching",
                    variable=ignore_case_var).grid(row=1, column=0, sticky="w")
    ttk.Checkbutton(opts, text="Open the output file when finished",
                    variable=open_after_var).grid(row=2, column=0, sticky="w")

    hdr = ttk.Frame(opts)
    hdr.grid(row=0, column=1, rowspan=3, sticky="nw", padx=(30, 0))
    ttk.Label(hdr, text="First row of the CSV:").pack(anchor="w")
    for text, value in (("Detect automatically", "auto"),
                        ("Is a header - skip it", "skip"),
                        ("Is data - use it", "data")):
        ttk.Radiobutton(hdr, text=text, value=value, variable=header_var,
                        command=lambda: preview_pairs()).pack(anchor="w")

    # ---- action buttons --------------------------------------------------
    actions = ttk.Frame(outer)
    actions.pack(fill="x", pady=(12, 8))
    run_btn = ttk.Button(actions, text="Run Find && Replace",
                         style="Run.TButton", command=lambda: start_run())
    run_btn.pack(side="left", ipadx=14, ipady=4)
    ttk.Button(actions, text="Preview pairs",
               command=lambda: preview_pairs(verbose=True)).pack(side="left", padx=8)
    ttk.Button(actions, text="Clear", command=lambda: clear_all()).pack(side="left")

    # ---- log -------------------------------------------------------------
    logframe = ttk.LabelFrame(outer, text=" Log ", padding=6)
    logframe.pack(fill="both", expand=True)
    log = tk.Text(logframe, wrap="none", height=12,
                  font=("Consolas", 9), background="#fbfbfb")
    yscroll = ttk.Scrollbar(logframe, orient="vertical", command=log.yview)
    xscroll = ttk.Scrollbar(logframe, orient="horizontal", command=log.xview)
    log.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set,
                  state="disabled")
    log.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    logframe.rowconfigure(0, weight=1)
    logframe.columnconfigure(0, weight=1)

    ttk.Label(outer, textvariable=status_var,
              foreground="#333333").pack(anchor="w", pady=(8, 0))

    def write_log(text, clear=False):
        log.configure(state="normal")
        if clear:
            log.delete("1.0", "end")
        log.insert("end", text + "\n")
        log.see("end")
        log.configure(state="disabled")

    def header_choice():
        return {"auto": None, "skip": True, "data": False}[header_var.get()]

    def clear_all():
        for var in (input_var, csv_var, output_var):
            var.set("")
        write_log("", clear=True)
        status_var.set("Cleared.")

    def preview_pairs(verbose=False):
        path = csv_var.get().strip()
        if not path:
            if verbose:
                messagebox.showinfo(APP_NAME, "Select a reference CSV file first.")
            return
        if not os.path.isfile(path):
            write_log("Reference file not found: %s" % path, clear=True)
            return
        try:
            pairs, warnings = load_pairs(path, header_choice())
        except Exception as exc:
            write_log("Could not read the reference file:\n  %s" % exc, clear=True)
            status_var.set("Reference file could not be read.")
            return

        lines = ["Loaded %d replacement pair(s) from %s"
                 % (len(pairs), os.path.basename(path)), "-" * 62]
        limit = len(pairs) if verbose else 15
        for find, repl in pairs[:limit]:
            lines.append("  %-30s -> %s"
                         % (_clip(find, 30), repl if repl else "(deleted)"))
        if len(pairs) > limit:
            lines.append("  ... and %d more (click 'Preview pairs' to see all)"
                         % (len(pairs) - limit))
        for w in warnings:
            lines.append("  ! " + w)
        write_log("\n".join(lines), clear=True)
        status_var.set("%d pair(s) ready." % len(pairs))

    def validate():
        inp = input_var.get().strip()
        ref = csv_var.get().strip()
        out = output_var.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "Please select a valid input .txt file.")
            return None
        if not ref or not os.path.isfile(ref):
            messagebox.showerror(APP_NAME,
                                 "Please select a valid reference .csv file.")
            return None
        if not out:
            out = default_output_path(inp)
            output_var.set(out)
        if os.path.abspath(out) in (os.path.abspath(inp), os.path.abspath(ref)):
            messagebox.showerror(
                APP_NAME,
                "The output file must be different from the input and "
                "reference files.")
            return None
        folder = os.path.dirname(os.path.abspath(out))
        if not os.path.isdir(folder):
            messagebox.showerror(APP_NAME,
                                 "The output folder does not exist:\n%s" % folder)
            return None
        if os.path.exists(out) and not messagebox.askyesno(
                APP_NAME, "%s already exists.\n\nOverwrite it?" % out):
            return None
        return inp, ref, out

    def start_run():
        paths = validate()
        if not paths:
            return
        inp, ref, out = paths
        run_btn.configure(state="disabled")
        status_var.set("Working...")
        write_log("Running...", clear=True)

        def worker():
            try:
                result = run_job(inp, ref, out,
                                 whole_word_var.get(), ignore_case_var.get(),
                                 header_choice())
            except Exception as exc:                    # surfaced in the GUI log
                detail = traceback.format_exc()
                root.after(0, lambda e=exc, d=detail: finish_error(e, d))
            else:
                root.after(0, lambda r=result: finish_ok(r, inp, ref, out))

        threading.Thread(target=worker, daemon=True).start()

    def finish_ok(result, inp, ref, out):
        run_btn.configure(state="normal")
        write_log(format_report(result, inp, ref), clear=True)
        status_var.set("Done - %d replacement(s) written to %s"
                       % (result["total"], os.path.basename(out)))
        if result["total"] == 0:
            messagebox.showwarning(
                APP_NAME,
                "The output file was written, but none of the words in the "
                "reference file were found in the input file.\n\n"
                "Try turning off 'Whole words only', or turning on "
                "'Ignore upper/lower case'.")
        elif open_after_var.get():
            try:
                os.startfile(out)                       # Windows only
            except Exception:
                pass

    def finish_error(exc, detail):
        run_btn.configure(state="normal")
        write_log("ERROR\n" + "-" * 62 + "\n%s\n\n%s" % (exc, detail), clear=True)
        status_var.set("Failed - see the log above.")
        messagebox.showerror(APP_NAME, str(exc))

    root.bind("<Return>", lambda _e: start_run())
    root.mainloop()


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a.lower() for a in argv if a.startswith("--")}

    if not args:
        launch_gui()
        return 0

    if len(args) < 2:
        print(__doc__)
        return 2

    input_path = args[0]
    csv_path = args[1]
    output_path = args[2] if len(args) > 2 else default_output_path(input_path)

    if "--skip-header" in flags:
        skip_header = True
    elif "--no-header" in flags:
        skip_header = False
    else:
        skip_header = None

    try:
        result = run_job(input_path, csv_path, output_path,
                         whole_word="--whole-word" in flags,
                         ignore_case="--ignore-case" in flags,
                         skip_header=skip_header)
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    print(format_report(result, input_path, csv_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
