#!/usr/bin/env python3
"""
format_transcript.py - turn raw caption lines into readable prose.

What this does:
  * strips [sound tags] and (parenthetical asides)
  * tidies spacing and stray punctuation
  * joins caption fragments into sentences and paragraphs
  * capitalises sentence starts (Latin scripts only)

How sentence breaks are decided:
  * Downloads carry per-caption timing, so a PAUSE in the speech marks the
    break: a short gap ends a sentence, a long gap starts a new paragraph.
    That is a real signal, not a guess.
  * Plain text files have no timing. If the text already has punctuation it
    is used as-is; otherwise breaks can only be estimated from word count,
    which is approximate - so that is opt-in via guess_breaks.

This does NOT do grammatical punctuation restoration; that needs a language
model. It produces readable paragraphs, not a professionally punctuated text.
"""

import re
import textwrap

WRAP_WIDTH = 100

# Sentence gap defaults, in seconds, tuned against real caption timing.
SENTENCE_GAP = 0.65
PARAGRAPH_GAP = 2.0
MAX_SENTENCE_WORDS = 40
SENTENCES_PER_PARAGRAPH = 5

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# [Music], (laughs), {inaudible} - kept short so real bracketed text survives
BRACKETED = re.compile(r"[\[\(\{][^\[\]\(\)\{\}]{0,80}[\]\)\}]")
ENDS_SENTENCE = re.compile(r"[.!?।॥][\"'\)\]]?$")
SPLIT_SENTENCES = re.compile(r"(?<=[.!?।॥])\s+")

# Hesitation noises that transcribers write out. Deliberately conservative:
# "ah" and "oh" are left alone because they carry meaning in real speech.
FILLERS = re.compile(
    r"(?<!\w)(?:uh+|um+|mm+|mhm+|hmm+|erm|er)(?!\w)[\s,]*",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------

def is_indic(text: str) -> bool:
    """True when the text is mostly Devanagari, which changes the punctuation."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if DEVANAGARI.match(c)) / len(letters) > 0.3


def terminator(text: str) -> str:
    """Devanagari ends sentences with a danda, Latin scripts with a period."""
    return "।" if is_indic(text) else "."


def strip_brackets(text: str) -> str:
    """Remove [sound tags] and (asides), including unclosed leftovers."""
    previous = None
    while previous != text:
        previous = text
        text = BRACKETED.sub(" ", text)
    # An opening bracket with no partner, e.g. a tag split across captions.
    text = re.sub(r"[\[\(\{][^\[\]\(\)\{\}]{0,80}$", " ", text)
    text = re.sub(r"^[^\[\]\(\)\{\}]{0,80}[\]\)\}]", " ", text)
    return text


def strip_fillers(text: str) -> str:
    """Drop hesitation noises like 'uh' and 'mhm' without touching real words."""
    cleaned = FILLERS.sub(" ", text)
    # A caption that was nothing but filler collapses to nothing.
    if not re.search(r"\w", cleaned):
        return ""
    return cleaned


def tidy_spacing(text: str) -> str:
    """Collapse whitespace and pull punctuation back against its word."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?।॥])", r"\1", text)
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"\s*-\s*-\s*", " - ", text)
    return text.strip()


def has_punctuation(lines) -> bool:
    """True if the source already punctuates its sentences."""
    checked = [line for line in lines if line.strip()]
    if not checked:
        return False
    ended = sum(1 for line in checked if ENDS_SENTENCE.search(line.strip()))
    return ended / len(checked) > 0.15


def capitalize_sentences(text: str) -> str:
    """Capitalise the first letter of each sentence, and the English 'i'."""
    if is_indic(text):
        return text

    def upper_first(match):
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"(^|[.!?]\s+|\n)([a-z])", upper_first, text)
    text = re.sub(r"\bi\b", "I", text)
    text = re.sub(r"\bi'(m|ve|ll|d)\b", lambda m: "I'" + m.group(1), text)
    return text


def _finish_sentence(words, sample: str) -> str:
    """Join words into one sentence and give it an ending mark."""
    sentence = tidy_spacing(" ".join(words))
    if not sentence:
        return ""
    if not ENDS_SENTENCE.search(sentence):
        sentence += terminator(sample)
    return sentence


