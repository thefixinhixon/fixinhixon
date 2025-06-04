const parseM3U = require('../parseM3U');

describe('parseM3U', () => {
  test('parses sample M3U content', () => {
    const sample = `#EXTM3U\n#EXTINF:-1 tvg-id="abc" tvg-name="ABC" tvg-logo="logo.png" group-title="News",ABC News\nhttp://example.com/stream1.m3u8\n#EXTINF:-1,No attributes\nhttp://example.com/stream2.ts`;
    const result = parseM3U(sample);
    expect(result).toEqual([
      {
        name: 'ABC News',
        tvgId: 'abc',
        tvgName: 'ABC',
        logo: 'logo.png',
        group: 'News',
        url: 'http://example.com/stream1.m3u8'
      },
      {
        name: 'No attributes',
        tvgId: '',
        tvgName: '',
        logo: '',
        group: '',
        url: 'http://example.com/stream2.ts'
      }
    ]);
  });
});
