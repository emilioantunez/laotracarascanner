import json
from datetime import datetime, timezone
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
            new = {'url': 'https://www.jw.org/es/new/', 'title': 'New', 'published': datetime.now(timezone.utc).isoformat(), 'modified': '2026-10-22'}
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


    def test_old_modified_and_undated_items_do_not_notify(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.json'
            source = {'name': 'Feed', 'url': 'https://www.jw.org/es/lo-nuevo/rss/feed.xml', 'type': 'rss'}
            old = {'url': 'https://www.jw.org/es/old/', 'title': 'Old edited', 'published': '2020-01-01T00:00:00Z'}
            undated = {'url': 'https://www.jw.org/es/unknown/', 'title': 'Unknown date', 'published': None}
            recent = {'url': 'https://www.jw.org/es/recent/', 'title': 'Genuine new', 'published': datetime.now(timezone.utc).isoformat()}
            with patch.object(scan, 'OUTPUT', output), patch.object(scan, 'SOURCES', [source]), patch.object(scan.time, 'sleep'), patch.object(scan, 'fetch', return_value='<rss/>'), patch.object(scan, 'rss_items') as items:
                items.return_value = [old]
                scan.run()
                items.return_value = [old, undated, recent]
                scan.run()
                state = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(state['sources']['Feed']['new'], 1)
                self.assertEqual(list(state['pending_notifications']), [recent['url']])
                old['title'] = 'Old edited again'
                items.return_value = [old, undated, recent]
                scan.run()
                state = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(state['sources']['Feed']['new'], 0)
                self.assertEqual(list(state['pending_notifications']), [recent['url']])

    def test_recent_date_parsing_and_old_dates(self):
        recent = datetime.now(timezone.utc).isoformat()
        checked = scan.now()
        self.assertTrue(scan.is_recent_publication(recent, checked))
        self.assertFalse(scan.is_recent_publication('2018-01-01', checked))
        self.assertFalse(scan.is_recent_publication(None, checked))
        self.assertFalse(scan.is_recent_publication('not a date', checked))


    def test_undated_novedad_requires_second_scan_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.json'
            source = {'name': 'Novedades', 'url': 'https://www.jw.org/es/lo-nuevo/', 'type': 'html', 'prefix': '/es/'}
            old = {'url': 'https://www.jw.org/es/biblioteca/old/article/', 'title': 'Old item', 'published': None}
            new = {'url': 'https://www.jw.org/es/biblioteca/new/article/', 'title': 'New item', 'published': None}
            with patch.object(scan, 'OUTPUT', output), patch.object(scan, 'SOURCES', [source]), patch.object(scan.time, 'sleep'), patch.object(scan, 'fetch', return_value='<main/>'), patch.object(scan, 'html_items') as items:
                items.return_value = [old]
                scan.run()
                items.return_value = [old, new]
                scan.run()
                self.assertEqual(json.loads(output.read_text())['pending_notifications'], {})
                scan.run()
                state = json.loads(output.read_text())
                self.assertEqual(list(state['pending_notifications']), [new['url']])
                self.assertEqual(state['pending_notifications'][new['url']]['verified_by'], 'novedades')
                scan.run()
                self.assertEqual(json.loads(output.read_text())['sources']['Novedades']['new'], 0)

    def test_questions_html_without_main_fallback(self):
        source = {'name': 'Preguntas sobre la Biblia', 'url': 'https://www.jw.org/es/enseñanzas-bíblicas/preguntas/', 'prefix': '/es/enseñanzas-bíblicas/preguntas/'}
        html = '<html><body><a href="/es/enseñanzas-bíblicas/preguntas/que-es-la-biblia/">¿Qué es la Biblia?</a></body></html>'
        items = scan.html_items(html, source)
        self.assertEqual(len(items), 1)


if __name__ == '__main__':
    unittest.main()
