#!/usr/bin/env python3
"""Colour system of the book (v11).

Turns palette definitions (templates/palettes.json plus an optional
ui.custom_palette in book.config.json) into CSS custom properties. Every colour
is derived in OKLCH and the lightness of each text/solid colour is *solved* so
that the text/background pairs the stylesheet uses meet WCAG 2 AA (4.5:1 for
text, 3:1 for control borders) in both themes — contrast holds by construction,
and verify() re-checks every pair mechanically.

A palette is seven "pens" (slots c1..c7). Per pen and theme the stylesheet gets:
  --cN        ink: text-safe on --bg/--bg2/--bg3 and on its own wash/highlight
  --cN-wash   soft background          --cN-hl    highlighter band
  --cN-line   border / decoration      --cN-solid solid fill, with --cN-on text

Usage (project = current directory, or --root <dir>; works outside a project too):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/make_palette.py" --list    # palettes available to this project
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/make_palette.py" --check   # verify every pair; exit 1 on any failure
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/make_palette.py" --css     # print the theme.css build_book.py writes
"""
import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib  # noqa: E402

SLOTS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]
ALIASES = {"primary": "c1", "warn": "c2", "example": "c3", "formula": "c4",
           "summary": "c5", "note": "c6", "recall": "c7"}
# chapter tab k (1..7) -> pen; neighbouring chapters get clearly different hues
TAB_ORDER = ["c1", "c3", "c5", "c4", "c6", "c7", "c2"]
INK_HUE = 262
# paper -> (light surface chroma, light hue, dark surface chroma, dark hue)
PAPERS = {"neutral": (0.0, INK_HUE, 0.020, INK_HUE), "warm": (0.007, 80, 0.012, 60),
          "cool": (0.006, 245, 0.024, 245)}
HEX_RE = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
TEXT_MIN, UI_MIN = 4.5, 3.0


# ---------------------------------------------------------------- colour maths
def _lin_to_srgb(x):
    return 12.92 * x if x <= 0.0031308 else 1.055 * (x ** (1 / 2.4)) - 0.055


def _srgb_to_lin(x):
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def _oklch_to_linear(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _in_gamut(rgb, eps=1e-4):
    return all(-eps <= c <= 1 + eps for c in rgb)


def oklch_hex(L, C, h):
    """sRGB hex of an OKLCH colour; chroma is reduced until the colour fits the gamut."""
    rgb = _oklch_to_linear(L, C, h)
    if not _in_gamut(rgb):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_linear(L, mid, h)):
                lo = mid
            else:
                hi = mid
        rgb = _oklch_to_linear(L, lo, h)
    return "#" + "".join(f"{round(_lin_to_srgb(min(1.0, max(0.0, c))) * 255):02x}" for c in rgb)


