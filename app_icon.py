"""Pressure-gauge app icon shared by Tk windows and optional Windows packaging."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageTk


def gauge_image(size: int = 64) -> Image.Image:
    """Draw a crisp navy/teal analog gauge without downloaded assets."""
    scale = 4
    n = size * scale
    im = Image.new("RGBA", (n, n), (23, 51, 76, 255))
    d = ImageDraw.Draw(im)
    c = n / 2
    r = n * .32
    line = max(3, round(n * .055))
    d.ellipse((c-r, c-r, c+r, c+r), outline=(230, 244, 248, 255), width=line)
    # Teal pressure arc in the lower/left portion of the gauge.
    d.arc((c-r*.78, c-r*.78, c+r*.78, c+r*.78),
          start=42, end=168, fill=(42, 199, 189, 255), width=max(2, line//2))
    for deg in (145, 105, 65, 25):
        import math
        a=math.radians(deg)
        x1=c+math.cos(a)*r*.69
        y1=c-math.sin(a)*r*.69
        x2=c+math.cos(a)*r*.88
        y2=c-math.sin(a)*r*.88
        d.line((x1,y1,x2,y2),fill=(231,244,247,255),width=max(2,line//3))
    import math
    angle=math.radians(37)
    needle=(c+math.cos(angle)*r*.70,c-math.sin(angle)*r*.70)
    d.line((c,c,*needle),fill=(42,199,189,255),width=max(3,line//2))
    pivot=r*.12
    d.ellipse((c-pivot,c-pivot,c+pivot,c+pivot),fill=(244,252,251,255))
    return im.resize((size,size),Image.Resampling.LANCZOS)


def set_window_icon(root) -> None:
    icons=[ImageTk.PhotoImage(gauge_image(s),master=root) for s in (64,32,16)]
    root.iconphoto(True,*icons)
    root._pressure_gauge_icons=icons  # Keep image references alive.


def export_windows_icon(path: str | Path) -> None:
    out=Path(path)
    out.parent.mkdir(parents=True,exist_ok=True)
    gauge_image(256).save(out,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