def _render(paragraphs, wrap: bool) -> str:
    """Lay paragraphs out with a blank line between them."""
    blocks = []
    for sentences in paragraphs:
        body = " ".join(s for s in sentences if s).strip()
        if not body:
            continue
        body = capitalize_sentences(body)
        blocks.append(textwrap.fill(body, width=WRAP_WIDTH) if wrap else body)
    return "\n\n".join(blocks) + "\n" if blocks else ""


# --------------------------------------------------------------------------
# Formatting a download (timing available)
# --------------------------------------------------------------------------

def format_timed(snippets, remove_brackets: bool = True,
                 remove_fillers: bool = True,
                 sentence_gap: float = SENTENCE_GAP,
                 paragraph_gap: float = PARAGRAPH_GAP,
                 max_words: int = MAX_SENTENCE_WORDS,
                 wrap: bool = True) -> str:
    """
    Format captions that carry timing.

    `snippets` is a list of dicts with 'text', 'start' and 'duration'.
    Pauses between captions decide where sentences and paragraphs break.
    """
    cleaned = []
    for snippet in snippets:
        text = snippet.get("text", "")
        if remove_brackets:
            text = strip_brackets(text)
        if remove_fillers:
            text = strip_fillers(text)
        text = tidy_spacing(text)
        if text:
            cleaned.append({**snippet, "text": text})
    if not cleaned:
        return ""

    sample = " ".join(item["text"] for item in cleaned[:40])
    keep_existing = has_punctuation([item["text"] for item in cleaned])

    paragraphs, sentences, words = [], [], []

    def close_sentence():
        if words:
            sentence = (tidy_spacing(" ".join(words)) if keep_existing
                        else _finish_sentence(words, sample))
            if sentence:
                sentences.append(sentence)
            words.clear()

    def close_paragraph():
        close_sentence()
        if sentences:
            paragraphs.append(list(sentences))
            sentences.clear()

    for index, item in enumerate(cleaned):
        words.extend(item["text"].split())

        following = cleaned[index + 1] if index + 1 < len(cleaned) else None
        if following is None:
            break
        gap = following["start"] - (item["start"] + item.get("duration", 0.0))

        if keep_existing:
            # Trust the caption's own punctuation; timing only splits paragraphs.
            if ENDS_SENTENCE.search(item["text"]):
                close_sentence()
            if gap >= paragraph_gap:
                close_paragraph()
        else:
            if gap >= paragraph_gap:
                close_paragraph()
            elif gap >= sentence_gap or len(words) >= max_words:
                close_sentence()
            if len(sentences) >= SENTENCES_PER_PARAGRAPH:
                close_paragraph()

    close_paragraph()
    return _render(paragraphs, wrap)


# --------------------------------------------------------------------------
# Formatting a text file (no timing)
# --------------------------------------------------------------------------

def format_lines(lines, remove_brackets: bool = True, remove_fillers: bool = True,
                 guess_breaks: bool = False,
                 max_words: int = MAX_SENTENCE_WORDS,
                 sentences_per_paragraph: int = SENTENCES_PER_PARAGRAPH,
                 wrap: bool = True) -> str:
    """
    Format caption lines that have no timing.

    If the text is already punctuated, its own sentence marks are used. If it
    is not, sentence breaks can only be estimated from word count, so that
    happens only when guess_breaks is set.
    """
    cleaned = []
    for line in lines:
        text = strip_brackets(line) if remove_brackets else line
        if remove_fillers:
            text = strip_fillers(text)
        text = tidy_spacing(text)
        if text:
            cleaned.append(text)
    if not cleaned:
        return ""

    sample = " ".join(cleaned[:40])

    if has_punctuation(cleaned):
        joined = tidy_spacing(" ".join(cleaned))
        sentences = [s.strip() for s in SPLIT_SENTENCES.split(joined) if s.strip()]
    elif guess_breaks:
        sentences, words = [], []
        for line in cleaned:
            words.extend(line.split())
            if len(words) >= max_words:
                sentences.append(_finish_sentence(words, sample))
                words = []
        if words:
            sentences.append(_finish_sentence(words, sample))
    else:
        # No punctuation and no guessing: keep it as one flowing block.
        sentences = [tidy_spacing(" ".join(cleaned))]

    paragraphs = [sentences[i:i + sentences_per_paragraph]
                  for i in range(0, len(sentences), sentences_per_paragraph)]
    return _render(paragraphs, wrap)
