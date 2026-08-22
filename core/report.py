"""The durable import record (prd.md sections 5.1 and 8).

An importer already knows everything an argument about a mask would need: what
the file claimed, who wrote it, what arrived, how far it sits from the source
and what could not be carried. Until now all of it went into one dialog and a
console, both of which are gone by the time anyone asks. This renders the same
material as text, which an adapter writes next to the host project, so the
answer outlives the session and the argument happens over evidence.

Pure: the caller supplies the timestamp and every measurement. Mirrored in
`ae/rotobridge_core.jsx` and checked against it byte for byte, because two
implementations formatting the same record differently would make two hosts
disagree about the same import.

Every frame number in a record is in the **destination's** numbering, offset
already applied. It is what an artist types into a timeline to look at the
frame the record names.
"""

import math

RULE = "-" * 78
LABEL = 15
SUFFIX = ".rotobridge.txt"


def path_for(anchor):
    """The record that sits beside `anchor`, whatever `anchor`'s extension.

    `anchor` is the host project when it has been saved - the record belongs
    with the comp holding the shapes, so someone opening it a month later finds
    it without knowing where the .rbj came from - and the source .rbj when it
    has not. Both adapters pick the anchor; the naming is here so they cannot
    pick different names for it.

    The extension is stripped the way `os.path.splitext` strips it, written out
    rather than imported so the ExtendScript mirror can say the same thing: only
    a dot in the last path component counts, and a leading dot is a name rather
    than an extension.
    """
    anchor = str(anchor)
    cut = anchor.rfind(".")
    slash = max(anchor.rfind("/"), anchor.rfind("\\"))
    if cut > slash + 1:
        anchor = anchor[:cut]
    return anchor + SUFFIX


def _num(value):
    """A number spelled the same way by both implementations.

    JavaScript has one number type, so `24.0` prints as `24` there and as
    `24.0` here. That is the one accepted divergence between the two writers
    (see `core/rbj.py`), and a record is a document the two hosts must produce
    identically, so whole numbers lose the trailing zero on both sides.
    """
    value = float(value)
    if value == int(value) and abs(value) < 1e16:
        return "%d" % int(value)
    return repr(value)


def _pixels(value):
    """A pixel measurement at four decimals, rounded half away from zero.

    `%.4f` rounds half to even and JavaScript's `toFixed` rounds half away from
    zero, so a residual that lands exactly on a tie would be spelled differently
    by the two hosts. The rule is stated here instead of inherited from either
    language.
    """
    scaled = int(math.floor(abs(float(value)) * 10000.0 + 0.5))
    sign = "-" if float(value) < 0.0 and scaled else ""
    return "%s%d.%04d" % (sign, scaled // 10000, scaled % 10000)


def _row(label, text):
    return label.ljust(LABEL) + text


def _tolerance(value):
    """The import mode, in words rather than as a float.

    `inf` is a legal tolerance and the two implementations spell it differently
    (`inf` against `Infinity`), so neither spelling is used.
    """
    if float(value) == float("inf"):
        return "unbounded (authored keys only)"
    if float(value) == 0.0:
        return "0 px (every frame keyed)"
    return _num(value) + " px"


def _shape_line(shape):
    """One shape's line: what arrived, and how far it sits from the file."""
    line = ("  %s: feather %s, %d point(s), %d authored key(s), %d corrective"
            % (shape["name"], shape["feather_model"], shape["points"],
               shape["authored"], shape["corrective"]))
    if shape["worst_frame"] is None:
        # `None` covers both of the drift pass's silent cases: every frame was
        # a key, or no frame between the keys moved at all. A bare "0.0000 px
        # at frame None" would read as a measurement, and naming the wrong one
        # of the two cases would be worse than naming neither.
        return line + "; nothing drifted from the file"
    return line + ("; worst drift %s px at frame %d"
                   % (_pixels(shape["residual"]), int(shape["worst_frame"])))


def _warnings(subject, messages):
    if not messages:
        # Stated rather than omitted. "Nothing was lost" is a claim the record
        # exists to support, and an absent section makes no claim at all.
        return ["no warnings " + subject]
    lines = ["%d warning%s %s:" % (len(messages),
                                   "" if len(messages) == 1 else "s", subject)]
    lines.extend("  - " + m for m in messages)
    return lines


def render(record):
    """One import as text, ending in a newline.

    `record` carries `written`, `host`, `target`, `source_file`, `source` (the
    file's own source object), `version`, `range`, `offset`, `tolerance`,
    `shapes` and the two warning lists. Every field is required: a record
    missing one is a bug in the adapter, and a hole in a document written to
    settle an argument is worse than a crash during the import that wrote it.
    """
    src = record["source"]
    first, last = record["range"]
    offset = int(record["offset"])
    shapes = record["shapes"]

    lines = [
        RULE,
        "RotoBridge import record",
        "",
        _row("written", record["written"]),
        _row("into", record["host"]),
        _row("target", record["target"]),
        "",
        _row("source file", record["source_file"]),
        _row("exported by", "%s %s" % (src["app"], src["app_version"])),
        _row("format", ".rbj version %d" % int(record["version"])),
        _row("source comp", "%d x %d at %s fps, pixel aspect %s"
             % (int(src["width"]), int(src["height"]), _num(src["fps"]),
                _num(src["pixel_aspect"]))),
        _row("source frames", "%d to %d" % (int(first), int(last))),
        _row("placed at", "%d to %d (offset %d)"
             % (int(first) + offset, int(last) + offset, offset)),
        _row("tolerance", _tolerance(record["tolerance"])),
        "",
        "%d shape(s):" % len(shapes),
    ]
    lines.extend(_shape_line(s) for s in shapes)
    lines.append("")
    lines.extend(_warnings("recorded when the file was written",
                           record["file_warnings"]))
    lines.append("")
    lines.extend(_warnings("from this import", record["import_warnings"]))
    lines.append("")
    return "\n".join(lines) + "\n"
