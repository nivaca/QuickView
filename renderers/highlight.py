# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Syntax highlighting with Pygments, and the #! language guess."""

from .base import (
    HIGHLIGHT_MAX_BYTES,
)


# Interpreters whose name is not the lexer's name, or that Pygments has no
# alias for at all. Everything resolvable on its own is deliberately absent:
# bash, sh, zsh, ksh, fish, python, perl, ruby, php, lua, awk, tcl, julia,
# groovy, scala, pwsh, racket, elixir, crystal, raku, ocaml, make, csh, zig.
_SHEBANG_ALIASES = {
    "node": "javascript", "nodejs": "javascript", "bun": "javascript",
    "deno": "typescript", "ts-node": "typescript",
    "dash": "bash", "rscript": "r", "tclsh": "tcl", "wish": "tcl",
    "guile": "scheme", "sbcl": "common-lisp",
    "runhaskell": "haskell", "escript": "erlang",
    "osascript": "applescript",
}


# Names Pygments resolves to something unrelated. "v" is the V language, but
# get_lexer_by_name("v") hands back Verilog — colouring a V script as Verilog
# is worse than leaving it plain.
_SHEBANG_DENY = frozenset({"v"})


def _shebang_lexer(text: str):
    """The lexer a `#!` line names, or None.

    Deliberately *not* guess_lexer(): that runs every lexer's analyse_text()
    over the content, which is the slow, regex-heavy surface the filename
    path above exists to avoid — and it is wrong often enough to matter
    (`#!/usr/bin/env node` and `#!/usr/bin/awk -f` both guess "Text only").
    Reading the interpreter's name is exact and costs one split.
    """
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    if not text.startswith("#!"):
        return None
    # Capped: the "line" of a minified one-liner can be the whole file, and
    # nothing past a handful of arguments is ever the interpreter.
    line = text.split("\n", 1)[0][2:2 + 200].strip()
    parts = line.split()
    if not parts:
        return None

    prog = parts[0].rsplit("/", 1)[-1]
    if prog == "env":
        # `env -S deno run --allow-net`, `env FOO=bar python3` — the
        # interpreter is the first token that is neither a flag nor an
        # assignment. Without this, every `#!/usr/bin/env x` reads as "env".
        for token in parts[1:]:
            if token.startswith("-") or "=" in token:
                continue
            prog = token.rsplit("/", 1)[-1]
            break
        else:
            return None

    prog = prog.lower()
    if prog in _SHEBANG_DENY:
        return None

    # python3.12 -> python, ruby2.7 -> ruby, node20 -> node -> javascript.
    # The stripped name goes through the alias table too, or a versioned
    # interpreter that needs an alias would miss it.
    stripped = prog.rstrip("0123456789.")
    for candidate in (_SHEBANG_ALIASES.get(prog, prog),
                      _SHEBANG_ALIASES.get(stripped, stripped)):
        if not candidate:
            continue
        try:
            return get_lexer_by_name(candidate, ensurenl=False, stripnl=False)
        except ClassNotFound:
            continue
    return None


def highlight_text(source, name: str, limit: int, style_name: str = "one-dark") -> dict:
    """Read a text file and return it with colour spans for its syntax.

    Returns {"text", "truncated", "spans", "styles", "lexer"}. `spans` is a
    list of [start, length, style_index] over the *characters* of "text";
    only tokens that differ from the default colour are listed, and adjacent
    runs sharing a colour are merged, which is what keeps the result far
    smaller than the file.

    This runs in the jail on purpose. Pygments lexers are regexes, and a file
    crafted to make one backtrack would otherwise wedge the daemon that owns
    the window and the IPC socket; in here the worker's watchdog kills it and
    the daemon shows the file unhighlighted.
    """
    data = source.read(limit + 1) if hasattr(source, "read") else open(source, "rb").read(limit + 1)
    data = bytes(data)
    truncated = len(data) > limit
    text = data[:limit].decode("utf-8", errors="replace")
    # Normalised here, before anything measures an offset: the daemon's
    # QTextDocument stores "\n" line ends, so lexing "\r\n" text would put
    # every span one character further off with each line.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    out = {"text": text, "truncated": truncated, "spans": [], "styles": [],
           "lexer": None}
    if len(text) > HIGHLIGHT_MAX_BYTES:
        return out
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_for_filename
        from pygments.styles import get_style_by_name
        from pygments.token import Token
        from pygments.util import ClassNotFound
    except ImportError:
        return out  # highlighting is optional; plain text is a fine preview

    # By filename first. guess_lexer() is never used: it runs every lexer's
    # analyse_text() over the content, which is both slow and a lot more
    # regex surface. ensurenl=False keeps the text identical to what the
    # daemon shows, so the offsets below stay valid.
    try:
        lexer = get_lexer_for_filename(name, ensurenl=False, stripnl=False)
    except ClassNotFound:
        # No usable extension — a personal script like ~/bin/deploy. The
        # text is already read and decoded above, so its `#!` line costs
        # nothing to consult. An extension Pygments *does* know always
        # wins; this only fills the gap where there is none.
        lexer = _shebang_lexer(text)
        if lexer is None:
            return out
    try:
        style = get_style_by_name(style_name)
    except ClassNotFound:
        return out  # a style name that does not exist

    default = style.style_for_token(Token.Text).get("color")
    palette, styles, spans = {}, [], []
    # style_for_token() walks the token hierarchy on every call, which costs
    # more than the lexing does; there are only a handful of distinct token
    # types in a file, so ask once each.
    colour_of = {}
    pos = 0
    for ttype, value in lex(text, lexer):
        length = len(value)
        colour = colour_of.get(ttype)
        if colour is None:
            # Some lexers mint their own token types — YAML's
            # Literal.Scalar.Plain — that no style lists, and
            # style_for_token() raises KeyError on those rather than
            # inheriting. Climb to the nearest ancestor the style knows,
            # as Pygments' own formatters do.
            known = ttype
            while not style.styles_token(known) and known.parent is not None:
                known = known.parent
            colour = colour_of[ttype] = style.style_for_token(known).get("color") or ""
        if colour and colour != default and value.strip():
            index = palette.get(colour)
            if index is None:
                index = palette[colour] = len(styles)
                styles.append("#" + colour)
            if spans and spans[-1][2] == index and spans[-1][0] + spans[-1][1] == pos:
                spans[-1][1] += length  # one run, not two
            else:
                spans.append([pos, length, index])
        pos += length

    out["spans"], out["styles"], out["lexer"] = spans, styles, lexer.name
    return out
