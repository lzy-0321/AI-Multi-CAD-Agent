import unittest
from scripts.release_metadata import metadata


class ReleaseMetadataTests(unittest.TestCase):
    def test_stable_version_is_not_prerelease(self):
        self.assertEqual(metadata('0.3.1', 'v0.3.1')['status'], 'release')
        self.assertFalse(metadata('0.3.1', 'v0.3.1')['prerelease'])

    def test_candidate_stays_prerelease(self):
        self.assertTrue(metadata('0.3.0rc1', 'v0.3.0rc1')['prerelease'])

    def test_relabeling_candidate_tag_is_rejected_with_both_values(self):
        with self.assertRaisesRegex(ValueError, "v0.3.0.*0.3.0rc1.*v0.3.0rc1"):
            metadata('0.3.0rc1', 'v0.3.0')

    def test_branch_name_cannot_be_published_as_version(self):
        with self.assertRaises(ValueError):
            metadata('0.3.1', 'master')
