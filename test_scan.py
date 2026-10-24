import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import scan


class ScannerTests(unittest.TestCase):
    def test_sitemap_nested_and_modified(self):
        documents = {
            'https://www.jw.org/es/sitemap.xml': '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.jw.org/es/part.xml</loc></sitemap></sitemapindex>',
            'https://www.jw.org/es/part.xml': '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://www.jw.org/es/artículo/</loc><lastmod>2026-10-22</lastmod></url></urlset>',
        }
        with patch.object(scan, 'fetch', side_effect=documents.__getitem__):
            items = scan.sitemap_items('https://www.jw.org/es/sitemap.xml')
        self.assertEqual(items[0]['modified'], '2026-10-22')
        self.assertIn('art%C3%ADculo', items[0]['url'])

    def test_media_categories_pagination_deduplication(self):
        def fetch(url):
            if '/root?' in url:
                return json.dumps({'category': {'subcategories': [{'key': 'child'}]}})
            if '/child?' in url:
                offset = 1 if 'offset=1' in url else 0
                return json.dumps({'category': {'media': [{'languageAgnosticNaturalKey': f'video{offset}', 'title': f'Video {offset}', 'type': 'video'}]}, 'pagination': {'totalCount': 2}})
            return json.dumps({'categories': [{'key': 'root'}, {'key': 'child'}]})
        with patch.object(scan, 'fetch', side_effect=fetch), patch.object(scan.time, 'sleep'):
            items = scan.media_items('https://example.test/categories/S')
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0]['url'], items[1]['url'])
        self.assertEqual(scan.canonical(items[0]['url']), items[0]['url'])

    def test_existing_publication_changes_do_not_notify(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.json'
            source = {'name': 'Map', 'url': 'https://www.jw.org/es/sitemap.xml', 'type': 'sitemap'}
            item = {'url': 'https://www.jw.org/es/test/', 'title': 'Test', 'published': None, 'modified': '2026-10-21'}
            with patch.object(scan, 'OUTPUT', output), patch.object(scan, 'SOURCES', [source]), patch.object(scan.time, 'sleep'), patch.object(scan, 'sitemap_items', return_value=[item]):
                scan.run()
                state = json.loads(output.read_text(encoding='utf-8'))
                state['pending_notifications'] = {'old': {'kind': 'Actualizado'}}
                output.write_text(json.dumps(state), encoding='utf-8')
                item['modified'] = '2026-10-22'
                item['title'] = 'Changed title'
                scan.run()
            state = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(state['items'][item['url']]['modified'], '2026-10-22')
            self.assertNotIn('updated_seen', state['items'][item['url']])
            self.assertEqual(state['sources']['Map']['new'], 0)
            self.assertEqual(state['pending_notifications'], {})


class NewPublicationTests(unittest.TestCase):
    def test_new_publication_survives_updates_and_repeat_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.json'
            source = {'name': 'Map', 'url': 'https://www.jw.org/es/sitemap.xml', 'type': 'sitemap'}
            old = {'url': 'https://www.jw.org/es/old/', 'title': 'Old', 'published': None, 'modified': '2026-10-21'}
            new = {'url': 'https://www.jw.org/es/new/', 'title': 'New', 'published': None, 'modified': '2026-10-22'}
            with patch.object(scan, 'OUTPUT', output), patch.object(scan, 'SOURCES', [source]), patch.object(scan.time, 'sleep'), patch.object(scan, 'sitemap_items') as items:
                items.return_value = [old]
                scan.run()
                self.assertEqual(json.loads(output.read_text())['pending_notifications'], {})
                items.return_value = [old, new]
                scan.run()
                state = json.loads(output.read_text())
                self.assertEqual(state['sources']['Map']['new'], 1)
                self.assertEqual(list(state['pending_notifications']), [new['url']])
                new['modified'] = '2026-10-23'
                scan.run()
                state = json.loads(output.read_text())
                self.assertEqual(state['sources']['Map']['new'], 0)
                self.assertEqual(state['pending_notifications'][new['url']]['kind'], 'Nuevo')


if __name__ == '__main__':
    unittest.main()
