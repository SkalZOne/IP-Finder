"""Проверки интерактивной передачи аргументов без сетевых запросов."""

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MenuTests(unittest.TestCase):
    def test_zero_is_not_passed_and_spaces_are_preserved(self) -> None:
        result = subprocess.run(
            ["bash", "-c", "source scripts/lib/common.bash; "
             "prompt_script_args country; printf '<%s>\\n' \"${PROMPTED_ARGS[@]}\""],
            input="DE\n--out\nout/my file.txt\n0\n",
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=True,
        )
        self.assertTrue(result.stdout.endswith("<DE>\n<--out>\n<out/my file.txt>\n"))

    def test_menu_prompts_before_each_search(self) -> None:
        result = subprocess.run(
            ["./init.sh", "3", "4", "5"],
            input="--help\n0\n--help\n0\n--help\n0\n",
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=True,
        )
        self.assertEqual(result.stdout.count("usage: python -m src.main"), 3)
        self.assertEqual(result.stdout.count("Запускаем "), 3)

    def test_eof_does_not_start_search(self) -> None:
        result = subprocess.run(
            ["./init.sh", "3"],
            input="",
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Запускаем ", result.stdout)


if __name__ == "__main__":
    unittest.main()
