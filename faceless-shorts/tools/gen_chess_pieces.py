#!/usr/bin/env python3
"""
gen_chess_pieces.py — draw the 12 chess piece SVGs into media/library/chess/.

remotion/src/lib/chess.tsx renders pieces as staticFile(`library/chess/<code>.svg`)
with codes w/b x KQRBNP. Those files are not in the repo, so Short1Chess renders a
board of broken images. This draws them instead of vendoring a set: no download, no
third-party licence riding along with the MIT repo.

Style: flat silhouettes on a 45x45 viewBox (the standard chess-SVG canvas), sized to
read at phone scale — the board is ~940px wide in a 1080x1920 frame, so a piece lands
around 110px. Black pieces carry a light contour so they separate from the dark
squares (#B58863) as cleanly as white ones do.

    python3 tools/gen_chess_pieces.py            # write media/library/chess/*.svg
    python3 tools/gen_chess_pieces.py --force    # overwrite existing files

Run from the repo root.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "media" / "library" / "chess"

# White reads as warm paper, black as the brand ink — both against the CLASSIC board
# theme in chess.tsx (light #F0D9B5 / dark #B58863).
THEMES = {
    "w": {"fill": "#FBFAF4", "stroke": "#1A1A2E", "detail": "#1A1A2E", "sw": 1.5},
    "b": {"fill": "#1F1D2B", "stroke": "#F2EFE6", "detail": "#F2EFE6", "sw": 1.3},
}

# Every piece stands on the same plinth + footer, so they sit on a common baseline.
BASE = (
    '<path d="M12.4 32.6h20.2l2.9 4.4H9.5z"/>'
    '<rect x="8.6" y="36.6" width="27.8" height="3.8" rx="1.3"/>'
)

# Collar between body and plinth — used by the tall pieces.
COLLAR = '<rect x="12.6" y="28.8" width="19.8" height="4.2" rx="2.1"/>'

PIECES = {
    "P": {  # pawn — head, shoulders, cone
        "name": "pawn",
        "body": (
            '<circle cx="22.5" cy="13.2" r="4.9"/>'
            '<path d="M18.2 18.3c-1.6 1.2-2.6 2.9-2.6 4.8 0 2.2 1.2 3.7 2.5 4.8'
            '-2.4 1.7-4 3.6-4.7 6.1h18.2c-.7-2.5-2.3-4.4-4.7-6.1 1.3-1.1 2.5-2.6 2.5-4.8'
            '0-1.9-1-3.6-2.6-4.8z"/>'
        ),
    },
    "R": {  # rook — three merlons, straight shaft
        "name": "rook",
        "body": (
            '<path d="M12.2 10.4h4.6v3.4h3.4v-3.4h4.6v3.4h3.4v-3.4h4.6v7.4'
            'L29.9 20.2v10.2l2.9 2.6H12.2l2.9-2.6V20.2z"/>'
        ),
    },
    "B": {  # bishop — mitre, finial, slit
        "name": "bishop",
        "body": (
            '<circle cx="22.5" cy="8.4" r="2.2"/>'
            '<path d="M22.5 11.4c4.7 0 8.5 5.5 8.5 10.8 0 3.4-1.9 6-4.2 7.6H18.2'
            'c-2.3-1.6-4.2-4.2-4.2-7.6 0-5.3 3.8-10.8 8.5-10.8z"/>'
        ),
        "detail": '<path d="M22.5 15.6v8.4M18.7 19.8h7.6"/>',
    },
    "N": {  # knight — head in profile, muzzle left, ear top-right
        "name": "knight",
        "body": (
            '<path d="M28.6 7.2 30.2 12.4C33.4 16.8 34.6 23 34.6 31.8V33.2H12.6V31.8'
            'C12.6 28 13.4 25 15 22.4L13.2 21.2C11.6 22.6 9.6 23.4 8.8 22.2'
            'C8 21 9 19.2 10.8 18L16.4 14.6C18.6 12 21 9.6 24 8.2'
            'C25.6 7.4 27.2 6.6 28.6 7.2Z"/>'
        ),
        "detail": '<path d="M15.9 18.6a1.25 1.25 0 1 0 .02 0zM19.6 13.2 24.4 17"/>',
    },
    "Q": {  # queen — five finials over a spiked crown
        "name": "queen",
        "body": (
            '<circle cx="10.4" cy="13.6" r="2.1"/><circle cx="16.4" cy="10.4" r="2.1"/>'
            '<circle cx="22.5" cy="8.9" r="2.3"/><circle cx="28.6" cy="10.4" r="2.1"/>'
            '<circle cx="34.6" cy="13.6" r="2.1"/>'
            '<path d="M10.4 16.1 14 29.2h17l3.6-13.1-5.4 6.6-3.2-10.4-3.5 10.9'
            '-3.5-10.9-3.2 10.4z"/>'
        ),
    },
    "K": {  # king — cross over a flared crown
        "name": "king",
        "body": (
            '<path d="M21.2 4.6h2.6v3.3h3.3v2.6h-3.3v3.3h-2.6v-3.3h-3.3V7.9h3.3z"/>'
            '<path d="M22.5 14.4c-2.7 2.3-6.5 3.7-9.1 2.4-2.3-1.1-3.5.9-3.5 3.1'
            '0 4.3 3.5 7.7 5.7 10.5h13.8c2.2-2.8 5.7-6.2 5.7-10.5 0-2.2-1.2-4.2-3.5-3.1'
            '-2.6 1.3-6.4-.1-9.1-2.4z"/>'
        ),
    },
}

# The tall pieces get the collar; pawn and rook flow straight into the plinth.
WITH_COLLAR = {"B", "N", "Q", "K"}


def svg_for(color: str, code: str) -> str:
    t = THEMES[color]
    piece = PIECES[code]
    parts = [piece["body"]]
    if code in WITH_COLLAR:
        parts.append(COLLAR)
    parts.append(BASE)
    shapes = "".join(parts)

    detail = ""
    if piece.get("detail"):
        detail = (
            f'<g fill="none" stroke="{t["detail"]}" stroke-width="{t["sw"]}" '
            f'stroke-linecap="round">{piece["detail"]}</g>'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 45 45" width="45" height="45">'
        f'<title>{color}{code} {piece["name"]}</title>'
        f'<g fill="{t["fill"]}" stroke="{t["stroke"]}" stroke-width="{t["sw"]}" '
        'stroke-linejoin="round" stroke-linecap="round">'
        f"{shapes}</g>{detail}</svg>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing SVGs")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    for color in ("w", "b"):
        for code in ("K", "Q", "R", "B", "N", "P"):
            name = f"{color}{code}.svg"
            path = OUT_DIR / name
            if path.exists() and not args.force:
                skipped.append(name)
                continue
            path.write_text(svg_for(color, code), encoding="utf-8")
            written.append(name)

    catalog = {
        "note": (
            "Chess piece sprites for remotion/src/lib/chess.tsx, which loads them as "
            "staticFile('library/chess/<code>.svg'). Drawn by tools/gen_chess_pieces.py "
            "— re-run it to restyle the set. Flat silhouettes on a 45x45 viewBox, tuned "
            "for the CLASSIC board theme (light #F0D9B5 / dark #B58863) at phone scale."
        ),
        "license": "Drawn for this repo by tools/gen_chess_pieces.py; MIT, same as the repo.",
        "pieces": [
            {
                "id": f"{c}{k}",
                "file": f"{c}{k}.svg",
                "color": "white" if c == "w" else "black",
                "piece": PIECES[k]["name"],
            }
            for c in ("w", "b")
            for k in ("K", "Q", "R", "B", "N", "P")
        ],
    }
    (OUT_DIR / "catalog.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    rel = OUT_DIR.relative_to(ROOT)
    print(f"wrote {len(written)} piece(s) -> {rel}/")
    if skipped:
        print(f"  skipped {len(skipped)} existing (use --force): {', '.join(skipped)}")
    print(f"catalog -> {rel}/catalog.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
