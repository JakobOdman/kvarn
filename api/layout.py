"""
layout.py - a page's text in reading order, rebuilt from the word boxes.

read_document.py gives the text in the order it is stored in the PDF, which can put a table's labels and
values far apart. With word positions ("Ordpositioner") the words are laid out as they are on the page:
line by line from the top, left to right, with spaces for the gaps so columns stay apart.
"""
from statistics import median


def layout_text(page: dict) -> str:
    """The page as laid out, or its plain text when there are no word boxes (Office files) or the AI read it.
    A page the AI read keeps the boxes of its thin text layer, but its text is the AI's: that is what counts."""
    words = page.get("words")
    if not words or page.get("reader") != "pdf_text":
        return page["text"]

    heights = [w["y1"] - w["y0"] for w in words if w["y1"] > w["y0"]]
    line_height = median(heights) if heights else 10
    char_width = median((w["x1"] - w["x0"]) / len(w["t"]) for w in words if w["t"] and w["x1"] > w["x0"]) or 5

    # Lines: a word belongs to the line whose middle is within half a line height of its own
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2):
        middle = (w["y0"] + w["y1"]) / 2
        if lines and abs(middle - lines[-1][0]["_middle"]) < line_height / 2:
            lines[-1].append(w | {"_middle": lines[-1][0]["_middle"]})
        else:
            lines.append([w | {"_middle": middle}])

    out = []
    previous = None
    for line in lines:
        if previous is not None and line[0]["_middle"] - previous > line_height * 1.8:
            out.append("")  # a bigger gap: a blank line, like a new paragraph
        previous = line[0]["_middle"]
        text = ""
        for w in sorted(line, key=lambda w: w["x0"]):
            column = round(w["x0"] / char_width)
            text += " " * max(1 if text else 0, column - len(text)) + w["t"]
        out.append(text.rstrip())
    indent = min((len(l) - len(l.lstrip()) for l in out if l), default=0)  # the page margin
    return "\n".join(l[indent:] for l in out)
