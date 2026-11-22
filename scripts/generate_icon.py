"""生成 Resin 256px 多尺寸高清 Windows .ico 图标与 Android 启动器 PNG 图标."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


def draw_resin_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(size * 0.06)
    # 深海蓝圆角底座
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=int(size * 0.22),
        fill=(15, 23, 42, 255),
        outline=(56, 189, 248, 255),
        width=max(2, int(size * 0.03)),
    )

    # 内层发光翡翠/青蓝网格护盾环
    inner_pad = int(size * 0.18)
    draw.ellipse(
        [inner_pad, inner_pad, size - inner_pad, size - inner_pad],
        fill=(14, 116, 144, 230),
        outline=(16, 185, 129, 255),
        width=max(2, int(size * 0.025)),
    )

    # 绘制智能路由星型拓扑节点与连接线
    cx, cy = size // 2, size // 2
    r_outer = int(size * 0.23)
    nodes = [
        (cx, cy - r_outer),
        (cx + int(r_outer * 0.95), cy - int(r_outer * 0.3)),
        (cx + int(r_outer * 0.6), cy + int(r_outer * 0.8)),
        (cx - int(r_outer * 0.6), cy + int(r_outer * 0.8)),
        (cx - int(r_outer * 0.95), cy - int(r_outer * 0.3)),
    ]
    line_w = max(2, int(size * 0.035))
    for nx, ny in nodes:
        draw.line([(cx, cy), (nx, ny)], fill=(224, 242, 254, 255), width=line_w)

    # 中心核心汇聚网关节点
    c_rad = max(4, int(size * 0.09))
    draw.ellipse(
        [cx - c_rad, cy - c_rad, cx + c_rad, cy + c_rad],
        fill=(16, 185, 129, 255),
        outline=(255, 255, 255, 255),
        width=max(1, int(size * 0.02)),
    )

    # 外围代理节点
    n_rad = max(3, int(size * 0.05))
    for nx, ny in nodes:
        draw.ellipse(
            [nx - n_rad, ny - n_rad, nx + n_rad, ny + n_rad],
            fill=(56, 189, 248, 255),
            outline=(255, 255, 255, 255),
            width=max(1, int(size * 0.015)),
        )

    return img


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    master = draw_resin_icon(256)
    ico_path = assets_dir / "resin.ico"
    png_path = assets_dir / "resin.png"

    master.save(png_path, format="PNG")
    master.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Generated Windows multi-size icon: {ico_path}")

    # 同时为 Android 客户端生成各密度 mipmap 图标
    android_res = root / "android" / "app" / "src" / "main" / "res"
    mipmaps = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder, px in mipmaps.items():
        d = android_res / folder
        d.mkdir(parents=True, exist_ok=True)
        resized = master.resize((px, px), Image.Resampling.LANCZOS)
        resized.save(d / "ic_launcher.png", format="PNG")
        resized.save(d / "ic_launcher_round.png", format="PNG")
    print(f"Generated Android mipmap icons under: {android_res}")


if __name__ == "__main__":
    main()
