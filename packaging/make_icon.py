"""產生安裝版的程式圖示（深色圓角底 + 紅綠 K 棒），不依賴字型，打包機器上一定畫得出來。

用法：python packaging/make_icon.py 輸出路徑.ico
"""

import sys

from PIL import Image, ImageDraw

SIZE = 256
BACKGROUND = (11, 15, 23, 255)
UP = (240, 82, 79, 255)
DOWN = (34, 181, 115, 255)
WICK = (201, 209, 222, 255)

# (中心 x, 影線上緣, 實體上緣, 實體下緣, 影線下緣, 顏色)
_CANDLES = [
    (62, 128, 146, 196, 214, DOWN),
    (110, 92, 110, 170, 190, UP),
    (158, 104, 122, 150, 176, DOWN),
    (206, 44, 62, 132, 150, UP),
]


def draw_icon() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=48, fill=BACKGROUND)
    for x, wick_top, body_top, body_bottom, wick_bottom, color in _CANDLES:
        draw.rectangle((x - 3, wick_top, x + 3, wick_bottom), fill=WICK)
        draw.rounded_rectangle((x - 17, body_top, x + 17, body_bottom), radius=5, fill=color)
    return image


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "app.ico"
    draw_icon().save(output, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"已產生 {output}")
