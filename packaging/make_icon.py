"""Generate multi-size Windows .ico matching the app's purple iPhone glyph."""
from pathlib import Path
from PIL import Image, ImageDraw


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int, int]:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
        255,
    )


def render_icon(out_path: Path):
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Diagonal purple-to-magenta gradient mask for the iPhone silhouette.
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = grad.load()
    c1 = (0x5E, 0x5C, 0xE6)
    c2 = (0xBF, 0x5A, 0xF2)
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2.0 * (size - 1))
            px[x, y] = _lerp_color(c1, c2, t)

    scale = size / 64.0
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    body = [int(16 * scale), int(3 * scale), int(48 * scale), int(61 * scale)]
    radius = int(9 * scale)
    md.rounded_rectangle(body, radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    # Dark bezel outline matching ui.app_icon
    draw.rounded_rectangle(body, radius=radius, outline=(28, 28, 30, 255), width=int(3 * scale))
    # Dynamic Island pill
    notch = [int(26 * scale), int(8 * scale), int(38 * scale), int(12 * scale)]
    draw.rounded_rectangle(notch, radius=int(2 * scale), fill=(28, 28, 30, 255))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        str(out_path),
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    render_icon(Path(__file__).resolve().parent / "iPhoneMirror.ico")
