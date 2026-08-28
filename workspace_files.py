"""Safe, workspace-scoped file operations for ADA's function tools."""

from pathlib import Path


class WorkspaceFiles:
    """Perform file operations without allowing paths outside one workspace."""

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, user_path, *, allow_root=False):
        if not isinstance(user_path, str) or not user_path.strip():
            raise ValueError("A non-empty relative path is required.")

        candidate = (self.root / user_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Path must stay inside the ADA workspace.")
        if candidate == self.root and not allow_root:
            raise ValueError("A file or folder name is required.")
        return candidate

    def display_path(self, path):
        path = Path(path).resolve()
        if path == self.root:
            return "."
        return path.relative_to(self.root).as_posix()

    def create_folder(self, folder_path):
        path = self._resolve(folder_path)
        if path.exists():
            return {
                "status": "skipped",
                "message": f"The folder '{self.display_path(path)}' already exists.",
            }
        path.mkdir(parents=True)
        return {
            "status": "success",
            "message": f"Created the folder '{self.display_path(path)}'.",
        }

    def create_file(self, file_path, content):
        path = self._resolve(file_path)
        if path.exists():
            return {
                "status": "skipped",
                "message": f"The file '{self.display_path(path)}' already exists.",
            }
        if not isinstance(content, str):
            raise ValueError("File content must be text.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "status": "success",
            "message": f"Created the file '{self.display_path(path)}'.",
        }

    def edit_file(self, file_path, content):
        path = self._resolve(file_path)
        if not path.is_file():
            return {
                "status": "error",
                "message": f"The file '{self.display_path(path)}' does not exist.",
            }
        if not isinstance(content, str):
            raise ValueError("File content must be text.")
        with path.open("a", encoding="utf-8") as file:
            file.write(f"\n{content}")
        return {
            "status": "success",
            "message": f"Appended content to '{self.display_path(path)}'.",
        }

    def list_files(self, directory_path=None):
        path = self._resolve(directory_path or ".", allow_root=True)
        if not path.is_dir():
            return {
                "status": "error",
                "message": f"The path '{self.display_path(path)}' is not a directory.",
            }
        files = sorted(item.name for item in path.iterdir())
        display_path = self.display_path(path)
        return {
            "status": "success",
            "message": f"Found {len(files)} items in '{display_path}'.",
            "files": files,
            "directory_path": display_path,
        }

    def read_file(self, file_path):
        path = self._resolve(file_path)
        if not path.is_file():
            return {
                "status": "error",
                "message": f"The file '{self.display_path(path)}' does not exist.",
            }
        return {
            "status": "success",
            "message": f"Read the file '{self.display_path(path)}'.",
            "content": path.read_text(encoding="utf-8"),
        }
