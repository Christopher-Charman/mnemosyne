"""Temporary synthetic notes only; never reads a real Obsidian vault."""
import os
import tempfile
import pathlib
import hashlib
import unittest
from unittest.mock import patch
from mnemosyne.integrations.owned_architecture_bridge import AdmissionError
from mnemosyne.integrations.owned_obsidian_note_reader import read_vault_note

class NoteReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="mnemo-note-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        os.chmod(self.root,0o700)
        self.dir=self.root/"Memory"
        self.dir.mkdir(mode=0o700)
        self.file=self.dir/"Synthetic.md"
        self.file.write_bytes(b"Synthetic reviewed fact")
        os.chmod(self.file,0o600)
        self.ref="obsidian:Memory/Synthetic.md"
    def read(self,**changes):
        return read_vault_note(changes.get("ref",self.ref),
            vault_root=changes.get("vault_root",self.root),
            owner_uid=changes.get("owner_uid",os.getuid()))
    def test_valid_bytes_and_hash_no_write(self):
        original=self.file.read_bytes()
        snap=self.read()
        self.assertEqual(snap.raw,original)
        self.assertEqual(snap.version,"sha256:"+hashlib.sha256(original).hexdigest())
        self.assertEqual(self.file.read_bytes(),original)
    def test_note_paths_with_internal_spaces(self):
        directory=self.root/"Memory Notes"
        directory.mkdir(mode=0o700)
        note=directory/"Design Notes.md"
        note.write_bytes(b"synthetic note")
        os.chmod(note,0o600)
        response=self.read(ref="obsidian:Memory Notes/Design Notes.md")
        self.assertEqual(response.raw,b"synthetic note")

    def test_unsupported_platform_fails_closed_without_open(self):
        with patch("mnemosyne.integrations.owned_obsidian_note_reader._secure_platform",return_value=False):
            with self.assertRaisesRegex(AdmissionError,"POSIX"):
                self.read()

    def test_wrong_owner_fails(self):
        with self.assertRaises(AdmissionError):self.read(owner_uid=os.getuid()+1)
    def test_traversal_and_hidden_denied(self):
        refs=("obsidian:../A.md","obsidian:Memory/../A.md",
              "obsidian:Memory//A.md","obsidian:Memory/.Secret.md",
              "obsidian:/absolute.md","library:/Memory/Synthetic.md",
              "obsidian:Memory/Synthetic.txt")
        for ref in refs:
            with self.subTest(ref=ref),self.assertRaises(AdmissionError):
                self.read(ref=ref)
    def test_symlink_parent_and_file_denied(self):
        (self.root/"Linked").symlink_to(self.dir,target_is_directory=True)
        (self.dir/"Link.md").symlink_to(self.file)
        for ref in ("obsidian:Linked/Synthetic.md","obsidian:Memory/Link.md"):
            with self.subTest(ref=ref),self.assertRaises(AdmissionError):
                self.read(ref=ref)
        with self.assertRaises(AdmissionError):self.read(vault_root=self.root/"Linked")
    def test_untrusted_permissions_denied(self):
        os.chmod(self.dir,0o777)
        with self.assertRaises(AdmissionError):self.read()
        os.chmod(self.dir,0o700)
        os.chmod(self.file,0o666)
        with self.assertRaises(AdmissionError):self.read()
    def test_empty_and_oversize_denied(self):
        for data in (b"",b"x"*65537):
            self.file.write_bytes(data)
            with self.assertRaises(AdmissionError):self.read()
    def test_fifo_and_hardlink_denied(self):
        self.file.unlink()
        os.mkfifo(self.file,0o600)
        with self.assertRaises(AdmissionError):self.read()
        self.file.unlink()
        self.file.write_bytes(b"synthetic")
        (self.dir/"Hardlink.md").hardlink_to(self.file)
        with self.assertRaises(AdmissionError):self.read()
    def test_encoding_denied(self):
        self.file.write_bytes(bytes([255,254]))
        with self.assertRaises(AdmissionError):self.read()
    def test_immutable_digest_tracks_revision(self):
        old=self.read().version
        self.file.write_bytes(b"changed")
        self.assertNotEqual(old,self.read().version)

if __name__=="__main__":unittest.main()
