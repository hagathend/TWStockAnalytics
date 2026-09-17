"""產生安裝版的程式圖示：跟介面左上角的品牌標誌（src/assets/brand.svg，上升葉片）同一個圖案。

用 Pillow 依 SVG 的座標直接畫（貝茲曲線取樣成多邊形），不需要 SVG 轉圖工具或字型，打包機器上一定畫得出來。
先用 4 倍解析度畫再縮小，邊緣才會平滑。改 brand.svg 的圖案時這裡要一起改。

用法：python packaging/make_icon.py 輸出路徑.ico [預覽.png]
"""

import sys

from PIL import Image, ImageChops, ImageDraw

VIEWBOX = 96
SIZE = 256
SCALE = 4  # 超取樣倍率
CANVAS = SIZE * SCALE
K = CANVAS / VIEWBOX


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha


def _pt(x: float, y: float) -> tuple[float, float]:
    return x * K, y * K


def _cubic(p0, p1, p2, p3, steps: int = 48) -> list[tuple[float, float]]:
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
        points.append(_pt(x, y))
    return points


def _gradient(start: str, end: str, box: tuple[float, float, float, float], diagonal: bool) -> Image.Image:
    """box 範圍內由 start 漸層到 end（水平或左上到右下），範圍外延伸端點色"""
    x0, y0, x1, y1 = box
    a, b = _hex(start), _hex(end)
    image = Image.new("RGBA", (CANVAS, CANVAS))
    pixels = image.load()
    span = (x1 - x0) + ((y1 - y0) if diagonal else 0)
    for y in range(0, CANVAS, 2):
        for x in range(0, CANVAS, 2):
            t = ((x - x0) + ((y - y0) if diagonal else 0)) / span
            t = min(max(t, 0.0), 1.0)
            color = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))
            for dx in (0, 1):
                for dy in (0, 1):
                    if x + dx < CANVAS and y + dy < CANVAS:
                        pixels[x + dx, y + dy] = color
    return image


def _fill(base: Image.Image, mask: Image.Image, paint):
    layer = paint if isinstance(paint, Image.Image) else Image.new("RGBA", (CANVAS, CANVAS), paint)
    base.paste(layer, (0, 0), ImageChops.multiply(mask, layer.getchannel("A")))


def draw_icon() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    # 圓角底：淡藍白對角漸層＋細邊框
    border = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(border).rounded_rectangle((*_pt(0.5, 0.5), *_pt(95.5, 95.5)), radius=23.5 * K, fill=255)
    _fill(image, border, _hex("#B7CBE1"))
    inner = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(inner).rounded_rectangle((*_pt(1.5, 1.5), *_pt(94.5, 94.5)), radius=22.5 * K, fill=255)
    _fill(image, inner, _gradient("#FDFEFF", "#DEE9F5", (*_pt(1, 1), *_pt(95, 95)), diagonal=True))

    # 三根上升的柱狀
    bars = Image.new("L", (CANVAS, CANVAS), 0)
    draw = ImageDraw.Draw(bars)
    for polygon in ([(19, 68), (19, 53), (31, 43), (31, 64)],
                    [(36, 60), (36, 38), (48, 28), (48, 51)],
                    [(53, 45), (53, 25), (65, 15), (65, 38)]):
        draw.polygon([_pt(x, y) for x, y in polygon], fill=255)
    _fill(image, bars, _hex("#2C5E9F"))

    # 葉片：M18 78 C46 78 77 65 76 33 C56 40 51 55 18 78 Z，水平漸層
    leaf_points = [_pt(18, 78)] + _cubic((18, 78), (46, 78), (77, 65), (76, 33)) + _cubic((76, 33), (56, 40), (51, 55), (18, 78))
    leaf = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(leaf).polygon(leaf_points, fill=255)
    _fill(image, leaf, _gradient("#245597", "#4C85CE", (*_pt(18, 33), *_pt(77, 78)), diagonal=False))

    # 葉脈：M23 76 C41 68 55 57 67 44，寬 2.5、圓頭
    vein = [_pt(23, 76)] + _cubic((23, 76), (41, 68), (55, 57), (67, 44))
    vein_mask = Image.new("L", (CANVAS, CANVAS), 0)
    vein_draw = ImageDraw.Draw(vein_mask)
    width = round(2.5 * K)
    vein_draw.line(vein, fill=255, width=width, joint="curve")
    for end in (vein[0], vein[-1]):
        vein_draw.ellipse((end[0] - width / 2, end[1] - width / 2, end[0] + width / 2, end[1] + width / 2), fill=255)
    _fill(image, vein_mask, _hex("#DCEAF8"))

    # 右上的圓點
    dot = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(dot).ellipse((*_pt(66.5, 10.5), *_pt(81.5, 25.5)), fill=255)
    _fill(image, dot, _hex("#8CA8C9"))
    dot_inner = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(dot_inner).ellipse((*_pt(67.5, 11.5), *_pt(80.5, 24.5)), fill=255)
    _fill(image, dot_inner, _hex("#ADC1D9"))

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "app.ico"
    icon = draw_icon()
    icon.save(output, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if len(sys.argv) > 2:
        icon.save(sys.argv[2])
    print(f"已產生 {output}")
