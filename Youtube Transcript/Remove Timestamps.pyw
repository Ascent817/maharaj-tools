#!/usr/bin/env python3
"""
Remove Timestamps - double-click GUI for making clean transcripts.

Two ways to use it:
  * Paste a YouTube link and press "Get transcript" - the transcript is
    downloaded and saved under the video's own title.
  * Choose a .txt file you already have and press "Remove Timestamps".

Double-click this file, or the "Remove Timestamps.bat" launcher next to it.
You can also drag a .txt file onto this file's icon in Explorer.
"""

import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if getattr(sys, "frozen", False):
    # Packed into an .exe: __file__ points inside a temporary unpack folder that
    # Windows later deletes, so saves must go beside the .exe the user clicked.
    # The helper modules are bundled inside the exe, so the folder it sits in is
    # deliberately NOT added to sys.path - stray .py files next to the exe must
    # never shadow the packaged code.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(APP_DIR))

try:
    from remove_timestamps import (
        default_output, finish, heading_from_name, looks_like_youtube,
        output_for_video, read_text, split_heading, strip_timestamps, with_heading,
    )
    import format_transcript as fmt
except ImportError:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Missing file",
        "Could not find remove_timestamps.py and format_transcript.py.\n\n"
        f"They must sit in the same folder as this app:\n{APP_DIR}",
    )
    raise SystemExit(1)

try:
    import youtube_transcript as yt
    YT_IMPORT_ERROR = None
except ImportError as exc:  # youtube_transcript.py itself is missing
    yt = None
    YT_IMPORT_ERROR = str(exc)

PREVIEW_LINES = 300
BEST_AVAILABLE = "Best available (per video)"


def first_line(exc):
    """The headline of an error, without the detail that follows it."""
    return str(exc).split("\n")[0].strip().rstrip(":")


def existing_transcript(folder, video_id):
    """
    An already-saved transcript for this video, or None.

    Output names end in "[<video id>].txt", so a re-run can tell what it
    already has without asking YouTube anything - which is what keeps a
    second attempt from spending requests it does not need.
    """
    tag = f"[{video_id}].txt"
    try:
        for path in folder.iterdir():
            if path.name.endswith(tag):
                return path
    except OSError:
        pass
    return None


