# Transcript Cleaner

Paste one or more YouTube links into the app. A single-video link creates one
transcript. A playlist link creates one combined transcript containing the
selected number of videos, beginning at the linked video or `index=` position.
Every playlist section is numbered with its original playlist position and
headed by the video title.

Double-click `Remove Timestamps.bat` to install the required Python packages
on first use and launch the app. `Transcript Cleaner.exe` is the standalone
build for computers without Python.

If a selected video has no transcript, the combined file contains a labeled
placeholder in that position. If YouTube rate-limits a batch, completed
sections are saved in an `_partial.txt` file so it cannot be mistaken for a
complete cached result.
