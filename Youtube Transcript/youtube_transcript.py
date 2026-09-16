#!/usr/bin/env python3
"""
youtube_transcript.py — fetch a video's transcript and title from a YouTube link.

Used by remove_timestamps.py and by the "Remove Timestamps" GUI.
Requires the youtube-transcript-api package:  python -m pip install youtube-transcript-api
"""

import html
import json
import re
import time
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) transcript-tool/1.0"

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ILLEGAL_FILENAME = re.compile(r'[<>:"/\|?*\x00-\x1f]')


class TranscriptError(Exception):
    """Anything that stopped us getting a transcript, with a readable message."""


class RateLimited(TranscriptError):
    """YouTube refused because too many requests came too quickly."""


# YouTube throttles bursts from one address, which is what breaks a long batch.
# Requests are spaced out, and a refusal is retried after a growing pause.
MIN_SECONDS_BETWEEN_CALLS = 1.5
RETRY_PAUSES = (6, 15, 30)
BLOCKING_ERRORS = ("IpBlocked", "RequestBlocked", "TooManyRequests", "YouTubeRequestFailed")

_last_call_at = 0.0


def _pace():
    """Keep a minimum gap between calls to YouTube."""
    global _last_call_at
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _is_blocking(exc: Exception) -> bool:
    if isinstance(exc, RateLimited):
        return True
    if type(exc).__name__ in BLOCKING_ERRORS:
        return True
    text = str(exc).lower()
    return "too many requests" in text or "blocking requests" in text


def with_retry(call, on_wait=None):
    """
    Run a YouTube call, pausing and retrying when it is refused for rate limits.

    `on_wait(seconds, attempt)` lets the caller report the pause, so a batch
    that is waiting does not look like a batch that has frozen.
    """
    last = None
    for attempt, pause in enumerate((0,) + RETRY_PAUSES):
        if pause:
            if on_wait:
                on_wait(pause, attempt)
            time.sleep(pause)
        _pace()
        try:
            return call()
        except Exception as exc:
            if not _is_blocking(exc):
                raise
            last = exc
    raise RateLimited(
        "YouTube is refusing further requests from this network right now "
        "(too many in a short time). The block usually clears on its own, but it "
        "can last anywhere from a few minutes to an hour or so - leave it a while, "
        "then run the same links again."
    ) from last


def extract_video_id(url_or_id: str) -> str:
    """Pull the 11-character video id out of any common YouTube link form."""
    text = (url_or_id or "").strip().strip('"').strip("'")
    if not text:
        raise TranscriptError("No YouTube link was given.")
    if ID_RE.match(text):
        return text

    if "//" not in text:
        text = "https://" + text
    parts = urllib.parse.urlparse(text)
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = parts.path or ""

    if host in ("youtu.be", "y2u.be"):
        candidate = path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        query = urllib.parse.parse_qs(parts.query)
        if "v" in query:
            candidate = query["v"][0]
        else:
            segments = [s for s in path.split("/") if s]
            # /shorts/ID, /embed/ID, /live/ID, /v/ID
            if (segments and segments[0] in ("shorts", "embed", "live", "v")
                    and len(segments) > 1):
                candidate = segments[1]
            else:
                # Name the page they actually pasted, rather than reporting a
                # missing id: these are the easy links to grab by mistake.
                first = segments[0].lower() if segments else ""
                if first == "results":
                    raise TranscriptError(
                        "That is a YouTube search results page, not a video.\n\n"
                        "Open the video you want, then paste the link from its "
                        "own page.")
                if first.startswith("@") or first in ("channel", "c", "user"):
                    raise TranscriptError(
                        "That is a channel page, not a video.\n\n"
                        "Open a video on that channel, or one of its playlists, "
                        "and paste that link instead.")
                if first in ("feed", "hashtag", "shorts") or not segments:
                    raise TranscriptError(
                        "That is a YouTube browsing page, not a single video.\n\n"
                        "Open the video you want and paste its link.")
                candidate = segments[-1] if segments else ""
    else:
        raise TranscriptError(f"That does not look like a YouTube link:\n{url_or_id}")

    candidate = candidate.split("?")[0].split("&")[0]
    if not ID_RE.match(candidate):
        raise TranscriptError(f"Could not find a video id in:\n{url_or_id}")
    return candidate


