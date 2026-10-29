"""Deterministic public-only isometric PNGs, same labels as the request JSON."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .common import sha

FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def font(size=14):
    return ImageFont.truetype(FONT_PATH, size)


def _scene(draw, rect, container, placed, candidate=None):
    left, top, width, height = rect
    length, breadth, ceiling = (container[k] for k in ('length_mm', 'width_mm', 'max_height_mm'))
    scale = min((width-28)/(length+breadth), (height-40)/(.40*(length+breadth)+ceiling))
    def point(x, y, z):
        return (left+width/2+(x-y)*scale, top+height-25-(.4*(x+y+(length+breadth)/2)+z)*scale)
    floor = [point(x, y, 0) for x, y in [(-length/2, -breadth/2), (length/2, -breadth/2),
                                       (length/2, breadth/2), (-length/2, breadth/2)]]
    draw.polygon(floor, fill='#eef1f4', outline='#333333')
    for label, xyz in [('origin', (0, 0, 0)), ('+X right', (length/2, 0, 0)), ('+Y back', (0, breadth/2, 0))]:
        xy = point(*xyz)
        draw.text(xy, label, fill='#444444', font=font(9))
    objects = [(p, False) for p in placed]
    if candidate:
        objects.append((candidate, True))
    objects.sort(key=lambda entry: (-entry[0]['pose']['x_mm']-entry[0]['pose']['y_mm'],
                                     entry[0]['pose']['z_base_mm']))
    for obj, highlighted in objects:
        x, y, z = (obj['pose'][k] for k in ('x_mm', 'y_mm', 'z_base_mm'))
        l, w, h = obj['oriented_size_mm']
        corners = [(x-l/2, y-w/2), (x+l/2, y-w/2), (x+l/2, y+w/2), (x-l/2, y+w/2)]
        lower = [point(a, b, z) for a, b in corners]
        upper = [point(a, b, z+h) for a, b in corners]
        colors = ('#507faa', '#6b9bc6', '#a2c8eb') if highlighted else ('#939ba3', '#afb7bf', '#d8dfe6')
        for face, color in [(lower[:2]+upper[:2][::-1], colors[0]),
                            ([lower[0], lower[3], upper[3], upper[0]], colors[1]), (upper, colors[2])]:
            draw.polygon(face, fill=color, outline='#333333')
        center = point(x, y, z+h)
        draw.text(center, obj.get('candidate_id', obj.get('item_id', '')), fill='#111111', font=font(10))


def render(public, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (800, 620), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), 'CURRENT PUBLIC LAYOUT | mm | Z up', fill='black', font=font(18))
    _scene(draw, (0, 45, 800, 475), public['container'], public['placed_items'])
    current = public['current_item']
    draw.text((12, 540), 'CURRENT ITEM ' + current['item_id'], fill='black', font=font(16))
    dims = [current['dimensions_mm'][k] for k in ('length', 'width', 'height')]
    draw.text((12, 567), f"L/W/H mm: {dims} | mass kg: {current['mass_kg']}", fill='black', font=font(15))
    draw.text((12, 592), 'stackable: true | physical top-load limit: 100 kg', fill='black', font=font(14))
    image.save(directory/'workspace.png')
    rows = max(1, (len(public['candidates'])+3)//4)
    montage = Image.new('RGB', (1120, rows*260+36), 'white')
    draw = ImageDraw.Draw(montage)
    draw.text((12, 8), 'CURRENT CANDIDATES | blue = hypothetical placement', fill='black', font=font(16))
    for i, c in enumerate(public['candidates']):
        x, y = (i % 4)*280, 36+(i//4)*260
        draw.rectangle((x, y, x+279, y+259), outline='#dddddd')
        draw.text((x+8, y+8), c['candidate_id'], fill='black', font=font(17))
        _scene(draw, (x, y+15, 280, 235), public['container'], public['placed_items'], c)
    if not public['candidates']:
        draw.text((12, 60), 'NO PHYSICAL CANDIDATE', fill='black', font=font(18))
    montage.save(directory/'candidates.png')
    return [{'asset_id': name, 'sha256': sha(directory/(name+'.png')),
             'width': size[0], 'height': size[1], 'media_type': 'image/png'}
            for name, size in [('workspace', image.size), ('candidates', montage.size)]]
