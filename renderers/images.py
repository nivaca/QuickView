# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Still images, Photoshop and Krita/OpenRaster composites, animations."""

from .base import (
    _encode,
)


def decode_image(source, max_w: int, max_h: int) -> tuple:
    """(QImage, "W×H") — the decode alone, without choosing a wire format.

    Split out of render_image so a caller that wants both the raw pixels
    and an encoded copy (the worker: pixels to show now, a cache entry to
    keep) pays for one decode instead of two.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImageIOHandler, QImageReader

    reader = QImageReader(source)
    reader.setAutoTransform(True)

    # Ask the decoder for a preview-sized image up front instead of decoding
    # full-size and downscaling after: for JPEG this engages libjpeg's DCT
    # scaling and cuts decode time to a fraction. size() only parses the
    # header; it is invalid for formats whose handler can't report it, and
    # those fall back to the decode-then-scale path below.
    orig = None
    size = reader.size()
    if size.isValid():
        # EXIF rotations of 90°/270° swap the displayed axes; fit the box in
        # display orientation, then hand the decoder its pre-rotation size.
        rotated = bool(
            reader.transformation()
            & QImageIOHandler.Transformation.TransformationRotate90
        )
        shown = size.transposed() if rotated else size
        orig = f"{shown.width()}×{shown.height()}"
        if shown.width() > max_w or shown.height() > max_h:
            fit = shown.scaled(max_w, max_h, Qt.KeepAspectRatio)
            reader.setScaledSize(fit.transposed() if rotated else fit)

    img = reader.read()
    if img.isNull():
        # Photoshop and Krita files each store a flattened copy of
        # themselves — try that before calling the file unreadable. Routing
        # them through here rather than through branches of their own is
        # what buys them the cache, the prefetch and the titlebar
        # dimensions for free.
        #
        # Whether this runs at all depends on the machine. Qt on its own has
        # no psd/kra handler, but kimageformats adds one (along with xcf,
        # avif, jxl and the raw formats), and a distro PySide6 will load it
        # from /usr/lib/qt6/plugins — a bundled one never can. So on a KDE
        # desktop these files are usually decoded above and the parsers
        # below are the fallback for everyone else. The tests call them
        # directly for that reason; see PsdDecoding.decoded.
        img, orig = _decode_native(source, max_w, max_h)
        if img is None:
            raise RuntimeError(f"unsupported or corrupt: {reader.errorString()}")

    if orig is None:
        orig = f"{img.width()}×{img.height()}"
    if img.width() > max_w or img.height() > max_h:
        img = img.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return img, orig


def render_image(source, max_w: int, max_h: int) -> bytes:
    """Decode one image, downscaled to fit max_w x max_h, as PNG bytes.

    The original dimensions travel along in a "QuickView:OrigSize" tEXt
    chunk. `source` is a path or a QIODevice.
    """
    img, orig = decode_image(source, max_w, max_h)
    img.setText("QuickView:OrigSize", orig)
    return _encode(img)


# --- Photoshop -------------------------------------------------------------
#
# Qt ships no PSD handler, but a .psd carries two preview-shaped things that
# cost nothing next to its layer stack: a flattened composite of the whole
# document ("merged image data", written whenever "Maximize Compatibility"
# is on, which is the default), and a small JPEG thumbnail in the image
# resources. Neither needs a single layer to be parsed, so the expensive
# half of the format is exactly the half a preview can skip.

# A PSD header is four bytes of width, four of height and two of channel
# count, all attacker-chosen; multiplied together they ask for as much
# memory as the file cares to name. The jail has no memory limit of its own,
# so — as with PDF_MAX_PAGE_PX — the bound has to be here.
PSD_MAX_PIXELS = 80_000_000


PSD_MAX_CHANNELS = 56


# Image resources are a linked list walked by length fields. A file can
# describe an arbitrarily long one; a thumbnail is never far in.
PSD_MAX_RESOURCES = 4096


# 8BIM resource ids for the embedded thumbnail. 1033 is the Photoshop 4.0
# one and stores its JPEG with the red and blue channels swapped.
PSD_THUMB_IDS = (1036, 1033)


# A thumbnail is a few tens of KiB. The resource header can claim any size
# up to the file's own, and this one is read into memory whole.
PSD_MAX_THUMB_BYTES = 8 * 1024 * 1024


# The decimated result, before decode_image's smooth scale. Whole-pixel
# strides cannot bring a degenerate canvas — one pixel wide and millions
# tall — inside the requested box, and a 4K box is 8 megapixels, so this
# only ever fires on a shape no preview could show anyway.
PSD_MAX_PREVIEW_PIXELS = 32_000_000


# Colour modes we can turn into pixels. 8 (duotone) is stored as greyscale
# with the ink curves alongside, so it decodes as one. Bitmap (0), Lab (9)
# and multichannel (7) fall through to the thumbnail.
PSD_MODES = {1: "gray", 2: "indexed", 3: "rgb", 4: "cmyk", 8: "gray"}


PSD_MODE_CHANNELS = {"gray": 1, "indexed": 1, "rgb": 3, "cmyk": 4}


class _PsdError(Exception):
    """A malformed or unsupported file. Never escapes _decode_native."""


class _DeviceFile:
    """A read-only Python file object over a QIODevice.

    The worker holds the file as a QFile on the fd the daemon passed, and
    neither zipfile nor the PSD reader below can take one of those. This is
    the adapter, and the reason it exists rather than a read() into a
    BytesIO: a .kra can be half a gigabyte, and only a few hundred KiB of it
    is the preview.
    """

    def __init__(self, dev):
        if not dev.seek(0):
            raise _PsdError("stream is not seekable")
        self._dev = dev

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return bytes(self._dev.readAll())
        return bytes(self._dev.read(n))

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 1:
            pos += int(self._dev.pos())
        elif whence == 2:
            pos += int(self._dev.size())
        self._dev.seek(pos)
        return int(self._dev.pos())

    def tell(self) -> int:
        return int(self._dev.pos())

    def seekable(self) -> bool:
        return True

    def close(self):
        """A no-op: the fd belongs to the caller, not to this wrapper."""


def _stream(source):
    """A file object for either a path or the QIODevice the worker passes."""
    return open(source, "rb") if isinstance(source, str) else _DeviceFile(source)


class _PsdReader:
    """Big-endian reads over a stream, bounded by the real file size.

    Every offset in a PSD comes from a length field in the file itself, so
    each read is checked against the actual size before anything is
    allocated or skipped — a claimed 4 GiB section in a 12 KiB file has to
    fail here rather than after a bytearray of that size.
    """

    def __init__(self, source):
        self._fh = _stream(source)
        self.size = self._fh.seek(0, 2)
        self._fh.seek(0)
        self.pos = 0

    def close(self):
        self._fh.close()

    def seek(self, pos: int):
        if pos < 0 or pos > self.size:
            raise _PsdError(f"offset {pos} outside a {self.size}-byte file")
        self._fh.seek(pos)
        self.pos = pos

    def skip(self, n: int):
        self.seek(self.pos + n)

    def read(self, n: int) -> bytes:
        if n < 0 or self.pos + n > self.size:
            raise _PsdError("read past end of file")
        data = self._fh.read(n)
        if len(data) != n:
            raise _PsdError("short read")
        self.pos += n
        return data

    def uint(self, n: int) -> int:
        return int.from_bytes(self.read(n), "big")


def _psd_header(r) -> dict:
    """Parse the 26-byte file header, or raise."""
    if r.read(4) != b"8BPS":
        raise _PsdError("not a Photoshop file")
    version = r.uint(2)
    if version not in (1, 2):
        raise _PsdError(f"unknown version {version}")
    r.skip(6)  # reserved, must be zero — not worth rejecting a file over
    channels = r.uint(2)
    height = r.uint(4)
    width = r.uint(4)
    depth = r.uint(2)
    mode = r.uint(2)
    if not 1 <= channels <= PSD_MAX_CHANNELS:
        raise _PsdError(f"absurd channel count {channels}")
    if width < 1 or height < 1 or width * height > PSD_MAX_PIXELS:
        raise _PsdError(f"absurd canvas {width}x{height}")
    return {
        # PSB is the same format with the wide fields widened: the layer
        # section's length and the RLE row counts grow, nothing else does.
        "psb": version == 2,
        "channels": channels, "w": width, "h": height,
        "depth": depth, "mode": mode,
    }


def _psd_sections(r, hdr: dict) -> dict:
    """Walk to the image data, collecting what the later stages need.

    Returns the indexed-colour palette, the thumbnail resource and the
    offset of the merged image data. The layer and mask section is skipped
    by its length without being looked at — that is the whole point.
    """
    out = {"palette": b"", "thumb": None, "image": None}

    n = r.uint(4)                       # colour mode data
    if n and n <= 4096:
        # Indexed files keep their 768-byte palette here. Everything else
        # this section is used for (duotone ink curves) we do not need, and
        # a length past the cap is not a palette either way.
        out["palette"] = r.read(n)
    elif n:
        r.skip(n)

    n = r.uint(4)                       # image resources
    end = r.pos + n
    if end > r.size:
        raise _PsdError("image resource section runs past the file")
    for _ in range(PSD_MAX_RESOURCES):
        if r.pos + 12 > end:
            break
        if r.read(4) != b"8BIM":
            break
        res_id = r.uint(2)
        name_len = r.uint(1)
        # Pascal string, padded so the length byte plus the text is even.
        r.skip(name_len + (1 - (name_len & 1)))
        size = r.uint(4)
        if size < 0 or r.pos + size > end:
            break
        if (res_id in PSD_THUMB_IDS and out["thumb"] is None
                and 28 < size <= PSD_MAX_THUMB_BYTES):
            out["thumb"] = (res_id, r.read(size))
        else:
            r.skip(size)
        if size & 1:
            r.skip(1)                   # data is padded to an even length
    r.seek(end)

    n = r.uint(8 if hdr["psb"] else 4)  # layer and mask information
    if r.pos + n > r.size:
        raise _PsdError("layer section runs past the file")
    r.skip(n)
    out["image"] = r.pos
    return out


def _psd_thumbnail(thumb):
    """The embedded JPEG preview, decoded, or None."""
    from PySide6.QtGui import QImage

    res_id, data = thumb
    fmt = int.from_bytes(data[0:4], "big")
    if fmt != 1:                        # 0 is raw RGB, which Photoshop
        return None                     # does not actually write
    img = QImage.fromData(data[28:], "JPEG")
    if img.isNull():
        return None
    # 1033 predates Photoshop 5 and stores the JPEG as BGR.
    return img.rgbSwapped() if res_id == 1033 else img


def _unpack_bits(src: bytes, want: int) -> bytes:
    """PackBits, the run-length coding PSD scanlines use.

    This is the decoder's hot loop — most of a large file's decode time —
    so it is written for the interpreter rather than for the page, and the
    shape was chosen by measurement rather than by eye. Two obvious
    tightenings do not pay: preallocating the output and writing into it by
    slice measures ~70% *slower*, because the bounds arithmetic it then
    needs per opcode costs more than the amortised growth it saves, and a
    memoryview over the source is slower still. What does pay is collecting
    the pieces and joining them once (8-20% over extending a bytearray) and
    keeping the length check out of the loop.

    The worst case is not the biggest file but the busiest one: a scanline
    of dithered or high-frequency two-colour artwork codes as thousands of
    short opcodes rather than dozens of long ones, and costs ~25x a
    photographic row of the same width. Nothing here changes that — it is
    the per-opcode interpreter overhead, and the way out would be a C
    extension this project does not want.
    """
    # With the length check out of the loop the bound has to be restored
    # here, once per scanline. The tight bound is tempting — Photoshop codes
    # `want` bytes in `want` plus one control byte per 128 — but PackBits
    # does not require an encoder to be good at it, and one that emits a
    # literal opcode per byte is suboptimal rather than malformed. Allowing
    # twice the row still caps what the loop can produce at 128x one
    # scanline, a few hundred KiB held for as long as it takes to trim.
    if len(src) > 2 * want + 16:
        raise _PsdError("scanline longer than its own row")
    parts = []
    add = parts.append                  # hoisted: this runs per opcode
    i, n = 0, len(src)
    while i < n:
        b = src[i]
        i += 1
        if b < 128:
            add(src[i:i + b + 1])
            i += b + 1
        elif b > 128:
            add(src[i:i + 1] * (257 - b))
            i += 1
        # 128 is a no-op byte, by the format's definition.
    row = b"".join(parts)
    if len(row) < want:
        raise _PsdError("truncated scanline")
    return row[:want]


def _psd_planes(r, hdr: dict, offset: int, want: int, step: int) -> list:
    """Decode `want` channel planes, keeping every `step`-th row and column.

    The decimation is the reason this is fast. RLE-compressed image data is
    preceded by a table of every scanline's compressed length, so a row can
    be *seeked past* instead of decoded; raw data is a flat grid and indexes
    directly. Either way the cost tracks the size of the preview rather than
    the size of the document, which is the same bargain decode_image already
    strikes with libjpeg's DCT scaling — a 6000x4000 canvas shown in a
    1600 px box decodes about a third of its rows and a third of each one.
    """
    w, h, depth = hdr["w"], hdr["h"], hdr["depth"]
    sample = depth // 8                 # bytes per sample; depth is 8 or 16
    row_bytes = w * sample
    r.seek(offset)
    compression = r.uint(2)

    counts = None
    if compression == 1:
        # h counts per channel, for every channel in the file — including
        # the ones past `want`, which still have to be measured to find
        # where the wanted ones start.
        width_of_count = 4 if hdr["psb"] else 2
        total = hdr["channels"] * h
        raw = r.read(total * width_of_count)
        counts = [
            int.from_bytes(raw[i:i + width_of_count], "big")
            for i in range(0, len(raw), width_of_count)
        ]
    elif compression != 0:
        # 2 and 3 are zlib, which Photoshop writes for layer data but not
        # for the composite. The thumbnail covers the case if it ever does.
        raise _PsdError(f"unsupported compression {compression}")

    base = r.pos
    planes = []
    for ch in range(want):
        plane = bytearray()
        if counts is None:
            start = base + ch * h * row_bytes
            if start + h * row_bytes > r.size:
                raise _PsdError("image data runs past the file")
            for y in range(0, h, step):
                plane += _psd_sample(r, start + y * row_bytes, row_bytes,
                                     sample, step)
        else:
            # Accumulate the row lengths rather than materialising them as a
            # table of offsets: a one-pixel-wide canvas may legally declare
            # tens of millions of rows, and a list that long costs more than
            # the image it indexes. Walking them in order costs nothing —
            # the rows are wanted in order too.
            here = base + sum(counts[:ch * h])
            if here + sum(counts[ch * h:(ch + 1) * h]) > r.size:
                raise _PsdError("scanline table runs past the file")
            for y in range(h):
                length = counts[ch * h + y]
                if y % step == 0:
                    r.seek(here)
                    row = _unpack_bits(r.read(length), row_bytes)
                    plane += _psd_decimate(row, sample, step)
                here += length
        planes.append(plane)
    return planes


def _psd_sample(r, at: int, row_bytes: int, sample: int, step: int) -> bytes:
    r.seek(at)
    return _psd_decimate(r.read(row_bytes), sample, step)


def _psd_decimate(row: bytes, sample: int, step: int) -> bytes:
    """One scanline down to one byte per kept pixel.

    16-bit samples are big-endian, so their high byte is the first of each
    pair and dropping the second is the whole conversion to 8-bit. Both
    steps are strided slices, which run in C — a per-pixel loop here would
    cost more than the decompression it follows.
    """
    if sample == 2:
        row = row[0::2]
    return row[::step] if step > 1 else row


def _psd_image(planes: list, ow: int, oh: int, kind: str, alpha, palette: bytes):
    """Interleave decoded channel planes into a QImage."""
    from PySide6.QtGui import QImage

    npx = ow * oh
    for plane in planes:
        if len(plane) != npx:
            raise _PsdError("channel plane is the wrong size")

    if kind == "indexed":
        if len(palette) < 768:
            raise _PsdError("indexed file with no palette")
        # translate() maps all 256 values in one C pass, which is exactly
        # what a palette lookup is.
        red = planes[0].translate(palette[0:256])
        green = planes[0].translate(palette[256:512])
        blue = planes[0].translate(palette[512:768])
    elif kind == "gray":
        red = green = blue = planes[0]
    else:                               # rgb, and cmyk's C/M/Y
        red, green, blue = planes[0], planes[1], planes[2]

    buf = bytearray(npx * 4)
    # Format_ARGB32 is BGRA in memory on a little-endian machine, and Qt
    # supports no big-endian desktop target. Strided assignment writes each
    # channel in one pass.
    buf[0::4] = blue
    buf[1::4] = green
    buf[2::4] = red
    buf[3::4] = alpha if alpha is not None else b"\xff" * npx
    img = QImage(bytes(buf), ow, oh, ow * 4,
                 QImage.Format.Format_ARGB32).copy()
    if img.isNull():
        raise _PsdError("could not build an image")

    if kind == "cmyk":
        # PSD stores CMYK inverted, so a stored byte is already the amount
        # of light the ink lets through: R = C x K / 255, and so on. That is
        # a multiply blend, which Qt does per pixel in C++ — a Python loop
        # over a few million pixels would cost more than the whole decode.
        from PySide6.QtGui import QPainter

        black = bytearray(npx * 4)
        black[0::4] = planes[3]
        black[1::4] = planes[3]
        black[2::4] = planes[3]
        black[3::4] = b"\xff" * npx
        painter = QPainter(img)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.drawImage(0, 0, QImage(bytes(black), ow, oh, ow * 4,
                                       QImage.Format.Format_ARGB32).copy())
        painter.end()
    return img


def _psd_composite(r, hdr: dict, sections: dict, max_w: int, max_h: int):
    """The flattened merged image, decimated to roughly the box asked for."""
    kind = PSD_MODES.get(hdr["mode"])
    if kind is None:
        raise _PsdError(f"colour mode {hdr['mode']} not supported")
    if hdr["depth"] not in (8, 16):
        # 1-bit bitmaps are packed rather than sampled, and 32-bit files are
        # floating point; neither survives the strided slice above.
        raise _PsdError(f"{hdr['depth']}-bit files not supported")

    need = PSD_MODE_CHANNELS[kind]
    if hdr["channels"] < need:
        raise _PsdError("fewer channels than the colour mode needs")
    # An extra channel on an RGB or greyscale document is transparency,
    # which is worth showing. On CMYK it is more likely a spot colour, and
    # reading a spot plate as alpha would punch holes in the preview.
    want = need + 1 if (hdr["channels"] > need and kind in ("gray", "rgb")) else need

    w, h = hdr["w"], hdr["h"]
    # Decimate by a whole number of pixels — strided slicing is what makes
    # the row cheap — and stop one step short of the target so the smooth
    # scale in decode_image still has pixels to work with. Landing exactly
    # on the box with an integer stride is only possible by accident.
    step = max(1, int(min(w / max(max_w, 1), h / max(max_h, 1))))
    ow, oh = -(-w // step), -(-h // step)
    if ow * oh > PSD_MAX_PREVIEW_PIXELS:
        raise _PsdError(f"{ow}x{oh} is too much preview to build")

    planes = _psd_planes(r, hdr, sections["image"], want, step)
    alpha = planes[need] if want > need else None
    return _psd_image(planes, ow, oh, kind, alpha, sections["palette"])


def _decode_psd(source, max_w: int, max_h: int) -> tuple:
    """(QImage, "W×H") for a Photoshop file, or (None, "").

    The composite is tried first and the embedded thumbnail is the fallback
    — a file saved without "Maximize Compatibility" has no composite at all,
    and a thumbnail at 256 px beats the "unsupported or corrupt" message it
    would otherwise get. Either way the reported dimensions come from the
    header, so the titlebar shows the document's real size and not the
    preview's.
    """
    r = None
    try:
        r = _PsdReader(source)
        hdr = _psd_header(r)
        orig = f"{hdr['w']}×{hdr['h']}"
        sections = _psd_sections(r, hdr)

        img = None
        try:
            img = _psd_composite(r, hdr, sections, max_w, max_h)
        except _PsdError:
            pass
        if img is None and sections["thumb"] is not None:
            img = _psd_thumbnail(sections["thumb"])
        return (img, orig) if img is not None else (None, "")
    except (_PsdError, OSError, ValueError):
        return None, ""
    finally:
        if r is not None:
            r.close()


# --- Krita and OpenRaster --------------------------------------------------

# Both are a zip holding the flattened composite as an ordinary PNG. Krita
# writes mergedimage.png precisely so that a thumbnailer never has to learn
# what a layer is, and OpenRaster's specification requires the same member —
# so one reader covers .kra and .ora, and "decoding" either is reading one
# zip entry.
KRA_MEMBERS = ("mergedimage.png", "preview.png")


# The composite is a PNG, and a PNG's declared size is not what it costs to
# decompress. This bounds the member before it is read, and again after, so
# a lying zip header buys nothing.
KRA_MAX_MERGED_BYTES = 96 * 1024 * 1024


def _decode_kra(source, max_w: int, max_h: int) -> tuple:
    """(QImage, "W×H") for a Krita or OpenRaster file, or (None, "").

    The merged image is preferred and preview.png is the fallback, which is
    what a file saved with the composite turned off leaves behind. Handing
    the member back to decode_image is deliberate: it is a plain PNG, and
    everything that path already does — the scaled read, the orientation,
    the dimensions — should happen to it too.
    """
    import zipfile
    from PySide6.QtCore import QBuffer, QIODevice

    fh = None
    try:
        fh = _stream(source)
        with zipfile.ZipFile(fh) as zf:
            names = set(zf.namelist())
            for member in KRA_MEMBERS:
                if member not in names:
                    continue
                if zf.getinfo(member).file_size > KRA_MAX_MERGED_BYTES:
                    continue
                with zf.open(member) as entry:
                    data = entry.read(KRA_MAX_MERGED_BYTES + 1)
                if len(data) > KRA_MAX_MERGED_BYTES:
                    continue        # the header understated it; do not decode
                # setData copies into the buffer's own storage. The
                # QBuffer(QByteArray) overload keeps a *reference* to the
                # array instead, and a temporary passed there is freed while
                # the buffer still points at it — which crashes the worker
                # on the second member rather than on the first.
                buf = QBuffer()
                buf.setData(data)
                buf.open(QIODevice.OpenModeFlag.ReadOnly)
                try:
                    return decode_image(buf, max_w, max_h)
                except RuntimeError:
                    continue        # try preview.png before giving up
    except (zipfile.BadZipFile, _PsdError, OSError, ValueError, EOFError):
        pass
    finally:
        if fh is not None:
            fh.close()
    return None, ""


def _decode_native(source, max_w: int, max_h: int) -> tuple:
    """Formats Qt has no handler for but which carry their own composite.

    Both checks are a header read on a file Qt has already refused, so the
    cost of asking is a few bytes and the cost of being wrong is nothing.
    """
    img, orig = _decode_psd(source, max_w, max_h)
    if img is None:
        img, orig = _decode_kra(source, max_w, max_h)
    return img, orig


def render_anim(source, max_w: int, max_h: int, max_frames: int, max_bytes: int):
    """Yield (frame_count, delay_ms, png_bytes) for an animation.

    Decoding every frame here is what lets the daemon animate a GIF without
    ever running QMovie — it just cycles pixmaps on a timer. Stops early at
    max_frames or once max_bytes of decoded RGB has been produced, so a
    header claiming 100k frames costs bounded memory; the caller falls back
    to a still image when nothing decodes.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMovie

    movie = QMovie(source)
    if not movie.isValid():
        raise RuntimeError("not a valid animation")
    movie.setCacheMode(QMovie.CacheMode.CacheNone)
    # frameCount() is 0 for formats that don't declare one; treat that as
    # "stream until jumpToNextFrame fails".
    declared = movie.frameCount()
    count = min(declared, max_frames) if declared > 0 else max_frames

    movie.jumpToFrame(0)
    spent = 0
    for i in range(count):
        img = movie.currentImage()
        if img.isNull():
            break
        delay = max(movie.nextFrameDelay(), 10)
        if img.width() > max_w or img.height() > max_h:
            img = img.scaled(
                max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        if i == 0:
            img.setText("QuickView:OrigSize", f"{img.width()}×{img.height()}")
        spent += img.width() * img.height() * 4
        yield count, delay, _encode(img)
        if spent >= max_bytes or not movie.jumpToNextFrame():
            break