# YouTube's playlist page ships its first pageful of items only; the
# continuation endpoint that would fetch the rest no longer returns them,
# so this is the honest ceiling for one request.
PLAYLIST_PAGE_ITEMS = 100
VIDEO_ID_IN_PAGE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
PAGE_TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def extract_playlist_id(url_or_id: str) -> str | None:
    """The list= id from a link, or None when the link is not part of a playlist."""
    text = (url_or_id or "").strip().strip('"').strip("'")
    if not text or "list=" not in text:
        return None
    if "//" not in text:
        text = "https://" + text
    parts = urllib.parse.urlparse(text)
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if not (host.endswith("youtube.com") or host.endswith("youtu.be")
            or host.endswith("youtube-nocookie.com")):
        return None
    values = urllib.parse.parse_qs(parts.query).get("list")
    return values[0] if values and values[0] else None


def _get_page(url: str, timeout: int = 25) -> str:
    _pace()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def fetch_playlist(playlist_id: str, limit: int | None = None) -> dict:
    """
    The videos in a playlist, in playlist order.

    Returns {'id', 'title', 'video_ids', 'found', 'capped'} where 'found' is how
    many the page listed and 'capped' says the page limit was hit, so the caller
    can tell the user that more videos may exist beyond what was read.
    """
    if playlist_id.startswith("RD"):
        raise TranscriptError(
            "That link points at an auto-generated YouTube mix, which has no "
            "fixed list of videos. Open the real playlist and use its link.")
    if playlist_id in ("WL", "LL"):
        raise TranscriptError(
            "Watch Later and Liked Videos are private to your account, so their "
            "contents cannot be read without signing in.")

    try:
        page = _get_page("https://www.youtube.com/playlist?list="
                         + urllib.parse.quote(playlist_id, safe=""))
    except Exception as exc:
        raise TranscriptError(f"Could not open that playlist ({type(exc).__name__}).") from exc

    video_ids = list(dict.fromkeys(VIDEO_ID_IN_PAGE.findall(page)))
    if not video_ids:
        raise TranscriptError(
            "No videos could be read from that playlist. It may be private, "
            "empty, or deleted.")

    match = PAGE_TITLE.search(page)
    title = ""
    if match:
        title = html.unescape(re.sub(r"\s*-\s*YouTube\s*$", "", match.group(1))).strip()

    found = len(video_ids)
    if limit is not None and limit > 0:
        video_ids = video_ids[:limit]
    return {
        "id": playlist_id,
        "title": title or playlist_id,
        "video_ids": video_ids,
        "found": found,
        "capped": found >= PLAYLIST_PAGE_ITEMS,
    }


PLAYLIST_ID_IN_PAGE = re.compile(r'"playlistId":"([A-Za-z0-9_-]{13,})"')


def find_playlists_for_video(video_id: str) -> list[str]:
    """
    Playlist ids named on a video's watch page.

    A shared youtu.be link usually carries no list= parameter, so this is the
    only way to tell which playlist a pasted video belongs to.
    """
    try:
        page = _get_page(f"https://www.youtube.com/watch?v={video_id}")
    except Exception:
        return []
    return [pid for pid in dict.fromkeys(PLAYLIST_ID_IN_PAGE.findall(page))
            if not pid.startswith("RD") and pid not in ("WL", "LL")]


def playlist_for_video(video_id: str) -> dict | None:
    """
    The playlist that actually contains this video, or None.

    A watch page can name several playlists, so each candidate is opened and
    the one that really lists the video wins - never merely the first named.
    """
    fallback = None
    for playlist_id in find_playlists_for_video(video_id):
        try:
            info = fetch_playlist(playlist_id)
        except TranscriptError:
            continue
        if video_id in info["video_ids"]:
            return info
        if fallback is None:
            fallback = info
    return fallback


def take_from(info: dict, start_video_id: str | None, limit: int) -> tuple[list[str], int]:
    """
    `limit` ids from a playlist, beginning at the given video when it is there.

    Starting at the pasted video is what the user means by "this one and the
    next few"; a playlist link with no video in it starts at the beginning.
    """
    ids = info["video_ids"]
    start = ids.index(start_video_id) if start_video_id in ids else 0
    return ids[start:start + max(1, limit)], start


def fetch_title(video_id: str, timeout: int = 20) -> str | None:
    """Video title via YouTube's public oEmbed endpoint. None if unavailable."""
    url = (
        "https://www.youtube.com/oembed?url="
        + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
        + "&format=json"
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response).get("title") or None
    except Exception:
        return None


