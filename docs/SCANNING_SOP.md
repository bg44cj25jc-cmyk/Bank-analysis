# How to scan a bank statement

**For the office. One page. Set it once on each machine and it stays set.**

StatementBridge reads the figures off the page and checks every one of them
against the running balance. It can correct a misread digit. It cannot recover
detail the scanner never captured — and the wrong preset throws most of it away
before the file is ever saved.

These settings are the single largest thing anyone can do for accuracy.

---

## The settings

| Setting | Use this | Not this |
|---|---|---|
| **Resolution** | **300 DPI** — 400 for dot-matrix or faint print | 150 or 200 DPI |
| **Colour mode** | **Greyscale** | Black & White / Text / Fax / Photo / Colour |
| **Auto-contrast**, auto-exposure, background removal | **Off** | Auto / Enhance |
| **Descreening** / moiré correction | **Off** | On |
| **Feed** | Square in the tray, paper guides closed to the stack | Loose or angled |
| **File type** | PDF | JPEG, or "compact/high-compression PDF" |

Everything else can stay on its default.

## Why these two matter most

**Greyscale, not black & white.** A "Text" or "Fax" preset stores each dot as
either pure black or pure white. That is half the reason the first batch of
statements could not be processed: measured on the Tripura Gramin ledger, every
page was 1-bit black-and-white. The soft grey edges around each character are
what the reader uses to tell `8` from `B` and `5` from `S`, and in that mode
they are gone before the file is saved. Nothing downstream can put them back.

**300 DPI, not 150.** 150 DPI is the default on most office machines because it
was chosen for emailing and faxing, where small files matter more than detail.
It puts too few dots across a digit to read it reliably. Both sample statements
came in at 150 DPI, and re-processing them at a higher setting afterwards does
**not** help — enlarging a small picture does not add detail, it only makes the
existing blur bigger.

## Where the settings live

The wording varies by machine, but every office MFP has these under a scan
profile or preset:

- On the panel, look for **Scan Settings**, **Scan to PDF**, or **Original Type**.
- Resolution may be listed as **Resolution**, **Quality** or **DPI**.
- Greyscale may be listed as **Grayscale**, **Gray** or **256 Levels of Gray**.
- If the machine offers **"Compact PDF"**, **"High compression"** or
  **"Small file"** — turn it off. It reaches the small size by discarding
  exactly the detail this depends on.

Save it as the default scan profile so nobody has to remember it.

## Before you scan

- Take the staples out. A folded corner hides a figure.
- Square the stack and close the paper guides. A page that goes through crooked
  smears each row across two scan lines.
- Scan a statement as **one PDF per account, per financial year**.
- Continuous stationery: it is fine if more than one printed page lands on a
  sheet. The system reads the printed page numbers and reports what it finds.

## Check it worked

Drop the PDF into StatementBridge. It grades the scan in a couple of seconds,
before any processing starts, and tells you the setting to change if something
is wrong. You do not have to wait for the job to run to find out.

From a terminal:

```
statementbridge quality "statement.pdf"
```

| It says | Meaning |
|---|---|
| **PASS** | 300 DPI or better, greyscale. Good to process. |
| **WARN** | Usable, but expect more rows to need checking by hand. |
| **REJECT** | Below 200 DPI, or scanned in black-and-white. Rescan it. |

A REJECT is worth acting on. At 150 DPI only about **four rows in ten** could be
verified against the running balance; the rest had to be checked by a person.
That is the difference between a statement that posts itself and an afternoon of
manual work.

## If the statement came from the bank's website

Download the **PDF** rather than printing and scanning it. A downloaded
statement carries the text directly, is read exactly, and skips all of the
above. Do not print it out and scan it back in — that throws away a perfect copy
and turns it into a photograph of itself.
