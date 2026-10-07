"""Server-side SVG bar charts. No JavaScript, no CDN - works offline."""


def _nice_step(x):
    if x <= 0:
        return 1
    import math
    p = 10 ** math.floor(math.log10(x))
    n = x / p
    if n < 1.5:
        return p
    if n < 3:
        return 2 * p
    if n < 7:
        return 5 * p
    return 10 * p


def grouped_bars(groups, fmt, width=680, height=300):
    """groups: [{label, sub, bars: [(value|None, color)]}]. fmt formats a number."""
    ml, mr, mt, mb = 58, 14, 18, 62
    vals = [v for g in groups for (v, _c) in g["bars"] if v is not None]
    if not vals:
        return '<p style="color:#888">No numbers to chart yet.</p>'
    lo = min(0, min(vals))
    hi = max(0, max(vals))
    pad = (hi - lo) * 0.14 or 1
    lo -= pad
    hi += pad

    def y(v):
        return mt + (hi - v) / (hi - lo) * (height - mt - mb)

    slot = (width - ml - mr) / len(groups)
    bw, gap = 30, 8
    s = [f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;display:block" role="img">']
    step = _nice_step((hi - lo) / 4)
    t = __import__("math").ceil(lo / step) * step
    while t <= hi:
        yy = round(y(t), 1)
        s.append(f'<line x1="{ml}" y1="{yy}" x2="{width-mr}" y2="{yy}" stroke="#e2e8f0"/>')
        s.append(f'<text x="{ml-8}" y="{yy+4}" text-anchor="end" font-size="11" fill="#64748b">{fmt(t)}</text>')
        t += step
    y0 = y(0)
    s.append(f'<line x1="{ml}" y1="{y0}" x2="{width-mr}" y2="{y0}" stroke="#94a3b8"/>')
    for gi, g in enumerate(groups):
        cx = ml + slot * (gi + 0.5)
        bars = g["bars"]
        total = len(bars) * bw + (len(bars) - 1) * gap
        x0 = cx - total / 2
        for bi, (v, color) in enumerate(bars):
            x = x0 + bi * (bw + gap)
            if v is None:
                s.append(f'<text x="{x+bw/2}" y="{y0-8}" text-anchor="middle" font-size="12" fill="#94a3b8">-</text>')
                continue
            yv = y(v)
            top, hgt = min(yv, y0), abs(yv - y0)
            s.append(f'<rect x="{round(x,1)}" y="{round(top,1)}" width="{bw}" '
                     f'height="{round(max(hgt,2),1)}" rx="3" fill="{color}"/>')
            ly = top - 7 if v >= 0 else top + hgt + 15
            s.append(f'<text x="{x+bw/2}" y="{round(ly,1)}" text-anchor="middle" '
                     f'font-size="11" font-weight="600" fill="#1e293b">{fmt(v)}</text>')
        s.append(f'<text x="{cx}" y="{height-40}" text-anchor="middle" font-size="11" '
                 f'font-weight="600" fill="#1e293b">{g["label"]}</text>')
        s.append(f'<text x="{cx}" y="{height-25}" text-anchor="middle" font-size="10" '
                 f'fill="#64748b">{g["sub"]}</text>')
    s.append("</svg>")
    return "".join(s)


def legend(items):
    """items: [(color, label)] -> html legend."""
    parts = ['<div style="display:flex;flex-wrap:wrap;gap:16px;margin:4px 0 12px;'
             'font-size:12px;color:#475569">']
    for color, label in items:
        parts.append(
            f'<span><span style="display:inline-block;width:11px;height:11px;border-radius:3px;'
            f'background:{color};margin-right:6px"></span>{label}</span>')
    parts.append("</div>")
    return "".join(parts)


SLATE = "#94a3b8"
BLUE = "#2563eb"
VIOLET = "#7c3aed"
AMBER = "#d97706"
GREEN = "#059669"

money = lambda v: ("-$" if v < 0 else "$") + f"{abs(v):.1f}M"
pct = lambda v: f"{v:.2f}%"
