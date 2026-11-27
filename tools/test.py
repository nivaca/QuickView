#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Corre a la vez las pruebas de QuickView: .venv/bin/python tools/test.py [-j N] [-v] [NOMBRE ...]

Cada archivo de pruebas (tests/test_*.py) corre en un proceso de unittest
propio, tantos a la vez como procesadores tenga el computador (-j lo
cambia), primero los más lentos; así la suite tarda más o menos lo que su
archivo más lento, y no la suma de todos. Cada proceso tiene su carpeta
personal, su carpeta temporal y su carpeta de ejecución (donde va el enchufe
del demonio), y QT_QPA_PLATFORM=offscreen, para que ninguna ventana salga en
la pantalla. Los paquetes de pip --user siguen visibles (PYTHONUSERBASE), aunque
la carpeta personal sea otra.

Los NOMBRE eligen qué correr: un archivo (test_zoom) o un patrón (test_*pdf*).
Al final aparecen los archivos que fallaron, con su salida, y los totales; -v
muestra además cada archivo a medida que termina. El código de salida es 1 si
falló alguna prueba. (python -m unittest discover -s tests -t . las corre una
tras otra, como antes.) Así las corre también packaging/release.py.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
# Los archivos que más tardan, que arrancan primero (los demás siguen en orden
# alfabético): medidos con -v el 2026-11-26
# (test_office.py, 12.5 s, es lo que tarda la suite entera)
SLOW = ("test_office.py", "test_zenodo.py", "test_reading_select.py", "test_settings_reload.py",
        "test_index_sheet.py", "test_hidpi.py", "test_zoom.py")


def files(names: list[str]) -> list[Path]:
    """The test files to run, the slowest first."""
    found = sorted(TESTS.glob("test_*.py"))
    if names:
        found = [p for p in found
                 if any(fnmatch.fnmatch(p.name, n) or fnmatch.fnmatch(p.stem, n) for n in names)]

    def rank(p: Path) -> int:
        return SLOW.index(p.name) if p.name in SLOW else len(SLOW)

    return sorted(found, key=rank)


def run(path: Path, work: Path, env: dict) -> tuple[Path, int, str, float]:
    """PATH run by unittest in a process of its own: (path, exit status, output, seconds)."""
    own = work / path.stem
    for sub in ("home", "tmp", "run"):
        (own / sub).mkdir(parents=True, exist_ok=True)
    (own / "run").chmod(0o700)
    env = {**env, "HOME": str(own / "home"), "TMPDIR": str(own / "tmp"),
           "XDG_RUNTIME_DIR": str(own / "run")}
    start = time.time()
    done = subprocess.run([sys.executable, "-m", "unittest", f"tests.{path.stem}"],
                          cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace")
    return path, done.returncode, done.stdout, time.time() - start


def counts(output: str) -> dict[str, int]:
    """{'ran': n, 'failures': n, 'errors': n, 'skipped': n} from unittest's
    summary ("Ran N tests", then "OK (skipped=k)" or "FAILED (failures=a, ...)")."""
    found: dict[str, int] = {}
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    if ran:
        found["ran"] = int(ran[-1])
    last = re.findall(r"^(?:OK|FAILED)(?: \((.*)\))?$", output, re.M)
    if last:
        for key, n in re.findall(r"(\w+)=(\d+)", last[-1]):
            found[key] = found.get(key, 0) + int(n)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tools/test.py",
                                     description="Run the tests of QuickView, each file in a process "
                                                 "of its own, at once.")
    parser.add_argument("names", nargs="*", metavar="NAME",
                        help="files or patterns to run (default: all)")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2,
                        help="how many at a time (default: the processors)")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each file as it ends")
    args = parser.parse_args(argv)
    todo = files(args.names)
    if not todo:
        print("tools/test.py: no tests match " + " ".join(args.names), file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="quickview-tests-"))
    # Sin pantalla, y con los paquetes de ~/.local (PySide6 puede venir de ahí)
    # aunque HOME cambie
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONUSERBASE": os.environ.get("PYTHONUSERBASE") or site.getuserbase()}
    start = time.time()
    failed: list[tuple[Path, str]] = []
    totals: dict[str, int] = {}
    try:
        with ThreadPoolExecutor(max(1, args.jobs)) as pool:
            jobs = [pool.submit(run, path, work, env) for path in todo]
            for n, job in enumerate(as_completed(jobs), 1):
                path, status, output, seconds = job.result()
                found = counts(output)
                for k, v in found.items():
                    totals[k] = totals.get(k, 0) + v
                # (5: unittest no encontró pruebas en el archivo; no es un fallo)
                if status not in (0, 5):
                    failed.append((path, output))
                if args.verbose or status not in (0, 5):
                    mark = "ok" if status in (0, 5) else "FAILED"
                    print(f"[{n}/{len(todo)}] {path.name}: {found.get('ran', 0)} ran, "
                          f"{seconds:.1f}s, {mark}", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for path, output in failed:
        print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}\n{output.rstrip()}")
    said = ", ".join(f"{v} {k}" for k, v in sorted(totals.items()))
    print(f"\n{said} ({len(todo)} files) in {time.time() - start:.1f}s: "
          + (f"FAILED ({len(failed)} files)" if failed else "OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