class App(ttk.Frame):
    def __init__(self, master, initial_file=None, initial_url=None):
        super().__init__(master, padding=14)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.in_path = None          # chosen local .txt
        self.out_path = None         # last file written
        self.out_dir = APP_DIR       # where downloads are saved
        self.languages = []          # [{'code','label',...}, ...] from the last run
        self.busy = False
        self.results = queue.Queue()  # background results, drained on the main thread

        self._build_header()
        self._build_tabs()
        self._build_options()
        self._build_preview()
        self._build_footer()
        self._poll_results()

        if initial_url:
            self.urls_text.insert("1.0", initial_url + "\n")
            self.tabs.select(0)
        elif initial_file:
            self.set_file(Path(initial_file))
            self.tabs.select(1)

    # ---------------------------------------------------------------- layout

    def _build_header(self):
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Transcript Cleaner",
                  font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header,
                  text="Download a transcript from a YouTube link, or strip timestamps "
                       "out of a text file you already have.",
                  foreground="#555555", wraplength=660, justify="left"
                  ).grid(row=1, column=0, sticky="w", pady=(2, 10))

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="ew")

        # --- YouTube tab -------------------------------------------------
        yt_tab = ttk.Frame(self.tabs, padding=12)
        yt_tab.columnconfigure(1, weight=1)
        self.tabs.add(yt_tab, text="  YouTube link  ")

        yt_tab.rowconfigure(0, weight=1)
        ttk.Label(yt_tab, text="Links:").grid(row=0, column=0, sticky="nw")

        links = ttk.Frame(yt_tab)
        links.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        links.columnconfigure(0, weight=1)
        self.urls_text = tk.Text(links, height=5, wrap="none", font=("Segoe UI", 10),
                                 relief="solid", borderwidth=1)
        self.urls_text.grid(row=0, column=0, sticky="ew")
        url_scroll = ttk.Scrollbar(links, orient="vertical",
                                   command=self.urls_text.yview)
        url_scroll.grid(row=0, column=1, sticky="ns")
        self.urls_text.configure(yscrollcommand=url_scroll.set)
        ttk.Label(links, text="One video per line. Paste as many as you like.",
                  foreground="#777777").grid(row=1, column=0, sticky="w", pady=(3, 0))

        buttons = ttk.Frame(yt_tab)
        buttons.grid(row=0, column=2, sticky="n")
        self.fetch_btn = ttk.Button(buttons, text="Get transcripts",
                                    command=self.get_transcripts)
        self.fetch_btn.grid(row=0, column=0, sticky="ew")
        ttk.Button(buttons, text="Clear", command=self.clear_urls).grid(
            row=1, column=0, sticky="ew", pady=(6, 0))

        ttk.Label(yt_tab, text="Language:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.lang_var = tk.StringVar(value=BEST_AVAILABLE)
        self.lang_box = ttk.Combobox(yt_tab, textvariable=self.lang_var,
                                     state="readonly", width=38,
                                     values=[BEST_AVAILABLE])
        self.lang_box.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Label(yt_tab,
                  text="Languages are listed after the first fetch. A video that "
                       "lacks the chosen one falls back to its best available.",
                  foreground="#777777", wraplength=430, justify="left"
                  ).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

        ttk.Label(yt_tab, text="Playlists:").grid(row=3, column=0, sticky="w",
                                                  pady=(10, 0))
        playlist = ttk.Frame(yt_tab)
        playlist.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        self.expand_playlists = tk.BooleanVar(value=True)
        ttk.Checkbutton(playlist, text="If a link is part of a playlist, take its first",
                        variable=self.expand_playlists).grid(row=0, column=0, sticky="w")
        self.playlist_count = tk.IntVar(value=10)
        ttk.Spinbox(playlist, from_=1, to=100, width=5,
                    textvariable=self.playlist_count).grid(row=0, column=1, padx=(6, 6))
        ttk.Label(playlist, text="videos").grid(row=0, column=2, sticky="w")
        ttk.Label(yt_tab,
                  text="Unticked, a playlist link fetches only the one video it points at. "
                       "YouTube lists 100 videos per playlist page, which is the most that "
                       "can be read in one go.",
                  foreground="#777777", wraplength=430, justify="left"
                  ).grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

        # --- Text file tab -----------------------------------------------
        file_tab = ttk.Frame(self.tabs, padding=12)
        file_tab.columnconfigure(1, weight=1)
        self.tabs.add(file_tab, text="  Text file  ")

        ttk.Button(file_tab, text="Choose file...",
                   command=self.choose_file).grid(row=0, column=0, sticky="w")
        self.file_label = ttk.Label(file_tab, text="No file selected",
                                    foreground="#777777", wraplength=430, justify="left")
        self.file_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.clean_btn = ttk.Button(file_tab, text="Remove Timestamps",
                                    command=self.clean_file, state="disabled")
        self.clean_btn.grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.anywhere = tk.BooleanVar(value=False)
        ttk.Checkbutton(file_tab, text="Also remove timestamps found mid-line",
                        variable=self.anywhere).grid(row=1, column=1, sticky="w",
                                                     padx=(10, 0), pady=(12, 0))

    def _build_options(self):
        opts = ttk.LabelFrame(self, text="Output", padding=10)
        opts.grid(row=2, column=0, sticky="ew", pady=(12, 8))
        opts.columnconfigure(1, weight=1)

        self.format_prose = tk.BooleanVar(value=True)
        self.remove_tags = tk.BooleanVar(value=True)
        self.remove_fillers = tk.BooleanVar(value=True)
        self.guess_breaks = tk.BooleanVar(value=False)
        self.merge_repeats = tk.BooleanVar(value=True)
        self.add_heading = tk.BooleanVar(value=True)
        self.skip_existing = tk.BooleanVar(value=True)

        ttk.Checkbutton(opts, text="Put the title on the first line",
                        variable=self.add_heading).grid(row=0, column=1, sticky="w",
                                                        padx=(20, 0))
        ttk.Checkbutton(opts, text="Skip videos already saved in that folder",
                        variable=self.skip_existing).grid(row=1, column=1, sticky="w",
                                                          padx=(20, 0))
        ttk.Checkbutton(opts, text="Format into sentences and paragraphs",
                        variable=self.format_prose).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opts, text="Remove [tags] and (asides)",
                        variable=self.remove_tags).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(opts, text="Remove filler words (uh, um, mhm)",
                        variable=self.remove_fillers).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(opts, text="Text files with no punctuation: estimate sentence breaks",
                        variable=self.guess_breaks).grid(row=3, column=0, columnspan=3,
                                                         sticky="w")
        ttk.Checkbutton(opts, text="Merge repeated lines",
                        variable=self.merge_repeats).grid(row=4, column=0, sticky="w")

        ttk.Label(opts, text="Save downloads to:").grid(row=5, column=0, sticky="w",
                                                        pady=(10, 0))
        self.dir_label = ttk.Label(opts, text=str(self.out_dir), foreground="#555555",
                                   wraplength=400, justify="left")
        self.dir_label.grid(row=5, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        ttk.Button(opts, text="Change...", command=self.choose_dir).grid(
            row=5, column=2, pady=(10, 0))

    def _build_preview(self):
        box = ttk.LabelFrame(self, text="Preview", padding=6)
        box.grid(row=3, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.preview = tk.Text(box, height=10, wrap="word", font=("Segoe UI", 10),
                               background="#fbfbfb", relief="flat")
        self.preview.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.preview.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.preview.configure(yscrollcommand=scroll.set, state="disabled")

    def _build_footer(self):
        footer = ttk.Frame(self)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        self.status = ttk.Label(footer, text="", foreground="#227722",
                                wraplength=430, justify="left")
        self.status.grid(row=0, column=0, sticky="w")
        self.open_file_btn = ttk.Button(footer, text="Open transcript",
                                        command=self.open_file, state="disabled")
        self.open_file_btn.grid(row=0, column=1, padx=(0, 8))
        self.open_btn = ttk.Button(footer, text="Open folder",
                                   command=self.open_folder, state="disabled")
        self.open_btn.grid(row=0, column=2)

    # ------------------------------------------------------------- plumbing

    def set_status(self, text, ok=True):
        self.status.configure(text=text, foreground="#227722" if ok else "#aa2222")

    def show_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.fetch_btn.configure(state=state)
        self.clean_btn.configure(state="normal" if (not busy and self.in_path) else "disabled")
        self.master.configure(cursor="watch" if busy else "")

    def run_in_background(self, work, on_done):
        """
        Run a network call off the UI thread.

        Tkinter may only be touched from the thread that created the window,
        so the worker just drops its result on a queue and the poller below -
        which always runs on the main thread - delivers it.
        """
        def progress(text):
            self.results.put(("progress", text, None))

        def worker():
            try:
                result = work(progress)
            except Exception as exc:
                self.results.put(("error", exc, on_done))
            else:
                self.results.put(("ok", result, on_done))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self):
        """Main-thread pump for finished background work."""
        while True:
            try:
                kind, payload, on_done = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.set_status(payload)
            elif kind == "ok":
                on_done(payload)
            else:
                self._on_error(payload)
        self.after(120, self._poll_results)

    def _on_error(self, exc):
        self.set_busy(False)
        if yt is not None and isinstance(exc, yt.TranscriptError):
            self.set_status(first_line(exc), ok=False)
            messagebox.showerror("Could not get the transcript", str(exc))
        else:
            self.set_status("Something went wrong.", ok=False)
            messagebox.showerror("Something went wrong", traceback.format_exc())

    def format_options(self):
        return {
            "remove_brackets": self.remove_tags.get(),
            "remove_fillers": self.remove_fillers.get(),
        }

    def write_output(self, text, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        self.out_path = out_path
        self.open_btn.configure(state="normal")
        self.open_file_btn.configure(state="normal")
        lines = text.splitlines()
        head = "\n".join(lines[:PREVIEW_LINES])
        if len(lines) > PREVIEW_LINES:
            head += f"\n... ({len(lines) - PREVIEW_LINES} more lines)"
        self.show_preview(head)

    # -------------------------------------------------------------- YouTube

    def clear_urls(self):
        self.urls_text.delete("1.0", "end")
        self.set_status("")

    def parse_urls(self):
        """Split the box into one entry per line, keeping the order, no repeats."""
        raw = self.urls_text.get("1.0", "end")
        found, seen = [], set()
        for line in raw.replace(",", "\n").splitlines():
            candidate = line.strip().strip('"').strip("'")
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            found.append(candidate)
        return found

    def selected_language(self):
        """The dropdown entry the user picked, or None for 'best available'."""
        label = self.lang_var.get()
        if not label or label == BEST_AVAILABLE:
            return None
        for item in self.languages:
            if item["label"] == label:
                return item
        return None

    def get_transcripts(self):
        if self.busy:
            return
        if yt is None:
            messagebox.showerror(
                "Missing file",
                f"youtube_transcript.py could not be loaded.\n\n{YT_IMPORT_ERROR}")
            return

        entries = self.parse_urls()
        if not entries:
            self.set_status("Paste at least one YouTube link first.", ok=False)
            return

        expand = self.expand_playlists.get()
        try:
            per_playlist = max(1, int(self.playlist_count.get()))
        except (tk.TclError, ValueError):
            per_playlist = 10

        # Sort the links now so bad ones are reported without any network use.
        # Playlists stay unexpanded here - that needs a fetch, so the worker does it.
        plan, rejected = [], []
        for entry in entries:
            playlist_id = yt.extract_playlist_id(entry)
            try:
                video_id = yt.extract_video_id(entry)
                reason = None
            except yt.TranscriptError as exc:
                video_id, reason = None, first_line(exc)

            if playlist_id or video_id:
                # Keep both: a shared youtu.be link names only the video, and the
                # playlist it belongs to has to be looked up from its watch page.
                plan.append({"playlist": playlist_id, "video": video_id,
                             "entry": entry})
            else:
                rejected.append((entry, reason or "No video in that link."))

        if not plan:
            self.set_status(f"No usable links ({len(rejected)} rejected).", ok=False)
            self.show_preview(self._summary([], rejected, []))
            return

        choice = self.selected_language()
        code = choice["code"] if choice else None
        generated = choice["generated"] if choice else None

        # Read every widget value here: the worker thread must not touch Tk.
        format_options = self.format_options()
        as_prose = self.format_prose.get()
        merge = self.merge_repeats.get()
        heading_on = self.add_heading.get()
        skip_existing = self.skip_existing.get()
        out_dir = self.out_dir

        self.set_busy(True)
        self.set_status("Working ...")

        def work(progress):
            if not self.dependency_ready():
                raise yt.TranscriptError(
                    "The youtube-transcript-api package is not installed.\n\n"
                    "Install it by opening a terminal and running:\n"
                    "    python -m pip install youtube-transcript-api")

            # Turn playlists into video ids first, so the count below is real.
            jobs, notes, seen = [], [], set()
            failures = list(rejected)
            for item in plan:
                playlist_id, video_id = item["playlist"], item["video"]
                info = None

                # A bare playlist link has no video of its own, so it expands
                # even when the user left expansion switched off.
                if expand or video_id is None:
                    if playlist_id:
                        progress("Reading playlist ...")
                        try:
                            info = yt.fetch_playlist(playlist_id)
                        except yt.TranscriptError as exc:
                            failures.append((item["entry"], first_line(exc)))
                            continue
                    elif video_id:
                        progress("Looking for this video's playlist ...")
                        info = yt.playlist_for_video(video_id)

                if info:
                    ids, start = yt.take_from(info, video_id, per_playlist)
                    note = (f'Playlist "{info["title"]}": taking {len(ids)} '
                            f'of {info["found"]} listed')
                    if start:
                        note += f", starting at #{start + 1}"
                    if info["capped"] and per_playlist > len(ids):
                        note += " - YouTube lists only 100 per page"
                    notes.append(note)
                    for found_id in ids:
                        if found_id not in seen:
                            seen.add(found_id)
                            jobs.append(found_id)
                    continue

                if expand and video_id and not playlist_id:
                    notes.append(f"No playlist found for {video_id} - "
                                 "took that video on its own.")
                if video_id and video_id not in seen:
                    seen.add(video_id)
                    jobs.append(video_id)

            done, languages, already, blocked = [], [], [], False
            total = len(jobs)
            for index, video_id in enumerate(jobs, start=1):
                if skip_existing:
                    # Costs no request, so a re-run after a failed batch asks
                    # YouTube only for what is genuinely missing.
                    have = existing_transcript(out_dir, video_id)
                    if have:
                        already.append(have.name)
                        continue

                progress(f"Downloading {index} of {total} ...")

                def waiting(seconds, attempt, index=index, total=total):
                    # Say why nothing is happening, so a pause is not mistaken
                    # for a hang.
                    progress(f"YouTube is throttling - waiting {seconds}s, then "
                             f"retrying {index} of {total} ...")

                fell_back = False
                try:
                    if not languages:
                        languages = yt.list_languages(video_id, on_wait=waiting)
                    snippets = yt.fetch_snippets(video_id, code, generated,
                                                 on_wait=waiting)
                except yt.RateLimited as exc:
                    # Retries are already exhausted; pressing on would only make
                    # the block worse, so stop and say where the run got to.
                    blocked = True
                    done.append({"ok": False, "id": video_id, "error": first_line(exc)})
                    notes.append(
                        f"Stopped at {index} of {total}: YouTube is rate-limiting this "
                        "network. Leave it a while - the block can last minutes or "
                        "longer - then run the same links again. Videos already saved "
                        "are simply written again, so nothing is lost.")
                    break
                except yt.TranscriptError as exc:
                    # One video missing the chosen language must not stop the run.
                    if not code:
                        done.append({"ok": False, "id": video_id,
                                     "error": first_line(exc)})
                        continue
                    try:
                        snippets = yt.fetch_snippets(video_id, on_wait=waiting)
                        fell_back = True
                    except yt.TranscriptError as inner:
                        done.append({"ok": False, "id": video_id,
                                     "error": first_line(inner)})
                        continue

                title = yt.fetch_title(video_id) or video_id
                if as_prose:
                    text = fmt.format_timed(snippets, **format_options)
                else:
                    text = finish([item["text"] for item in snippets],
                                  drop_empty=True, merge_repeats=merge)
                if heading_on:
                    # The same sanitised title the filename uses, so they match.
                    text = with_heading(text, yt.safe_filename(title,
                                                               fallback=video_id))
                path = output_for_video(title, video_id, out_dir)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                done.append({"ok": True, "id": video_id, "title": title,
                             "path": path, "captions": len(snippets),
                             "fallback": fell_back})
            if already:
                notes.append(f"Already saved, so not fetched again: {len(already)}")
            return {"done": done, "rejected": failures, "languages": languages,
                    "notes": notes, "blocked": blocked, "already": already}

        self.run_in_background(work, self._on_batch_done)

    @staticmethod
    def dependency_ready():
        try:
            import youtube_transcript_api  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _summary(done, rejected, notes=()):
        """One line per video, so a part-successful run is still readable."""
        saved = [item for item in done if item["ok"]]
        failed = [item for item in done if not item["ok"]]
        lines = []
        for note in notes:
            lines.append(note)
        if notes:
            lines.append("")
        if saved:
            lines.append(f"Saved {len(saved)} transcript(s):")
            for item in saved:
                note = "   (chosen language unavailable - used best available)" \
                    if item.get("fallback") else ""
                lines.append(f"  OK    {item['path'].name}{note}")
        if failed or rejected:
            if lines:
                lines.append("")
            lines.append(f"Skipped {len(failed) + len(rejected)}:")
            for item in failed:
                lines.append(f"  FAIL  {item['id']} - {item['error']}")
            for entry, reason in rejected:
                lines.append(f"  FAIL  {entry[:60]} - {reason}")
        return "\n".join(lines)

    def _on_batch_done(self, result):
        done = result["done"]
        rejected = result["rejected"]
        languages = result["languages"]
        notes = result["notes"]
        already = result["already"]
        blocked = result["blocked"]

        if languages:
            self.languages = languages
            labels = [BEST_AVAILABLE] + [item["label"] for item in languages]
            self.lang_box.configure(values=labels)
            if self.lang_var.get() not in labels:
                self.lang_var.set(BEST_AVAILABLE)

        saved = [item for item in done if item["ok"]]
        if saved:
            # "Open transcript" points at the last one written.
            self.out_path = saved[-1]["path"]
            self.open_btn.configure(state="normal")
            self.open_file_btn.configure(state="normal")

        self.show_preview(self._summary(done, rejected, notes))
        self.set_busy(False)

        skipped = len(done) - len(saved) + len(rejected)
        if blocked:
            # Name the cause in the status line: "nothing downloaded" on its own
            # reads like a broken app rather than a throttled connection.
            done_note = f"Saved {len(saved)} first. " if saved else ""
            self.set_status(
                f"{done_note}YouTube is rate-limiting this network - it is not your "
                "links. Leave it a while, then run them again.", ok=False)
        elif saved and not skipped:
            self.set_status(f"Saved {len(saved)} transcript(s) to {self.out_dir}")
        elif saved:
            self.set_status(f"Saved {len(saved)}, skipped {skipped} - see the list above.")
        elif already and not skipped:
            self.set_status(f"All {len(already)} were already saved in that folder.")
        else:
            self.set_status("Nothing could be downloaded - see the list above.", ok=False)

    # ------------------------------------------------------------ text file

    def choose_file(self):
        picked = filedialog.askopenfilename(
            title="Choose a transcript file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if picked:
            self.set_file(Path(picked))

    def set_file(self, path: Path):
        if not path.is_file():
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        self.in_path = path
        self.file_label.configure(text=str(path), foreground="#000000")
        self.clean_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.open_file_btn.configure(state="disabled")
        self.set_status("")
        self.show_preview("")

    def clean_file(self):
        if not self.in_path or self.busy:
            return
        try:
            text, _encoding = read_text(self.in_path)
            # Lift off a title the file already carries, so reflowing the text
            # does not fold it into the first paragraph.
            text = split_heading(text, heading_from_name(self.in_path))
            cleaned, changed = strip_timestamps(
                text, anywhere=self.anywhere.get(), drop_empty=True,
                merge_repeats=self.merge_repeats.get())
            if self.format_prose.get():
                # A text file has no timing, so the source's own punctuation
                # decides the sentences unless estimating is switched on.
                cleaned = fmt.format_lines(
                    cleaned.splitlines(),
                    guess_breaks=self.guess_breaks.get(),
                    **self.format_options())
            out_path = default_output(self.in_path)
            if out_path.resolve() == self.in_path.resolve():
                messagebox.showerror("Error", "Output would overwrite the input file.")
                return
            if self.add_heading.get():
                # No video title here, so the source filename supplies it.
                cleaned = with_heading(cleaned, heading_from_name(self.in_path))
            self.write_output(cleaned, out_path)
        except Exception:
            self.set_status("Something went wrong.", ok=False)
            messagebox.showerror("Something went wrong", traceback.format_exc())
            return
        self.set_status(f"Cleaned {changed} line(s) -> {out_path.name}")

    # --------------------------------------------------------------- output

    def choose_dir(self):
        picked = filedialog.askdirectory(title="Where should transcripts be saved?",
                                         initialdir=str(self.out_dir))
        if picked:
            self.out_dir = Path(picked)
            self.dir_label.configure(text=str(self.out_dir))

    def open_folder(self):
        if self.out_path:
            os.startfile(self.out_path.parent)

    def open_file(self):
        if self.out_path and self.out_path.exists():
            os.startfile(self.out_path)


def main():
    argument = sys.argv[1] if len(sys.argv) > 1 else None
    initial_url = argument if (argument and looks_like_youtube(argument)) else None
    initial_file = argument if (argument and not initial_url) else None

    root = tk.Tk()
    root.title("Transcript Cleaner")
    root.geometry("760x660")
    root.minsize(620, 560)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root, initial_file=initial_file, initial_url=initial_url)
    root.mainloop()


if __name__ == "__main__":
    main()
