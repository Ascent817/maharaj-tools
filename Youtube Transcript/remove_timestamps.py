#!/usr/bin/env python3
"""
remove_timestamps.py - produce a clean transcript, from a YouTube link or a .txt file.

Two sources:

  1. A YouTube link. The transcript is downloaded for that video and saved as
     "<video title> [<video id>].txt", so the file matches the video it came from.

  2. A local .txt file. Timestamps are stripped out. Handles the YouTube
     "copy transcript" format, where the clock and the screen-reader duration
     label end up glued together at the start of each line, e.g. a line that
     begins "0:000 seconds" or "1:031 minute, 3 seconds" before the words.

Usage:
    python remove_timestamps.py https://youtu.be/VIDEOID
    python remove_timestamps.py https://youtu.be/VIDEOID --language hi
    python remove_timestamps.py https://youtu.be/VIDEOID --list-languages
    python remove_timestamps.py transcript.txt
    python remove_timestamps.py transcript.txt -o cleaned.txt --merge-repeats
    python remove_timestamps.py            (prompts for a link or file path)
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path

# --------------------------------------------------------------------------
# Timestamp patterns (only applied to local text files)
# --------------------------------------------------------------------------

# Clock part: 0:00, 12:34, 1:02:03, optionally wrapped in [] or ()
CLOCK = r"\d{1,2}(?::\d{2}){1,2}"

# Spoken duration label: "0 seconds", "16 seconds",
# "1 minute, 3 seconds", "2 hours, 5 minutes, 9 seconds"
DURATION = (
    r"(?:\d+\s*hours?\s*,?\s*)?"
    r"(?:\d+\s*minutes?\s*,?\s*)?"
    r"(?:\d+\s*seconds?)?"
)

TIMESTAMP = r"[\[\(]?\s*" + CLOCK + r"\s*[\]\)]?\s*" + DURATION

TIMESTAMP_AT_START = re.compile(r"^\s*(?:" + TIMESTAMP + r")\s*", re.IGNORECASE)
TIMESTAMP_ANYWHERE = re.compile(TIMESTAMP, re.IGNORECASE)

ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "cp1252")
WRAP_WIDTH = 100


# --------------------------------------------------------------------------
# Core cleaning
# --------------------------------------------------------------------------

def read_text(path: Path) -> tuple[str, str]:
    """Read the file, trying a few encodings. Returns (text, encoding_used)."""
    last_error = None
    for enc in ENCODINGS:
        try:
            return path.read_text(encoding=enc), enc
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_error = exc
    raise SystemExit(
        f"Could not decode {path} (tried: {', '.join(ENCODINGS)}). {last_error}"
    )


def strip_line(line: str, anywhere: bool = False) -> str:
    """Remove the timestamp(s) from a single line."""
    if anywhere:
        cleaned = TIMESTAMP_ANYWHERE.sub(" ", line)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    else:
        cleaned = TIMESTAMP_AT_START.sub("", line, count=1)
    return cleaned.strip()


def finish(lines, drop_empty: bool = False, merge_repeats: bool = False,
           paragraphs: bool = False) -> str:
    """Apply the shared tidy-up options and return the finished text."""
    out = []
    for line in lines:
        if drop_empty and not line.strip():
            continue
        if merge_repeats and out and line.strip().casefold() == out[-1].strip().casefold():
            continue
        out.append(line)

    if paragraphs:
        joined = " ".join(line.strip() for line in out if line.strip())
        joined = re.sub(r"\s{2,}", " ", joined)
        return textwrap.fill(joined, width=WRAP_WIDTH) + "\n" if joined else ""

    return "\n".join(out) + "\n" if out else ""


def strip_timestamps(text: str, anywhere: bool = False, drop_empty: bool = False,
                     merge_repeats: bool = False, paragraphs: bool = False) -> tuple[str, int]:
    """Clean a whole transcript file. Returns (cleaned_text, lines_changed)."""
    cleaned_lines, changed = [], 0
    for line in text.splitlines():
        cleaned = strip_line(line, anywhere=anywhere)
        if cleaned != line.strip():
            changed += 1
        cleaned_lines.append(cleaned)
    return finish(cleaned_lines, drop_empty, merge_repeats, paragraphs), changed


# --------------------------------------------------------------------------
# Output naming
# --------------------------------------------------------------------------

def default_output(path: Path) -> Path:
    # "_clean" rather than "_no_timestamps": the tool now formats as well as strips.
    return path.with_name(f"{path.stem}_clean{path.suffix or '.txt'}")


def output_for_video(title: str, video_id: str, folder) -> Path:
    """Name the file after the video it came from."""
    from youtube_transcript import safe_filename
    return Path(folder) / f"{safe_filename(title, fallback=video_id)} [{video_id}].txt"


def output_for_playlist(title: str, playlist_id: str, start: int, end: int,
                        folder, partial: bool = False) -> Path:
    """Stable name for one combined playlist selection."""
    from youtube_transcript import safe_filename
    suffix = "_partial" if partial else ""
    name = safe_filename(title, fallback=playlist_id, max_len=90)
    return Path(folder) / (
        f"{name} [{playlist_id}] {start:03d}-{end:03d}{suffix}.txt")


def playlist_section(position: int, title: str, video_id: str, text: str,
                     error: str | None = None) -> str:
    """One numbered, titled section in a combined playlist transcript."""
    heading = f"#{position} - {title or video_id} [{video_id}]"
    body = f"[Transcript unavailable: {error}]" if error else text.strip()
    return f"{heading}\n\n{body}\n"


# The " [dQw4w9WgXcQ]" tag that output_for_video() appends to a filename.
ID_SUFFIX = re.compile(r"\s*\[[A-Za-z0-9_-]{11}\]\s*$")


def heading_from_name(path) -> str:
    """The title part of a transcript filename, without the [videoid] tag."""
    stem = Path(path).stem
    stem = re.sub(r"_clean$", "", stem)
    return ID_SUFFIX.sub("", stem).strip()


def with_heading(text: str, heading: str) -> str:
    """Put the title on the first line, then a blank line, then the transcript."""
    heading = (heading or "").strip()
    if not heading:
        return text
    # Compare the first LINE, not the start of the text: a heading that has been
    # merged into an opening paragraph must not count as already present.
    first = text.lstrip("\n").split("\n", 1)[0].strip()
    if first == heading:
        return text
    return f"{heading}\n\n{text}"


def split_heading(text: str, heading: str) -> str:
    """
    Drop a title line the file already carries, so re-cleaning does not fold it
    into the opening paragraph. Returns the body without that line.
    """
    heading = (heading or "").strip()
    if not heading:
        return text
    lines = text.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].strip() == heading:
        return "\n".join(lines[index + 1:]).lstrip("\n")
    return text


def looks_like_youtube(text: str) -> bool:
    """True if this string should be treated as a link rather than a file path."""
    candidate = (text or "").strip().strip('"')
    if not candidate:
        return False
    try:
        if Path(candidate).exists():
            return False
    except OSError:
        pass
    lowered = candidate.lower()
    return any(mark in lowered
               for mark in ("youtube.com", "youtu.be", "youtube-nocookie.com"))


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def expand_playlists(sources, args):
    """
    Replace playlist links with the video ids they hold.

    A link is expanded when --playlist N asks for it, or when it names a
    playlist but no single video (so there is nothing else it could mean).
    Returns (sources, failures).
    """
    try:
        import youtube_transcript as yt
    except ImportError:
        return sources, 0

    expanded, failures, seen = [], 0, set()
    for source in sources:
        playlist_id = yt.extract_playlist_id(source)
        try:
            video_id = yt.extract_video_id(source)
        except yt.TranscriptError:
            video_id = None

        if playlist_id is None and video_id is None:
            expanded.append(source)          # a file path, or junk to report later
            continue
        if args.playlist is None and video_id is not None:
            expanded.append(source)          # a single video, no expansion asked for
            continue

        info = None
        if playlist_id:
            try:
                info = yt.fetch_playlist(playlist_id)
            except yt.TranscriptError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                failures += 1
                continue
        elif video_id:
            # A shared link carries no list=, so find the playlist from the video.
            print(f"Looking for the playlist that holds {video_id} ...")
            info = yt.playlist_for_video(video_id)
            if info is None:
                print(f"No playlist found for {video_id}; taking that video alone.")
                expanded.append(source)
                continue

        limit = args.playlist if args.playlist is not None else info["found"]
        ids, start = yt.take_from(info, video_id, limit)
        note = (f'Playlist "{info["title"]}": taking {len(ids)} '
                f'of {info["found"]} listed')
        if start:
            note += f", starting at #{start + 1}"
        if info["capped"] and limit > len(ids):
            note += " - YouTube lists only 100 per page"
        print(note)
        for found_id in ids:
            if found_id not in seen:
                seen.add(found_id)
                # A full link, not a bare id: the loop below routes on the URL.
                expanded.append(f"https://www.youtube.com/watch?v={found_id}")

    return expanded, failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Make a clean transcript from a YouTube link or a .txt file."
    )
    parser.add_argument("sources", nargs="*", metavar="SOURCE",
                        help="one or more YouTube links (or video ids), and/or "
                             "paths to .txt files")
    parser.add_argument("-o", "--output", help="path for the cleaned file")
    parser.add_argument("--outdir",
                        help="folder for downloaded transcripts (default: alongside this script)")
    parser.add_argument("--language", help="transcript language code, e.g. hi, en")
    parser.add_argument("--list-languages", action="store_true",
                        help="show which transcript languages a video offers, then exit")
    parser.add_argument("--anywhere", action="store_true",
                        help="text files: remove timestamps anywhere in a line, not just at the start")
    parser.add_argument("--drop-empty", action="store_true", help="drop blank lines")
    parser.add_argument("--merge-repeats", action="store_true",
                        help="collapse consecutive identical lines")
    parser.add_argument("--raw", action="store_true",
                        help="skip the prose formatting: one line per caption, as downloaded")
    parser.add_argument("--keep-tags", action="store_true",
                        help="keep [Music], (laughs) and similar bracketed tags")
    parser.add_argument("--keep-fillers", action="store_true",
                        help="keep hesitation noises such as 'uh' and 'mhm'")
    parser.add_argument("--guess-breaks", action="store_true",
                        help="text files with no punctuation: estimate sentence breaks by length")
    parser.add_argument("--no-heading", action="store_true",
                        help="do not put the title on the first line of the output")
    parser.add_argument("--playlist", type=int, metavar="N",
                        help="for a link that belongs to a playlist, transcribe the "
                             "N videos beginning at the linked video/index into one file")
    parser.add_argument("--encoding", default="utf-8", help="output encoding (default: utf-8)")
    args = parser.parse_args(argv)

    sources = list(args.sources)
    if not sources:
        typed = input("YouTube link(s) or path to a .txt file: ").strip()
        # Several links can be pasted at once; a lone path may contain spaces.
        if typed.lower().count("http") > 1:
            sources = [part.strip().strip('"') for part in typed.split() if part.strip()]
        elif typed:
            sources = [typed.strip('"')]
    if not sources:
        parser.error("nothing to do: give a YouTube link or a file path")

    failures = 0

    if args.output and len(sources) > 1:
        parser.error("-o/--output names a single file; with several sources use --outdir")

    for index, source in enumerate(sources, start=1):
        if len(sources) > 1:
            print(f"\n[{index}/{len(sources)}] {source}")
        if looks_like_youtube(source) or args.list_languages:
            try:
                import youtube_transcript as yt
                playlist_id = yt.extract_playlist_id(source)
                try:
                    video_id = yt.extract_video_id(source)
                except yt.TranscriptError:
                    video_id = None
            except ImportError:
                playlist_id = video_id = None
            if args.playlist is not None or (playlist_id and video_id is None):
                failures += run_playlist(source, args)
            else:
                failures += run_youtube(source, args)
        elif "://" in source:
            # A link, but not a YouTube one - don't mistake it for a file path.
            print(f"Error: not a YouTube link: {source}", file=sys.stderr)
            failures += 1
        else:
            failures += run_file(source, args)

    if len(sources) > 1:
        print(f"\nDone: {len(sources) - failures} succeeded, {failures} failed.")
    return 1 if failures else 0


def run_playlist(raw: str, args) -> int:
    """Download one playlist selection into one numbered transcript file."""
    import format_transcript as fmt
    import youtube_transcript as yt

    playlist_id = yt.extract_playlist_id(raw)
    try:
        video_id = yt.extract_video_id(raw)
    except yt.TranscriptError:
        video_id = None
    if playlist_id:
        info = yt.fetch_playlist(playlist_id)
    elif video_id:
        info = yt.playlist_for_video(video_id)
        if info is None:
            return run_youtube(raw, args)
    else:
        print(f"Error: no playlist found in {raw}", file=sys.stderr)
        return 1

    limit = args.playlist if args.playlist is not None else info["found"]
    ids, start = yt.take_from(info, video_id, limit, yt.extract_playlist_index(raw))
    if not ids:
        print("Error: no videos selected from that playlist.", file=sys.stderr)
        return 1

    title_by_id = {entry["id"]: entry["title"] for entry in info.get("entries", [])}
    sections, failures = [], 0
    for offset, selected_id in enumerate(ids):
        position = start + offset + 1
        title = title_by_id.get(selected_id) or yt.fetch_title(selected_id) or selected_id
        try:
            snippets = yt.fetch_snippets(selected_id, args.language)
            if args.raw:
                cleaned = finish([item["text"] for item in snippets],
                                 drop_empty=True, merge_repeats=args.merge_repeats)
            else:
                cleaned = fmt.format_timed(
                    snippets, remove_brackets=not args.keep_tags,
                    remove_fillers=not args.keep_fillers)
            sections.append(playlist_section(position, title, selected_id, cleaned))
        except yt.TranscriptError as exc:
            failures += 1
            sections.append(playlist_section(
                position, title, selected_id, "", error=str(exc).split("\n")[0]))
            if isinstance(exc, yt.RateLimited):
                for rest_offset, rest_id in enumerate(ids[offset + 1:], offset + 1):
                    rest_position = start + rest_offset + 1
                    sections.append(playlist_section(
                        rest_position, title_by_id.get(rest_id, rest_id), rest_id, "",
                        error="not attempted because YouTube rate-limited the batch"))
                    failures += 1
                break

    folder = Path(args.outdir).expanduser() if args.outdir else Path(__file__).resolve().parent
    folder.mkdir(parents=True, exist_ok=True)
    if args.output:
        out_path = Path(args.output).expanduser()
    else:
        out_path = output_for_playlist(
            info["title"], info["id"], start + 1, start + len(ids), folder,
            partial=bool(failures))
    out_path.write_text("\n".join(sections), encoding=args.encoding)
    print(f"Playlist: {info['title']}")
    print(f"Videos  : {len(ids)} selected, starting at #{start + 1}")
    print(f"Wrote   : {out_path}")
    return 1 if failures else 0


def run_youtube(raw: str, args) -> int:
    try:
        import youtube_transcript as yt
    except ImportError:
        print("Error: youtube_transcript.py is missing from this folder.", file=sys.stderr)
        return 1

    try:
        video_id = yt.extract_video_id(raw)
        if args.list_languages:
            print(f"Transcripts available for {video_id}:")
            for item in yt.list_languages(video_id):
                print(f"  {item['code']:<8} {item['label']}")
            return 0

        print(f"Downloading transcript for {video_id} ...")
        snippets = yt.fetch_snippets(video_id, args.language)
        title = yt.fetch_title(video_id) or video_id
    except yt.TranscriptError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    lines = [item["text"] for item in snippets]
    # A downloaded transcript carries no inline timestamps, so the regex is skipped.
    if args.raw:
        cleaned = finish(lines, drop_empty=True, merge_repeats=args.merge_repeats)
    else:
        # Timing is available here, so pauses in the speech drive the breaks.
        import format_transcript as fmt
        cleaned = fmt.format_timed(
            snippets,
            remove_brackets=not args.keep_tags,
            remove_fillers=not args.keep_fillers,
        )

    if args.output:
        out_path = Path(args.output).expanduser()
    else:
        folder = Path(args.outdir).expanduser() if args.outdir else Path(__file__).resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        out_path = output_for_video(title, video_id, folder)

    if not args.no_heading:
        # The same sanitised title the filename uses, so the two always match.
        cleaned = with_heading(cleaned, yt.safe_filename(title, fallback=video_id))

    out_path.write_text(cleaned, encoding=args.encoding)
    print(f"Video   : {title}")
    print(f"Lines   : {len(lines)} caption line(s)")
    print(f"Wrote   : {out_path}")
    return 0


def run_file(raw: str, args) -> int:
    in_path = Path(raw).expanduser()
    if not in_path.is_file():
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        return 1

    text, enc_used = read_text(in_path)
    # Lift off a title this file already carries, so it is not folded into the
    # first paragraph when the text is reflowed.
    text = split_heading(text, heading_from_name(in_path))
    cleaned, changed = strip_timestamps(
        text, anywhere=args.anywhere, drop_empty=args.drop_empty,
        merge_repeats=args.merge_repeats,
    )
    if not args.raw:
        # No timing in a text file, so the source's own punctuation is used.
        import format_transcript as fmt
        cleaned = fmt.format_lines(
            cleaned.splitlines(),
            remove_brackets=not args.keep_tags,
            remove_fillers=not args.keep_fillers,
            guess_breaks=args.guess_breaks,
        )

    out_path = Path(args.output).expanduser() if args.output else default_output(in_path)
    if out_path.resolve() == in_path.resolve():
        print("Error: output path is the same as the input path.", file=sys.stderr)
        return 1

    if not args.no_heading:
        # No video title here, so the source filename supplies the heading.
        cleaned = with_heading(cleaned, heading_from_name(in_path))

    out_path.write_text(cleaned, encoding=args.encoding)

    print(f"Read    : {in_path}  ({len(text.splitlines())} lines, decoded as {enc_used})")
    print(f"Cleaned : {changed} line(s) had a timestamp removed")
    print(f"Wrote   : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
