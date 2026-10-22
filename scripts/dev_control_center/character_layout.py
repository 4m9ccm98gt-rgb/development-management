"""Pure character sizing against the existing loop geometry; no layout mutation."""
import math

# Conservative horizontal bands covering nonzero alpha in all 6 x 72 shipped
# frames, at the authored 240 x 333 resolution. Tests guard asset changes.
SPRITE_BANDS = (
    (105,0,143,16), (64,16,163,32), (26,32,218,48), (25,48,217,64),
    (24,64,217,80), (24,80,215,96), (24,96,218,112), (24,112,222,128),
    (16,128,221,144), (11,144,221,160), (11,160,222,176), (11,176,220,192),
    (14,192,219,208), (22,208,218,224), (24,224,215,240), (25,240,216,256),
    (26,256,216,272), (26,272,216,288), (28,288,217,304), (28,304,217,320),
    (74,320,167,333),
)

def loop_obstacles(width, height):
    cx, cy = width/2, height*.53
    radius = max(100, min(width*.46, (height-85)*.47))
    panel_w = max(155, width*.29)
    panel_h = max(75, min(155, (height-150)*.27))
    circles, panels = [], []
    for angle in (135,45,-45,-135):
        x = cx+radius*.83*math.cos(math.radians(angle))
        y = cy-radius*.83*math.sin(math.radians(angle))
        y = min(y,height-panel_h-58) if angle < 0 else max(108,y)
        circles.append((x,y,42))
        left = 8 if angle in (135,-135) else width-panel_w-8
        panels.append((left,y+48,left+panel_w,y+48+panel_h))
    return circles, panels


def fits_character(width, height, factor):
    # 8px clearance also covers the LANCZOS alpha fringe outside the bands.
    circles, panels = loop_obstacles(width,height)
    left, top = width/2-math.ceil(240*factor)/2, height*.53-math.ceil(333*factor)/2
    for a,b,c,d in SPRITE_BANDS:
        x0,y0,x1,y1 = left+a*factor,top+b*factor,left+c*factor,top+d*factor
        if x0<4 or y0<4 or x1>width-4 or y1>height-4:
            return False
        for px,py,qx,qy in panels:
            if x0<qx+8 and x1>px-8 and y0<qy+8 and y1>py-8:
                return False
        for x,y,r in circles:
            nx,ny = max(x0,min(x,x1)),max(y0,min(y,y1))
            if (x-nx)**2+(y-ny)**2 < (r+8)**2:
                return False
    return True


def character_display_scale(width,height):
    """Aim for 1.4x authored size, reducing only to keep observed UI clear.

    The 1% steps avoid near-identical image preparations during small resizes.
    They do not constrain the renderer's arbitrary floating-point scale API.
    """
    for step in range(140,24,-1):
        factor=step/100
        if fits_character(width,height,factor):
            return factor
    return .25
