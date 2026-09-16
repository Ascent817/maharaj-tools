===========================================================
  FIND & REPLACE  v1.0
  Bulk word replacement in a text file, driven by a CSV list
===========================================================

WHAT IT DOES
------------
  1. You give it a text/Excel file (.txt/.xls) - the input
  2. You give it a reference list (.csv)   - column A = the word to find
                                             column B = the word to put instead
  3. It writes a matching output  (.txt/.xls) - the output

Your original input file is never changed.


HOW TO START IT
---------------
Double-click:      Find and Replace.bat

That is all. A window opens with three boxes to fill in.
(The .bat file finds Python for you. If you ever move the app, keep
"Find and Replace.bat" and "find_replace_app.py" in the same folder.)

If Windows says Python is not installed, get it from
https://www.python.org/downloads/windows/ and tick
"Add python.exe to PATH" during setup.

Want it to run on a PC with no Python at all?
Double-click "Build standalone EXE.bat" once (needs internet). It
produces dist\FindAndReplace.exe - a single file you can copy anywhere.


HOW TO USE THE WINDOW
---------------------
  1. Input file      - Browse to your .txt or legacy Excel .xls file.
  2. Reference file  - Browse to your .csv file.
                       The pairs appear in the Log box straight away, so
                       you can confirm the list was read correctly.
  3. Output file     - Filled in as <name>_replaced.txt or
                       <name>_replaced.xls.
                       Change it if you want it somewhere else.
  4. Click "Run Find & Replace".

The Log box then shows how many times each word was replaced. Any word
that was never found in the input is marked with "!" at the start of the
line, so nothing fails silently.

For .xls files, the first worksheet is processed. Text cells are replaced;
numbers, dates, booleans and blanks keep their value types. The output is a
values-only .xls workbook with the same first-sheet name. Formatting, formulas,
charts, macros and additional worksheets are not copied.


THE REFERENCE CSV
-----------------
Make it in Excel, Google Sheets or Notepad. Two columns:

    Find,Replace With          <- a header row is optional, it is detected
    colour,color
    organisation,organization
    John Smith,J. Smith

Notes:
  - A header row is detected automatically. You can override that with the
    "First row of the CSV" setting if your real data happens to start with
    a word like "find" or "old".
  - Phrases with spaces are fine ("John Smith" above).
  - A comma inside a word needs quotes: "Smith, John",JS
  - Leave column B empty to DELETE the word instead of replacing it.
  - Extra columns beyond A and B are ignored.
  - Blank rows are ignored; a word listed twice keeps its first entry and
    a note appears in the log.
  - Semicolon-separated files (some European Excel versions) also work.


OPTIONS
-------
  Whole words only
      Off (default): "cat" also matches inside "catalog".
      On:            only the standalone word "cat" is replaced.

  Ignore upper/lower case
      Off (default): "Colour" is left alone if your list says "colour".
      On:            Colour, colour and COLOUR are all replaced.
      (The replacement is written exactly as typed in column B.)

  Open the output file when finished
      Opens the result in Notepad, or whatever opens .txt on your PC.


THINGS IT GETS RIGHT
--------------------
  - Replacements never cascade. If your list says cat->dog and dog->fox,
    a "cat" in the text becomes "dog" and stops there - it does not carry
    on to "fox". Each part of the text is replaced once, in one pass.
  - The longest match wins. With both "New York"->"NY" and
    "New York City"->"NYC" in the list, "New York City" becomes "NYC".
  - Punctuation and symbols in your words are treated literally, so
    entries like "C++", "a.b" or "$total" behave as written.
  - Line endings and file encoding are preserved (UTF-8, UTF-16 and
    Windows ANSI files are all handled; a file without a byte-order mark
    does not gain one).


COMMAND LINE (optional)
-----------------------
For scripting or scheduled jobs, no window:

    python find_replace_app.py input.txt list.csv output.txt

Flags: --whole-word  --ignore-case  --skip-header  --no-header
The same summary is printed to the console. Exit code 0 = success.


WHAT IS IN THIS FOLDER
----------------------
  Find and Replace.bat      <- double-click this to run the app
  find_replace_app.py       <- the program itself
  Build standalone EXE.bat  <- optional: makes a Python-free .exe
  README.txt                <- this file
  samples\                  <- a worked example you can try immediately
      sample_input.txt
      sample_replacements.csv
      sample_output.txt     <- the result of running the two files above

Try the samples first: run the app, pick sample_input.txt and
sample_replacements.csv, and click Run.
