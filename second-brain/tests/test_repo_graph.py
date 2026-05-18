"""Ref và khóa repo cho multi-repo per project."""

from __future__ import annotations

import unittest

from second_brain.repo_graph import (
    codefile_ref,
    codefunction_ref,
    git_repository_ref,
    normalize_github_repo_key,
    normalize_local_repo_key,
)


class TestRepoGraph(unittest.TestCase):
    def test_normalize_github_repo_key(self) -> None:
        self.assertEqual(normalize_github_repo_key("Org/My-Repo"), "org/my-repo")

    def test_normalize_local_repo_key_stable(self) -> None:
        a = normalize_local_repo_key("/workspace/mia")
        b = normalize_local_repo_key("/workspace/mia")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("local:"))

    def test_refs_include_repo_key(self) -> None:
        rk = "org/api"
        self.assertIn("org_api", git_repository_ref(2, rk))
        cf = codefile_ref(2, rk, "src/main.py")
        self.assertTrue(cf.startswith("p2:codefile:"))
        self.assertIn("org_api", cf)
        self.assertIn("src_main.py", cf)
        fn = codefunction_ref(2, rk, "src/main.py", "handler")
        self.assertIn("handler", fn)


if __name__ == "__main__":
    unittest.main()
