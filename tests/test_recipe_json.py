import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ai_recipe', ROOT / 'app/ai_recipe.py')
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)


class RecipeJsonTests(unittest.TestCase):
    def setUp(self):
        self.recipe = json.loads((ROOT / 'skills/table-and-tale-recipe-card-archivist/example-import.json').read_text(encoding='utf-8-sig'))
        self.recipe['notes'] = 'Source says "Dash Lemon Juice".\n\nKeep commas, } and , ] and https://example.com and /* prose */ intact.'
        self.text = json.dumps(self.recipe, ensure_ascii=False, indent=2)

    def check_recipe(self, text):
        draft, warnings = ai.parse_ai_json(text)
        self.assertEqual(draft['notes'], self.recipe['notes'])
        self.assertEqual(len(draft['ingredients']), len(self.recipe['ingredients']))
        self.assertEqual(len(draft['steps']), len(self.recipe['steps']))
        return warnings

    def test_valid_escaped_quotes_and_paragraphs(self):
        self.check_recipe(self.text)

    def test_code_block_and_bom(self):
        self.check_recipe('\ufeff```json\n' + self.text + '\n```')

    def test_serialized_json_string(self):
        self.check_recipe(json.dumps(self.text))

    def test_comments_and_trailing_commas_preserve_prose(self):
        warnings = self.check_recipe('// Recipe\n' + self.text[:-1] + ',\n}')
        self.assertTrue(any('Removed comments or trailing commas' in w for w in warnings))

    def test_unescaped_quotes_rejected_with_copy_guidance(self):
        broken = self.text.replace(r'\"Dash Lemon Juice\"', '"Dash Lemon Juice"')
        with self.assertRaisesRegex(ValueError, 'line .*column .*Copy button'):
            ai.parse_ai_json(broken)

    def test_actual_line_break_in_string_rejected(self):
        with self.assertRaisesRegex(ValueError, 'paragraph breaks'):
            ai.parse_ai_json(self.text.replace(r'\n\n', '\n\n'))

    def test_missing_comma_not_guessed(self):
        with self.assertRaises(ValueError):
            ai.parse_ai_json(self.text.replace(',\n', '\n', 1))

    def test_multiple_recipes_rejected(self):
        with self.assertRaisesRegex(ValueError, 'one recipe at a time'):
            ai.parse_ai_json(json.dumps([self.recipe, self.recipe]))

    def test_one_item_array_and_wrapper(self):
        self.check_recipe(json.dumps([self.recipe]))
        self.check_recipe(json.dumps({'recipe': self.recipe}))

    def test_all_skill_examples_parse(self):
        for path in (ROOT / 'skills').rglob('example-import.json'):
            with self.subTest(path=path):
                ai.parse_ai_json(path.read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
