"""QA-GP1-E01 public entry regression; no stubs, budgets or physical imports."""
import unittest
from semantic_pallet_planner.planner.space_candidates import build_space_index


def raw_length(token):
    return ('{"version":"geometry_space_input_v1","container":{"length_mm":'+token+
            ',"width_mm":10,"max_height_mm":10},"placed_items":[]}').encode()


class NumericErrorRegression(unittest.TestCase):
    def test_decimal_exponent_conversion_failures_are_atomic(self):
        # Original QA exponent plus distinct exponent/sign variations of the
        # same Decimal conversion class, not special-casing one literal.
        for token in ('1e999999999999999999999999', '1e-999999999999999999999999',
                      '-1e1000000000000000000000000', '-1e-1000000000000000000000000'):
            with self.subTest(token=token):
                r=build_space_index(raw_length(token))
                self.assertEqual(r['status'],'ERROR')
                self.assertEqual(r['error']['code'],'UNSUPPORTED_GEOMETRY_NUMBER')
                self.assertEqual(r['spaces'],[])
                self.assertIsNone(r['surface'])
                self.assertIsNone(r['input_digest'])  # rejected before geometry

    def test_normal_positive_and_negative_exponents_keep_geometry(self):
        for exponential,plain in (('1e2','100'),('1e-2','0.01'),('1e0','1')):
            with self.subTest(token=exponential):
                r=build_space_index(raw_length(exponential))
                control=build_space_index(raw_length(plain))
                self.assertEqual(r['status'],'OK')
                self.assertEqual({k:v for k,v in r.items() if k!='source_bytes_sha256'},
                                 {k:v for k,v in control.items() if k!='source_bytes_sha256'})


if __name__=='__main__':
    unittest.main()