def safe_filename(name: str, fallback: str = "transcript", max_len: int = 120) -> str:
    """Turn a video title into a filename Windows will accept."""
    cleaned = _ILLEGAL_FILENAME.sub("", html.unescape(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
        f"LPT{i}" for i in range(1, 10)
    }
    if not cleaned or cleaned.upper() in reserved:
        cleaned = fallback
    return cleaned


def _api():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise TranscriptError(
            "The youtube-transcript-api package is not installed.\n\n"
            "Install it with:\n    python -m pip install youtube-transcript-api"
        )
    return YouTubeTranscriptApi()


def _friendly_error(exc: Exception, video_id: str) -> TranscriptError:
    name = type(exc).__name__
    messages = {
        "TranscriptsDisabled": "This video has captions turned off, so there is no transcript to download.",
        "NoTranscriptFound": "No transcript is available in the requested language.",
        "VideoUnavailable": "That video is unavailable (it may be private, deleted, or region-locked).",
        "VideoUnplayable": "YouTube will not play that video, so its transcript cannot be read.",
        "AgeRestricted": "That video is age-restricted, so its transcript cannot be read without signing in.",
        "InvalidVideoId": f"'{video_id}' is not a valid video id.",
        "IpBlocked": "YouTube is blocking requests from this network. Try again later or from another connection.",
        "RequestBlocked": "YouTube blocked this request. Try again in a little while.",
    }
    if name in messages:
        return TranscriptError(messages[name])
    return TranscriptError(f"Could not get the transcript ({name}): {exc}")


def list_languages(video_id: str, on_wait=None) -> list[dict]:
    """Available transcripts: [{'code', 'name', 'generated', 'label'}, ...]."""
    api = _api()
    try:
        transcripts = with_retry(lambda: api.list(video_id), on_wait)
    except TranscriptError:
        raise
    except Exception as exc:
        raise _friendly_error(exc, video_id) from exc

    found = []
    for transcript in transcripts:
        kind = "auto-generated" if transcript.is_generated else "manual"
        # YouTube already tacks "(auto-generated)" onto some names; don't say it twice.
        name = re.sub(r"\s*\(auto[- ]generated\)\s*$", "", transcript.language,
                      flags=re.IGNORECASE).strip()
        found.append(
            {
                "code": transcript.language_code,
                "name": name,
                "generated": transcript.is_generated,
                "label": f"{name} ({kind})",
            }
        )
    # Manual captions are more accurate, so offer them first.
    found.sort(key=lambda item: (item["generated"], item["name"]))
    if not found:
        raise TranscriptError("This video has no transcripts available.")
    return found


def fetch_snippets(video_id: str, language_code: str | None = None,
                   generated: bool | None = None, on_wait=None) -> list[dict]:
    """
    Captions WITH their timing: [{'text', 'start', 'duration'}, ...].

    The timing is what lets the formatter tell a mid-sentence caption break
    from a real pause in the speech, so this is the richer of the two fetches.

    A language can offer both a manual and an auto-generated transcript under
    the same code, so `generated` says which of the two was asked for:
    True = auto-generated, False = manual, None = whichever is better.
    """
    api = _api()
    try:
        transcripts = with_retry(lambda: api.list(video_id), on_wait)
        if language_code and generated is True:
            transcript = transcripts.find_generated_transcript([language_code])
        elif language_code and generated is False:
            transcript = transcripts.find_manually_created_transcript([language_code])
        elif language_code:
            transcript = transcripts.find_transcript([language_code])
        else:
            available = list(transcripts)
            manual = [t for t in available if not t.is_generated]
            transcript = (manual or available)[0]
        fetched = with_retry(lambda: transcript.fetch(), on_wait)
    except TranscriptError:
        raise
    except Exception as exc:
        raise _friendly_error(exc, video_id) from exc

    snippets = []
    for snippet in fetched.snippets:
        text = html.unescape(snippet.text or "")
        text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
        if text:
            snippets.append(
                {
                    "text": text,
                    "start": float(getattr(snippet, "start", 0.0) or 0.0),
                    "duration": float(getattr(snippet, "duration", 0.0) or 0.0),
                }
            )
    if not snippets:
        raise TranscriptError("The transcript came back empty.")
    return snippets


def fetch_transcript(video_id: str, language_code: str | None = None,
                     generated: bool | None = None) -> list[str]:
    """Just the caption text, without timing."""
    return [item["text"] for item in fetch_snippets(video_id, language_code, generated)]


def download(url_or_id: str, language_code: str | None = None,
             generated: bool | None = None) -> dict:
    """One-shot fetch. Returns {'video_id', 'title', 'language', 'lines'}."""
    video_id = extract_video_id(url_or_id)
    lines = fetch_transcript(video_id, language_code, generated)
    return {
        "video_id": video_id,
        "title": fetch_title(video_id) or video_id,
        "language": language_code,
        "lines": lines,
    }
