import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from layout_audit import AuditError, audit


class LayoutAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = np.full((12, 12, 4), 255, np.uint8)
        self.core = np.zeros((12, 12), np.uint8)
        self.core[3:9, 4:8] = 255
        self.carrier = np.full((32, 32), 255, np.uint8)
        self.layer = np.full((32, 32, 4), 255, np.uint8)

    def tearDown(self):
        self.tmp.cleanup()

    def image(self, name, pixels):
        p = self.root / name
        Image.fromarray(pixels).save(p)
        return {'path': name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}

    def plan(self, matrix=None, **extra):
        item = {'id': 'wing', 'source': self.image('source.png', self.source),
                'critical': self.image('core.png', self.core),
                'actual_layer': self.image('layer.png', self.layer),
                'carrier': self.image('carrier.png', self.carrier),
                'source_to_canvas': matrix or [1, 0, 5, 0, 1, 6], **extra}
        p = self.root / 'plan.json'
        p.write_text(json.dumps({'schema_version': 1, 'canvas': [32, 32], 'instances': [item]}), encoding='utf-8')
        return p

    def test_translation_preserves_all_critical_pixels(self):
        r = audit(self.plan())
        self.assertTrue(r['passed'])
        self.assertEqual(r['instances'][0]['critical_source_pixels'], 24)

    def test_rotation_is_checked_in_target_coordinates(self):
        self.carrier[:] = 0
        self.carrier[4:8, 11:17] = 255
        self.assertTrue(audit(self.plan([0, -1, 20, 1, 0, 0]))['passed'])

    def test_crop_outside_canvas_is_not_hidden_by_target_mask(self):
        r = audit(self.plan([1, 0, -7, 0, 1, 0]))
        self.assertFalse(r['passed'])
        self.assertEqual(r['instances'][0]['failure_counts']['outside_canvas'], 18)

    def test_split_carrier_catches_face_over_gap(self):
        self.carrier[:, 10:12] = 0
        r = audit(self.plan())
        self.assertEqual(r['instances'][0]['failure_counts']['outside_carrier'], 12)

    def test_export_alpha_failure_is_distinct_from_carrier(self):
        self.layer[9:15, 9:13, 3] = 0
        r = audit(self.plan())
        self.assertEqual(r['instances'][0]['failure_counts']['missing_export_alpha'], 24)
        self.assertEqual(r['instances'][0]['failure_counts']['outside_carrier'], 0)

    def test_empty_or_transparent_core_is_not_success(self):
        self.core[:] = 0
        with self.assertRaises(AuditError):
            audit(self.plan())
        self.core[1, 1] = 255
        self.source[1, 1, 3] = 0
        with self.assertRaises(AuditError):
            audit(self.plan())

    def test_mirror_needs_explicit_decision(self):
        with self.assertRaises(AuditError):
            audit(self.plan([-1, 0, 20, 0, 1, 0]))
        self.assertTrue(audit(self.plan([-1, 0, 20, 0, 1, 0], allow_mirror=True))['passed'])

    def test_hash_and_dimensions_are_real_contracts(self):
        p = self.plan()
        (self.root / 'source.png').write_bytes(b'changed')
        with self.assertRaises(AuditError):
            audit(p)
        self.layer = np.zeros((30, 32, 4), np.uint8)
        with self.assertRaises(AuditError):
            audit(self.plan())

    def test_bad_transform_or_escape_is_rejected(self):
        for m in ([0, 0, 0, 0, 0, 0], [float('nan'), 0, 0, 0, 1, 0]):
            with self.assertRaises(AuditError):
                audit(self.plan(m))
        p = self.plan()
        data = json.loads(p.read_text())
        data['instances'][0]['source']['path'] = '../source.png'
        p.write_text(json.dumps(data))
        with self.assertRaises(AuditError):
            audit(p)


if __name__ == '__main__':
    unittest.main()
