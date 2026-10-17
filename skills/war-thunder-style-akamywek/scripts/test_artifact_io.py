"""Real-filesystem regressions for protected artifact publication."""

import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact_io import ArtifactError, ArtifactTransaction


class ArtifactTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source.tga"
        self.original = b"unchanged original texture\x00\xff"
        self.source.write_bytes(self.original)

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.temporary.cleanup()

    def receipt(self, transaction):
        self.assertIsNotNone(transaction.failure_receipt)
        return json.loads(transaction.failure_receipt.read_text(encoding="utf-8"))

    def assert_no_staging(self):
        self.assertEqual(list(self.root.rglob(".artifact-*-*")), [])

    def test_success_preserves_suffix_relative_names_and_exact_bytes(self):
        first = self.root / "delivery" / "paint.tga"
        second = first.with_suffix(".blk")
        with ArtifactTransaction([first, second], [self.source]) as transaction:
            staged = transaction.stage(first)
            other = transaction.stage(second)
            self.assertEqual(staged.suffix, ".tga")
            self.assertEqual(staged.name, first.name)
            self.assertEqual(staged.parent, other.parent)
            self.assertEqual(transaction.stage(first), staged)
            staged.write_bytes(b"new skin bytes")
            other.write_text('to:t="paint.tga"', encoding="utf-8")
            transaction.commit()
        self.assertEqual(first.read_bytes(), b"new skin bytes")
        self.assertEqual(second.read_text(), 'to:t="paint.tga"')
        self.assertIsNone(transaction.failure_receipt)
        self.assert_no_staging()

    def test_existing_file_rejected_before_any_write(self):
        before = sorted(str(item) for item in self.root.rglob("*"))
        with self.assertRaises(FileExistsError):
            ArtifactTransaction([self.source], [self.source])
        self.assertEqual(sorted(str(item) for item in self.root.rglob("*")), before)

    def test_duplicate_and_case_aliases_rejected_without_writes(self):
        destination = self.root / "preview.png"
        for outputs in ([destination, destination], [destination, self.root / "PREVIEW.PNG"]):
            with self.subTest(outputs=outputs), self.assertRaises(ArtifactError):
                ArtifactTransaction(outputs, [self.source])
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_input_directory_blocks_derived_file(self):
        source_directory = self.root / "original"
        source_directory.mkdir()
        (source_directory / "texture.tga").write_bytes(b"original")
        before = sorted(str(item) for item in self.root.rglob("*"))
        with self.assertRaises(ArtifactError):
            ArtifactTransaction([source_directory / "preview.png"], [source_directory])
        self.assertEqual(sorted(str(item) for item in self.root.rglob("*")), before)

    def test_existing_hard_link_alias_is_rejected(self):
        alias = self.root / "different-name.png"
        os.link(self.source, alias)
        with self.assertRaises(FileExistsError):
            ArtifactTransaction([alias], [self.source])
        self.assertEqual(alias.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob(".artifact*")), [])

    def test_output_ancestry_aliases_are_rejected(self):
        directory = self.root / "same-parent"
        directory.mkdir()
        destination = directory / "new.png"
        alias = directory / ".." / "same-parent" / "new.png"
        with self.assertRaises(ArtifactError):
            ArtifactTransaction([destination, alias], [self.source])

    def test_output_file_cannot_be_another_output_parent(self):
        first = self.root / "artifact"
        with self.assertRaises(ArtifactError):
            ArtifactTransaction([first, first / "child.png"])

    def test_preflight_repeated_on_enter(self):
        output = self.root / "new.png"
        transaction = ArtifactTransaction([output], [self.source])
        output.write_bytes(b"concurrent creation")
        with self.assertRaises(FileExistsError):
            with transaction:
                self.fail("must not enter")
        self.assertEqual(output.read_bytes(), b"concurrent creation")
        self.assertIsNone(transaction.failure_receipt)
        self.assert_no_staging()

    def test_mid_operation_error_retains_failure_receipt_and_no_outputs(self):
        output = self.root / "new" / "nested" / "result.png"
        receipts = self.root / "receipts"
        with self.assertRaisesRegex(OSError, "simulated write failure"):
            with ArtifactTransaction([output], [self.source], label="preview", failure_directory=receipts) as transaction:
                transaction.stage(output).write_bytes(b"partial work")
                raise OSError("simulated write failure")
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "new").exists())
        record = self.receipt(transaction)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["label"], "preview")
        self.assertEqual(record["error_type"], "OSError")
        self.assert_no_staging()

    def test_missing_declared_stage_rejects_complete_set(self):
        outputs = [self.root / "first.png", self.root / "second.json"]
        with self.assertRaisesRegex(ArtifactError, "No staged file"):
            with ArtifactTransaction(outputs, [self.source]) as transaction:
                transaction.stage(outputs[0]).write_bytes(b"first")
                transaction.commit()
        self.assertFalse(any(item.exists() for item in outputs))
        self.receipt(transaction)
        self.assert_no_staging()

    def test_missing_commit_is_not_silent_success(self):
        output = self.root / "result.png"
        with self.assertRaisesRegex(ArtifactError, "without commit"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                transaction.stage(output).write_bytes(b"work")
        self.assertFalse(output.exists())
        self.receipt(transaction)

    def test_mid_commit_io_error_rolls_back_earlier_owned_files(self):
        outputs = [self.root / "a.png", self.root / "b.json"]
        real_link = os.link
        calls = 0

        def interrupted_link(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(errno.EIO, "simulated disk failure")
            return real_link(source, destination)

        with self.assertRaises(OSError):
            with ArtifactTransaction(outputs, [self.source]) as transaction:
                for output in outputs:
                    transaction.stage(output).write_bytes(b"owned")
                with patch("artifact_io.os.link", side_effect=interrupted_link):
                    transaction.commit()
        self.assertFalse(any(item.exists() for item in outputs))
        record = self.receipt(transaction)
        self.assertEqual(record["published_before_rollback"], [str(outputs[0])])
        self.assert_no_staging()

    def test_competing_creation_during_commit_is_preserved(self):
        outputs = [self.root / "first.png", self.root / "racing.png"]
        real_link = os.link

        def competing_link(source, destination):
            if Path(destination) == outputs[1]:
                outputs[1].write_bytes(b"another writer")
            return real_link(source, destination)

        with self.assertRaises(FileExistsError):
            with ArtifactTransaction(outputs, [self.source]) as transaction:
                for output in outputs:
                    transaction.stage(output).write_bytes(b"ours")
                with patch("artifact_io.os.link", side_effect=competing_link):
                    transaction.commit()
        self.assertFalse(outputs[0].exists())
        self.assertEqual(outputs[1].read_bytes(), b"another writer")
        self.receipt(transaction)

    def test_concurrent_in_place_change_is_not_removed_by_rollback(self):
        outputs = [self.root / "first.png", self.root / "second.png"]
        real_link = os.link

        def changing_link(source, destination):
            if Path(destination) == outputs[1]:
                outputs[0].write_bytes(b"user changed our first file")
                raise OSError(errno.EIO, "second install failed")
            return real_link(source, destination)

        with self.assertRaises(OSError):
            with ArtifactTransaction(outputs, [self.source]) as transaction:
                for output in outputs:
                    transaction.stage(output).write_bytes(b"ours")
                with patch("artifact_io.os.link", side_effect=changing_link):
                    transaction.commit()
        self.assertEqual(outputs[0].read_bytes(), b"user changed our first file")
        self.assertFalse(outputs[1].exists())
        record = self.receipt(transaction)
        self.assertTrue(any("concurrently changed" in item for item in record["cleanup_warnings"]))

    def test_concurrent_replacement_is_not_removed_by_rollback(self):
        outputs = [self.root / "first.png", self.root / "second.png"]
        real_link = os.link

        def replacing_link(source, destination):
            if Path(destination) == outputs[1]:
                outputs[0].unlink()
                outputs[0].write_bytes(b"replacement")
                raise OSError(errno.EIO, "second install failed")
            return real_link(source, destination)

        with self.assertRaises(OSError):
            with ArtifactTransaction(outputs, [self.source]) as transaction:
                for output in outputs:
                    transaction.stage(output).write_bytes(b"ours")
                with patch("artifact_io.os.link", side_effect=replacing_link):
                    transaction.commit()
        self.assertEqual(outputs[0].read_bytes(), b"replacement")
        self.assertFalse(outputs[1].exists())

    def test_no_link_filesystem_uses_exclusive_copy(self):
        output = self.root / "copy.png"
        with ArtifactTransaction([output], [self.source]) as transaction:
            transaction.stage(output).write_bytes(b"copied safely")
            with patch("artifact_io.os.link", side_effect=OSError(errno.ENOTSUP, "links unavailable")):
                transaction.commit()
        self.assertEqual(output.read_bytes(), b"copied safely")
        self.assert_no_staging()

    def test_exclusive_copy_does_not_overwrite_competing_file(self):
        output = self.root / "copy.png"

        def competing_link(source, destination):
            Path(destination).write_bytes(b"concurrent")
            raise OSError(errno.ENOTSUP, "links unavailable")

        with self.assertRaises(FileExistsError):
            with ArtifactTransaction([output], [self.source]) as transaction:
                transaction.stage(output).write_bytes(b"ours")
                with patch("artifact_io.os.link", side_effect=competing_link):
                    transaction.commit()
        self.assertEqual(output.read_bytes(), b"concurrent")

    def test_hard_linked_input_cannot_be_used_as_stage(self):
        output = self.root / "unsafe.png"
        with self.assertRaisesRegex(ArtifactError, "hard-linked to an input"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                os.link(self.source, transaction.stage(output))
                transaction.commit()
        self.assertFalse(output.exists())

    def test_nested_caller_generated_staging_files_cleaned_safely(self):
        output = self.root / "result.png"
        with ArtifactTransaction([output], [self.source]) as transaction:
            staged = transaction.stage(output)
            nested = staged.parent / "validation" / "images"
            nested.mkdir(parents=True)
            (nested / "proof.txt").write_text("temporary diagnostic")
            staged.write_bytes(b"final")
            transaction.commit()
        self.assert_no_staging()

    def test_replaced_staging_directory_is_preserved_instead_of_deleted(self):
        output = self.root / "result.png"
        with self.assertRaisesRegex(ArtifactError, "identity changed"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                staged = transaction.stage(output)
                staged.write_bytes(b"our staged data")
                private = staged.parent
                moved = private.with_name(private.name + "-moved")
                private.rename(moved)
                private.mkdir()
                foreign = private / "third-party.txt"
                foreign.write_bytes(b"keep this new directory")
                transaction.commit()
        self.assertFalse(output.exists())
        self.assertEqual(foreign.read_bytes(), b"keep this new directory")
        self.assertEqual((moved / output.name).read_bytes(), b"our staged data")
        record = self.receipt(transaction)
        self.assertTrue(any("identity changed" in item for item in record["cleanup_warnings"]))

    def test_read_only_input_directory_cannot_contain_failure_receipts(self):
        source_directory = self.root / "input-dir"
        source_directory.mkdir()
        with self.assertRaises(ArtifactError):
            ArtifactTransaction([self.root / "result.png"], [source_directory], failure_directory=source_directory / "failures")
        self.assertEqual(list(source_directory.iterdir()), [])

    def test_undeclared_stage_cannot_create_directories(self):
        output = self.root / "declared.png"
        with self.assertRaisesRegex(ArtifactError, "Undeclared output"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                transaction.stage(self.root / "unplanned" / "file.png")
        self.assertFalse((self.root / "unplanned").exists())
        self.receipt(transaction)

    def test_failure_before_first_stage_still_has_evidence(self):
        output = self.root / "result.png"
        with self.assertRaisesRegex(ValueError, "invalid parsed data"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                raise ValueError("invalid parsed data")
        self.assertFalse(output.exists())
        self.assertEqual(self.receipt(transaction)["error_type"], "ValueError")

    def test_unwritable_receipt_does_not_hide_original_error(self):
        output = self.root / "result.png"
        with self.assertRaisesRegex(OSError, "original failure") as caught:
            with ArtifactTransaction([output], [self.source]) as transaction:
                transaction.stage(output).write_bytes(b"temporary")
                # Fail only receipt persistence; cleanup must still run.
                with patch.object(transaction, "_mkdirs", side_effect=PermissionError("receipt denied")):
                    transaction._fail(OSError("original failure"))
                raise OSError("original failure")
        self.assertFalse(output.exists())
        self.assertIsNone(transaction.failure_receipt)
        self.assertEqual(transaction.failure_record["state"], "failed")
        self.assertTrue(any("receipt could not be saved" in item.lower()
                            for item in transaction.failure_record["cleanup_warnings"]))
        self.assert_no_staging()

    def test_partial_exclusive_copy_rolls_back_owned_bytes(self):
        output = self.root / "result.png"
        real_fdopen = os.fdopen

        class FailingWriter:
            def __init__(self, descriptor, mode):
                self.stream = real_fdopen(descriptor, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, block):
                self.stream.write(block[:3])
                self.stream.flush()
                raise OSError(errno.EIO, "partial copy failed")

        with self.assertRaisesRegex(OSError, "partial copy failed"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                transaction.stage(output).write_bytes(b"a full new artifact")
                with patch("artifact_io.os.link", side_effect=OSError(errno.ENOTSUP, "no links")), \
                        patch("artifact_io.os.fdopen", side_effect=FailingWriter):
                    transaction.commit()
        self.assertFalse(output.exists())
        self.receipt(transaction)
        self.assert_no_staging()

    def test_committed_set_survives_later_unrelated_exception(self):
        output = self.root / "result.png"
        with self.assertRaisesRegex(ValueError, "later operation"):
            with ArtifactTransaction([output], [self.source]) as transaction:
                transaction.stage(output).write_bytes(b"committed")
                transaction.commit()
                raise ValueError("later operation")
        self.assertEqual(output.read_bytes(), b"committed")
        self.assertIsNone(transaction.failure_receipt)


if __name__ == "__main__":
    unittest.main()
