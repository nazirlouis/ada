import tempfile
import unittest
from pathlib import Path

from workspace_files import WorkspaceFiles


class WorkspaceFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceFiles(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_read_edit_and_list_file(self):
        created = self.workspace.create_file("notes/today.txt", "hello")
        edited = self.workspace.edit_file("notes/today.txt", "world")
        read = self.workspace.read_file("notes/today.txt")
        listed = self.workspace.list_files("notes")

        self.assertEqual(created["status"], "success")
        self.assertEqual(edited["status"], "success")
        self.assertEqual(read["content"], "hello\nworld")
        self.assertEqual(listed["files"], ["today.txt"])

    def test_rejects_parent_directory_escape(self):
        with self.assertRaisesRegex(ValueError, "inside the ADA workspace"):
            self.workspace.read_file("../secret.txt")

    def test_rejects_absolute_path_escape(self):
        outside_path = str(Path(self.temp_dir.name).parent / "secret.txt")
        with self.assertRaisesRegex(ValueError, "inside the ADA workspace"):
            self.workspace.create_file(outside_path, "nope")

    def test_rejects_symlink_escape(self):
        workspace_path = Path(self.temp_dir.name)
        outside_dir = workspace_path.parent
        (workspace_path / "outside").symlink_to(outside_dir, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "inside the ADA workspace"):
            self.workspace.read_file("outside/secret.txt")

    def test_lists_workspace_root_by_default(self):
        self.workspace.create_folder("projects")

        listed = self.workspace.list_files()

        self.assertEqual(listed["directory_path"], ".")
        self.assertEqual(listed["files"], ["projects"])


if __name__ == "__main__":
    unittest.main()
