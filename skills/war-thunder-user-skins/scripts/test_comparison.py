import unittest
import numpy as np
from compare_skin import channel_metrics, normal_metrics
from composa_mcp import McpError, validate_required_arguments


class ComparisonTests(unittest.TestCase):
    def test_mask_excludes_unused_atlas(self):
        reference=np.zeros((4,4),dtype=np.uint8)
        edited=reference.copy(); edited[2:,:]=255
        mask=np.zeros((4,4),dtype=bool); mask[:2,:]=True
        result=channel_metrics(reference,edited,mask)
        self.assertEqual(result['mae_0_255'],0)
        self.assertEqual(result['pixels_diff_gt_8_percent'],0)

    def test_constant_baseline_has_no_defined_correlation(self):
        plane=np.full((4,4),128,dtype=np.uint8)
        result=channel_metrics(plane,plane,np.ones((4,4),dtype=bool))
        self.assertIsNone(result['correlation'])

    def test_normals_ignore_roughness_and_metallicity_changes(self):
        base=np.full((4,4,4),128,dtype=np.uint8)
        modified=base.copy(); modified[:,:,0]=255; modified[:,:,2]=0
        result=normal_metrics(base,modified,np.ones((4,4),dtype=bool))
        self.assertLess(result['mean_degrees'],0.05)

    def test_layer_identifier_required_by_live_schema(self):
        tool={'name':'set_layer','inputSchema':{'required':['layer']}}
        with self.assertRaises(McpError):
            validate_required_arguments(tool,{'name':'UV wire'})
        validate_required_arguments(tool,{'layer':'1239a4d3','name':'UV wire'})


if __name__=='__main__':
    unittest.main()