def hex_to_rgb(hx):
    hx = hx.lstrip("#")
    if len(hx) == 3:
        hx = "".join(ch * 2 for ch in hx)
    return tuple(int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hex_to_oklch(hx):
    r, g, b = (_srgb_to_lin(c) for c in hex_to_rgb(hx))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360


def luminance(hx):
    r, g, b = (_srgb_to_lin(c) for c in hex_to_rgb(hx))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _solve(h, C, against, target, start, stop, step):
    """First lightness walking from start to stop whose colour reaches `target`
    contrast against every colour in `against` (falls back to stop; verify() reports it)."""
    n = int(round(abs(stop - start) / abs(step)))
    for i in range(n + 1):
        hx = oklch_hex(start + i * step, C, h)
        if all(contrast(hx, bg) >= target for bg in against):
            return hx
    return oklch_hex(stop, C, h)


# ---------------------------------------------------------------- token generation
def _deep_hue(h):
    """Yellows turn olive when darkened enough to carry text on a light page; the dark
    tones (ink, solid) of a yellow pen lean toward amber instead. Washes keep the true hue."""
    return h - (h - 60) * 0.55 if 75 <= h <= 115 else h


def build_theme(defn, dark):
    hues, m = defn["hues"], defn["chroma"]
    pc, ph, dc, dh = PAPERS[defn["paper"]]
    t = {}
    if not dark:
        t["bg"] = oklch_hex(0.992 if pc else 1.0, pc, ph)
        t["bg2"] = oklch_hex(0.968, 0.005 + pc, ph)
        t["bg3"] = oklch_hex(0.943, 0.008 + pc, ph)
        t["line"] = oklch_hex(0.895, 0.010 + pc * 0.5, ph)
        t["fg"] = oklch_hex(0.245, 0.030, INK_HUE)
    else:
        t["bg"] = oklch_hex(0.205, dc, dh)
        t["bg2"] = oklch_hex(0.172, dc * 0.9, dh)
        t["bg3"] = oklch_hex(0.262, dc * 1.1, dh)
        t["line"] = oklch_hex(0.315, dc * 1.1, dh)
        t["fg"] = oklch_hex(0.930, 0.012, dh)
    surfaces = [t["bg"], t["bg2"], t["bg3"]]
    for s in SLOTS:
        h = hues[s]
        if not dark:
            t[s + "-wash"] = oklch_hex(0.962, 0.030 * m, h)
            t[s + "-hl"] = oklch_hex(0.905, 0.080 * m, h)
            t[s + "-line"] = oklch_hex(0.850, 0.075 * m, h)
            t[s + "-on"] = "#ffffff"
            hd = _deep_hue(h)
            t[s + "-solid"] = _solve(hd, 0.155 * m, [t[s + "-on"]], 4.6, 0.62, 0.30, -0.01)
            t[s] = _solve(hd, 0.140 * m, surfaces + [t[s + "-wash"], t[s + "-hl"]], 4.6, 0.58, 0.22, -0.01)
        else:
            t[s + "-wash"] = oklch_hex(0.268, 0.040 * m, h)
            t[s + "-hl"] = oklch_hex(0.350, 0.072 * m, h)
            t[s + "-line"] = oklch_hex(0.430, 0.075 * m, h)
            t[s + "-on"] = oklch_hex(0.160, 0.020, INK_HUE)
            t[s + "-solid"] = _solve(h, 0.130 * m, [t[s + "-on"]], 4.6, 0.72, 0.95, 0.01)
            t[s] = _solve(h, 0.125 * m, surfaces + [t[s + "-wash"], t[s + "-hl"]], 4.6, 0.74, 0.97, 0.01)
    washes = [t[s + "-wash"] for s in SLOTS]
    if not dark:
        t["muted"] = _solve(INK_HUE, 0.028, surfaces + washes, 4.6, 0.56, 0.25, -0.01)
        t["line2"] = _solve(INK_HUE, 0.020, [t["bg"], t["bg2"]], 3.05, 0.72, 0.30, -0.01)
    else:
        t["muted"] = _solve(dh, 0.022, surfaces + washes, 4.6, 0.66, 0.95, 0.01)
        t["line2"] = _solve(dh, 0.022, [t["bg"], t["bg2"]], 3.05, 0.44, 0.90, 0.01)
    return t


def generate(defn):
    return {"light": build_theme(defn, False), "dark": build_theme(defn, True)}


def verify(t):
    """Every text/background and control/background pair the stylesheet uses, for one theme."""
    fails = []

    def need(fg, bg, minimum):
        r = contrast(t[fg], t[bg])
        if r < minimum:
            fails.append({"fg": "--" + fg, "bg": "--" + bg, "ratio": round(r, 2), "min": minimum})

    for bg in ("bg", "bg2", "bg3"):
        need("fg", bg, TEXT_MIN)
        need("muted", bg, TEXT_MIN)
    for s in SLOTS:
        for bg in ("bg", "bg2", "bg3", s + "-wash", s + "-hl"):
            need(s, bg, TEXT_MIN)
        need("fg", s + "-wash", TEXT_MIN)
        need("fg", s + "-hl", TEXT_MIN)
        need("muted", s + "-wash", TEXT_MIN)
        need(s + "-on", s + "-solid", TEXT_MIN)
        need(s + "-solid", "bg", UI_MIN)
        need(s + "-solid", "bg2", UI_MIN)
    need("line2", "bg", UI_MIN)
    need("line2", "bg2", UI_MIN)
    return fails


# ---------------------------------------------------------------- definitions
def load_definitions(templates_dir):
    with open(os.path.join(templates_dir, "palettes.json"), "r", encoding="utf-8") as f:
        defs = json.load(f)
    if not isinstance(defs, dict) or not isinstance(defs.get("palettes"), dict) or not defs["palettes"]:
        raise ValueError("palettes.json has no palettes")
    return defs


def to_hue(v):
    """A hue angle (number) or a hex colour whose OKLCH hue is taken."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) % 360
    if isinstance(v, str) and HEX_RE.fullmatch(v.strip()):
        return round(hex_to_oklch(v.strip())[2], 1)
    return None


def _normalise(d, name):
    hues = {}
    for s in SLOTS:
        h = to_hue((d.get("hues") or {}).get(s))
        if h is None:
            raise ValueError(f"palette {name!r}: missing or invalid hue for {s}")
        hues[s] = h
    paper = d.get("paper", "neutral")
    if paper not in PAPERS:
        raise ValueError(f"palette {name!r}: paper must be one of {', '.join(PAPERS)}")
    chroma = min(1.6, max(0.5, float(d.get("chroma", 1.0))))
    return {"label": d.get("label") or name, "paper": paper, "chroma": chroma, "hues": hues}


def resolve_palettes(defs, ui):
    """({name: definition}, default_name, warnings) — built-ins plus the project's
    ui.custom_palette (as "custom"). ui is the effective config's "ui" block."""
    warnings, out = [], {}
    for name, d in defs["palettes"].items():
        if not kitlib.PALETTE_NAME_RE.fullmatch(name) or name == "custom":
            raise ValueError(f"palettes.json: bad palette name {name!r}")
        out[name] = _normalise(d, name)
    builtin_default = defs.get("default") if defs.get("default") in out else next(iter(out))
    custom = (ui or {}).get("custom_palette")
    if isinstance(custom, dict):
        base = out.get(custom.get("base")) or out[builtin_default]
        d = {"label": custom.get("label") or {"th": "กำหนดเอง", "en": "Custom"},
             "paper": base["paper"], "chroma": base["chroma"], "hues": dict(base["hues"])}
        if custom.get("base") is not None and custom.get("base") not in out:
            warnings.append({"code": "config.palette",
                             "detail": f"ui.custom_palette.base {custom.get('base')!r} is not a built-in palette — "
                                       f"starting from {builtin_default!r}"})
        if "paper" in custom:
            if custom["paper"] in PAPERS:
                d["paper"] = custom["paper"]
            else:
                warnings.append({"code": "config.palette",
                                 "detail": f"ui.custom_palette.paper must be one of {', '.join(PAPERS)} — kept {d['paper']!r}"})
        if "chroma" in custom:
            try:
                d["chroma"] = min(1.6, max(0.5, float(custom["chroma"])))
            except (TypeError, ValueError):
                warnings.append({"code": "config.palette", "detail": "ui.custom_palette.chroma must be a number 0.5..1.6 — ignored"})
        hues = custom.get("hues") if isinstance(custom.get("hues"), dict) else {}
        for k, v in hues.items():
            slot, hue = ALIASES.get(k, k), to_hue(v)
            if slot not in SLOTS or hue is None:
                warnings.append({"code": "config.palette",
                                 "detail": f"ui.custom_palette.hues.{k}={v!r} ignored — keys are c1..c7 or "
                                           f"{', '.join(ALIASES)}; values are a hue angle or a hex colour"})
                continue
            d["hues"][slot] = hue
        out["custom"] = d
    want = (ui or {}).get("palette")
    if want and want not in out:
        warnings.append({"code": "config.palette",
                         "detail": f"ui.palette {want!r} is not available ({', '.join(out)}) — using {builtin_default!r}"})
        want = None
    return out, (want or builtin_default), warnings


def label_for(defn, lang, name=""):
    lab = defn.get("label")
    if isinstance(lab, dict):
        return str(lab.get(lang) or lab.get("en") or next(iter(lab.values()), name))
    return str(lab or name)


# ---------------------------------------------------------------- CSS
def _decls(t):
    order = ["bg", "bg2", "bg3", "fg", "muted", "line", "line2"]
    for s in SLOTS:
        order += [s, s + "-wash", s + "-hl", s + "-line", s + "-solid", s + "-on"]
    return "".join(f"--{k}:{t[k]};" for k in order)


def theme_css(generated, default):
    """generated: {name: {"light": tokens, "dark": tokens}}. Every block is complete, so
    the palette+theme block (highest specificity) never inherits a stray light/dark value."""
    out = ["/* Generated by book-kit make_palette.py — do not edit. Colours come from ui.palette /",
           "   ui.custom_palette in book.config.json; every text/background pair is AA-checked. */",
           ":root{" + _decls(generated[default]["light"]) + "}",
           'html[data-theme="dark"]{' + _decls(generated[default]["dark"]) + "}"]
    for name, g in generated.items():
        out.append(f'html[data-palette="{name}"]{{' + _decls(g["light"]) + "}")
        out.append(f'html[data-palette="{name}"][data-theme="dark"]{{' + _decls(g["dark"]) + "}")
    # Without JavaScript nothing sets data-theme: follow the system theme for the default palette
    # (the only one reachable then). With JavaScript the attribute is set before first paint.
    out.append("@media (prefers-color-scheme: dark){"
               f'html:not([data-theme])[data-palette="{default}"]{{' + _decls(generated[default]["dark"]) + "}}")
    return "\n".join(out) + "\n"


def project_palettes(root=None, templates=None):
    """(definitions, generated, default, warnings) for a project (or built-ins only outside one)."""
    root = kitlib.resolve_root(root)
    raw, _ = kitlib.load_config(root)
    cfg, _ = kitlib.effective_config(raw)
    defs = load_definitions(kitlib.resolve_templates(root, templates))
    pals, default, warnings = resolve_palettes(defs, cfg["ui"])
    return pals, {n: generate(d) for n, d in pals.items()}, default, warnings, cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="palettes available to this project")
    g.add_argument("--check", action="store_true", help="verify WCAG AA for every palette and theme")
    g.add_argument("--css", action="store_true", help="print the generated theme.css")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    ap.add_argument("--templates", help="templates dir (default: <root>/templates if present, else the plugin's)")
    args = ap.parse_args()
    try:
        pals, gen, default, warnings, cfg = project_palettes(args.root, args.templates)
    except (OSError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    lang = cfg["book"]["language"]
    if args.css:
        sys.stdout.write(theme_css(gen, default))
        return 0
    if args.list:
        print(json.dumps({"default": default, "warnings": warnings, "palettes": [
            {"name": n, "label": label_for(d, lang, n), "paper": d["paper"], "chroma": d["chroma"],
             "hues": d["hues"], "primary": gen[n]["light"]["c1-solid"]} for n, d in pals.items()]},
            indent=2, ensure_ascii=False))
        return 0
    failures = []
    for n in gen:
        for theme in ("light", "dark"):
            for f in verify(gen[n][theme]):
                failures.append(dict(f, palette=n, theme=theme))
    print(json.dumps({"status": "PASS" if not failures else "FAIL", "default": default,
                      "palettes": list(gen), "pairsPerTheme": 7 * 11 + 8,
                      "failures": failures, "warnings": warnings}, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
