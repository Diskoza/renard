"""Renard logo variants from the user's original fox artwork (traced to vector, look unchanged).
Only colours/background/composition differ:  icon (shortcut, tray, header), tg (square Telegram avatar),
corner (no background, in-app corner), sleep (night palette, moon, zZ).
Usage: .venv\\Scripts\\python scripts\\gen_logo.py  then  scripts\\build_icons.py"""
import re
import math
from pathlib import Path
A = Path(__file__).resolve().parent.parent / "web" / "assets"
fb = (A / "src" / "fox_paths.svgfrag").read_text(encoding="utf-8")
def rgb(h): return tuple(int(h[i:i+2],16) for i in (1,3,5))
TOK={'base':'#D77653','light':'#FB9D60','mid':'#AC624B','shadow':'#8A4B37','warm':'#C26C4F'}
def tok(h):
    c=rgb(h); return min(TOK,key=lambda k:sum((a-b)**2 for a,b in zip(rgb(TOK[k]),c)))
def fox(pal):
    return re.sub(r'fill="(#[0-9A-F]{6})"',lambda m:f'fill="{pal[tok(m.group(1))]}"',fb)
def sparkle(cx,cy,r,w=0.16,minor=0.0,fill='#fff',op=1):
    pts=[]
    n=8 if minor else 4
    for i in range(n*2):
        a=math.pi/2+i*math.pi/n
        if i%2==0: rr=r if (n==4 or (i//2)%2==0) else r*minor
        else: rr=r*w
        pts.append(f'{cx+rr*math.cos(a):.1f} {cy-rr*math.sin(a):.1f}')
    return f'<path d="M{" L".join(pts)}Z" fill="{fill}" opacity="{op}"/>'
STARS=lambda fill='#fff',f='url(#sg)':(f'<g fill="{fill}" filter="{f}">'+sparkle(742,203,80,0.17,0.45,fill)+sparkle(862,316,30,0.2,0,fill,0.95)+sparkle(766,384,26,0.13,0,fill,0.9)+'</g>')
DAY=dict(TOK, base='#D97757')
SVG='<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">'
GLOW='<filter id="sg" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
BG='''<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#1F1C47"/><stop offset="0.42" stop-color="#2A2350"/><stop offset="0.72" stop-color="#46304F"/><stop offset="1" stop-color="#6E3C42"/></linearGradient>
<radialGradient id="halo" cx="0.42" cy="0.36" r="0.42"><stop offset="0" stop-color="#D97757" stop-opacity="0.22"/><stop offset="1" stop-color="#D97757" stop-opacity="0"/></radialGradient>
<clipPath id="c"><circle cx="512" cy="512" r="500"/></clipPath>'''
icon=(SVG.format(vb='0 0 1024 1024')+'<defs>'+BG+GLOW+'</defs>'
 '<circle cx="512" cy="512" r="500" fill="url(#bg)"/><circle cx="512" cy="512" r="500" fill="url(#halo)"/>'
 '<g clip-path="url(#c)">'+fox(DAY)+'</g>'+STARS()+
 '<circle cx="512" cy="512" r="496" fill="none" stroke="#D97757" stroke-opacity="0.35" stroke-width="8"/></svg>')
tg=icon.replace('<circle cx="512" cy="512" r="500" fill="url(#bg)"/>','<rect width="1024" height="1024" fill="url(#bg)"/>').replace('<circle cx="512" cy="512" r="496" fill="none" stroke="#D97757" stroke-opacity="0.35" stroke-width="8"/>','')
cornerpal=dict(DAY)
corner=(SVG.format(vb='60 40 900 915')+'<defs>'+GLOW+
 '<radialGradient id="g2" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#D97757" stop-opacity="0.16"/><stop offset="1" stop-color="#D97757" stop-opacity="0"/></radialGradient>'
 '<clipPath id="c"><circle cx="512" cy="512" r="500"/></clipPath>'
 '<linearGradient id="fade" gradientUnits="userSpaceOnUse" x1="0" y1="850" x2="0" y2="950"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
 '<mask id="m"><rect width="1024" height="1024" fill="url(#fade)"/></mask></defs>'
 '<ellipse cx="512" cy="620" rx="430" ry="330" fill="url(#g2)"/>'
 '<g clip-path="url(#c)" mask="url(#m)">'+fox(cornerpal)+'</g>'+STARS('#FFE2C4')+'</svg>')
NIGHT={'base':'#A9604F','light':'#C98466','mid':'#8A4E45','shadow':'#5E3438','warm':'#9A5749'}
SBG='''<linearGradient id="nb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14122E"/><stop offset="0.6" stop-color="#1D1838"/><stop offset="1" stop-color="#36253A"/></linearGradient>
<radialGradient id="mg" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#FFE9C9" stop-opacity="0.35"/><stop offset="1" stop-color="#FFE9C9" stop-opacity="0"/></radialGradient>
<clipPath id="c"><circle cx="512" cy="512" r="500"/></clipPath><mask id="moon"><rect width="1024" height="1024" fill="#fff"/><circle cx="866" cy="162" r="66" fill="#000"/></mask>'''
z=lambda x,y,s,o:f'<text x="{x}" y="{y}" font-family="Segoe UI, Arial, sans-serif" font-weight="700" font-size="{s}" fill="#C9C3E6" opacity="{o}">z</text>'
sleep=(SVG.format(vb='0 0 1024 1024')+'<defs>'+SBG+GLOW+'</defs>'
 '<circle cx="512" cy="512" r="500" fill="url(#nb)"/>'
 '<circle cx="820" cy="200" r="150" fill="url(#mg)"/><circle cx="820" cy="200" r="74" fill="#FFE2C4" mask="url(#moon)"/>'
 '<g clip-path="url(#c)">'+fox(NIGHT)+'</g>'+
 sparkle(880,420,22,0.2,0,'#E8E3FF',0.7)+sparkle(250,150,16,0.2,0,'#E8E3FF',0.5)+sparkle(160,330,10,0.25,0,'#E8E3FF',0.4)+
 z(610,300,46,0.45)+z(655,240,62,0.65)+z(712,170,80,0.9)+
 '<circle cx="512" cy="512" r="496" fill="none" stroke="#6F5FA8" stroke-opacity="0.35" stroke-width="8"/></svg>')
for n,s in (('renard_icon.svg',icon),('renard_tg.svg',tg),('renard_corner.svg',corner),('renard_sleep.svg',sleep)):
    (A / n).write_text(s, encoding='utf-8'); print(n, len(s))
