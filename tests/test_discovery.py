"""Public crawler routes; the app uses only a disposable in-memory test database."""
import os
import unittest
import xml.etree.ElementTree as ET
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_SALT'] = 'discovery-test-only'
from app import app

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_robots_advertises_the_public_sitemap(self):
        response = self.client.get('/robots.txt')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/plain')
        self.assertIn('Sitemap: https://managersthatsuck.com/sitemap.xml', response.text)
        self.assertIn('Allow: /', response.text)
        with self.client.head('/robots.txt') as head:
            self.assertEqual(head.status_code, 200)

    def test_sitemap_contains_real_canonical_pages_only(self):
        response = self.client.get('/sitemap.xml')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/xml')
        root = ET.fromstring(response.data)
        urls = [x.text for x in root.findall('{*}url/{*}loc')]
        self.assertEqual(urls, ['https://managersthatsuck.com/'])
        with self.client.head('/sitemap.xml') as head:
            self.assertEqual(head.status_code, 200)

    def test_existing_homepage_and_missing_paths_are_unchanged(self):
        response = self.client.get('/')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn('https://crossformdev.com/about.html', response.text)
        self.assertIn('rel="canonical" href="https://managersthatsuck.com/"', response.text)
        self.assertEqual(self.client.get('/missing-discovery-file.xml').status_code, 404)

if __name__ == '__main__':
    unittest.main()
