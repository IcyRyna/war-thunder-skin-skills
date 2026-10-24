"""Guard a shared scalable camouflage pattern without replacing net cutouts."""
import numpy as np
from PIL import Image


def check_scope(materials, pattern_resource, contract):
    resource = pattern_resource.rstrip('*').casefold()
    rows = contract['bindings']
    fixed = {r['resource'].rstrip('*').casefold() for r in rows
             if r.get('coverage') == 'opaque_fixed' and r['role'] == 'color'}
    users, nets, protected = set(), set(), set()
    for material in materials['materials']:
        slots = material['texture_slots']
        if len(slots) < 2 or not slots[1] or slots[1].rstrip('*').casefold() != resource:
            continue
        shader = material['shader']
        if shader == 'dynamic_tank_net_atest':
            nets.add(material.get('obj_name', material.get('name')))
            protected.update(s.rstrip('*').casefold() for i, s in enumerate(slots)
                             if i in [0, 2, 3] and s)
        elif shader == 'dynamic_masked_tank':
            if not slots[0]:
                raise ValueError('A shared solid material has no color resource')
            users.add(slots[0].rstrip('*').casefold())
        else:
            raise ValueError('Unknown shader shares the scalable pattern: '+shader)
    if not nets:
        raise ValueError('No confirmed native camouflage-net material uses this pattern')
    if not users <= fixed:
        raise ValueError('Shared solid materials need fixed coverage before net pattern replacement: '+', '.join(sorted(users-fixed)))
    if protected & {r['resource'].rstrip('*').casefold() for r in rows}:
        raise ValueError('Keep native net C, cutout Alpha, N and AO; use supported base-pattern binding')
    matching = [r for r in rows if r['resource'].rstrip('*').casefold() == resource]
    if len(matching) != 1 or matching[0]['role'] != 'pattern' or matching[0].get('coverage'):
        raise ValueError('Exactly one separate scalable pattern binding is required')
    return {'pattern_resource': resource, 'net_materials': sorted(nets),
            'fixed_solid_color_resources': sorted(users), 'native_net_C_N_AO_unchanged': True,
            'scope': 'shared texture slots from native material evidence', 'game_visual': 'pending'}


def make_pattern(size, background, patch, rectangles):
    if not isinstance(size, int) or size not in [128, 256, 512, 1024, 2048, 4096]:
        raise ValueError('A supported square scalable texture is required')
    colors = np.asarray([background, patch])
    if colors.shape != (2, 3) or not np.isfinite(colors).all() or colors.min() < 0 or colors.max() > 255:
        raise ValueError('Two explicit RGB colors are required')
    a = np.empty((size, size, 4), np.uint8)
    a[:, :, :3] = background
    a[:, :, 3] = 255
    for x, y, width, height in rectangles:
        if not all(isinstance(v, int) for v in [x, y, width, height]) or not 0 < width < size or not 0 < height < size:
            raise ValueError('Pattern rectangles must be explicit bounded integers')
        xx = np.arange(x, x+width) % size
        yy = np.arange(y, y+height) % size
        a[np.ix_(yy, xx, [0, 1, 2])] = patch
    if not np.array_equal(a[0], a[-1]) or not np.array_equal(a[:, 0], a[:, -1]):
        raise ValueError('Pattern edges must match for seamless repetition')
    return Image.fromarray(a)
