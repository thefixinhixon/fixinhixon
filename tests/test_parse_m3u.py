import unittest
from parse_m3u import parse_m3u, parse_m3u_from_url
from unittest import mock
import io

class TestParseM3U(unittest.TestCase):
    def test_parses_sample_m3u_content(self):
        sample = (
            "#EXTM3U\n"
            "#EXTINF:-1 tvg-id=\"abc\" tvg-name=\"ABC\" tvg-logo=\"logo.png\" group-title=\"News\",ABC News\n"
            "http://example.com/stream1.m3u8\n"
            "#EXTINF:-1,No attributes\n"
            "http://example.com/stream2.ts"
        )
        result = parse_m3u(sample)
        expected = [
            {
                'name': 'ABC News',
                'tvg_id': 'abc',
                'tvg_name': 'ABC',
                'logo': 'logo.png',
                'group': 'News',
                'url': 'http://example.com/stream1.m3u8',
            },
            {
                'name': 'No attributes',
                'tvg_id': '',
                'tvg_name': '',
                'logo': '',
                'group': '',
                'url': 'http://example.com/stream2.ts',
            },
        ]
        self.assertEqual(result, expected)

    def test_parse_m3u_from_url(self):
        sample = "#EXTM3U\n#EXTINF:-1,Only One\nhttp://example.com/only.ts"

        class _MockResponse(io.BytesIO):
            def __init__(self, data: bytes):
                super().__init__(data)
                self.headers = {'content-type': 'text/plain; charset=utf-8'}

            def getheader(self, name, default=None):
                return self.headers.get(name, default)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.close()

        mock_resp = _MockResponse(sample.encode())
        with mock.patch('parse_m3u.urlopen', return_value=mock_resp):
            channels = parse_m3u_from_url('http://fake.test/playlist.m3u')
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]['name'], 'Only One')

if __name__ == '__main__':
    unittest.main()
