import re
from typing import List, Dict, Optional
from urllib.request import urlopen
from urllib.error import URLError
import argparse
import sys

def parse_m3u(m3u_text: str) -> List[Dict[str, str]]:
    """Parse an M3U playlist string into channel dictionaries.

    Parameters
    ----------
    m3u_text : str
        Raw text of the M3U playlist.

    Returns
    -------
    List[Dict[str, str]]
        A list of channel dictionaries containing name, tvg_id,
        tvg_name, logo, group, and url keys.
    """
    lines = m3u_text.splitlines()
    parsed_channels: List[Dict[str, str]] = []
    current_channel: Optional[Dict[str, str]] = None
    attribute_regex = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')

    if not lines or not lines[0].strip().startswith('#EXTM3U'):
        # Not strictly an error but warn via print for parity with JS version
        print('Warning: M3U file does not start with #EXTM3U.')

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith('#EXTINF:'):
            if current_channel and not current_channel.get('url'):
                print(f"Warning: Discarding previous channel \"{current_channel.get('name')}\" missing URL.")
            current_channel = {
                'name': '',
                'tvg_id': '',
                'tvg_name': '',
                'logo': '',
                'group': '',
                'url': '',
                'raw_extinf': line,
            }
            info_line = line[8:].strip()
            comma_index = info_line.rfind(',')
            if comma_index == -1:
                print(f"Warning: Skipping malformed #EXTINF (no comma): {line}")
                current_channel = None
                continue
            current_channel['name'] = info_line[comma_index + 1:].strip()
            attributes_part = info_line[:comma_index].strip()
            for match in attribute_regex.finditer(attributes_part):
                key = match.group(1).lower()
                value = match.group(2)
                if key == 'tvg-id':
                    current_channel['tvg_id'] = value
                elif key == 'tvg-name':
                    current_channel['tvg_name'] = value
                elif key == 'tvg-logo':
                    current_channel['logo'] = value
                elif key == 'group-title':
                    current_channel['group'] = value
            if ((not current_channel['name'] or re.match(r'^Channel\s*\d+$', current_channel['name'], re.I))
                    and current_channel['tvg_name']):
                current_channel['name'] = current_channel['tvg_name']
            if not current_channel['name']:
                current_channel['name'] = f"Unnamed Channel {len(parsed_channels) + 1}"

        elif current_channel and line and not line.startswith('#'):
            current_channel['url'] = line
            current_channel.pop('raw_extinf', None)
            parsed_channels.append(current_channel)
            current_channel = None

        elif line and not line.startswith('#') and not current_channel:
            print(f"Warning: Found URL \"{line}\" without #EXTINF. Creating basic entry.")
            parsed_channels.append({
                'name': f"Channel {len(parsed_channels) + 1}",
                'tvg_id': '',
                'tvg_name': '',
                'logo': '',
                'group': '',
                'url': line,
            })

        elif line.startswith('#') and line != '#EXTM3U' and current_channel and not current_channel.get('url'):
            print(f"Warning: Found directive \"{line}\" before URL for \"{current_channel['name']}\". Discarding.")
            current_channel = None

    if current_channel and not current_channel.get('url'):
        print(f"Warning: Last channel \"{current_channel['raw_extinf']}\" missing URL at EOF.")

    if not parsed_channels and len(lines) > 1:
        print('Warning: Parsed 0 channels from non-empty M3U.')

    return parsed_channels


def parse_m3u_from_url(url: str) -> List[Dict[str, str]]:
    """Fetch an M3U playlist from a URL and parse it."""
    try:
        with urlopen(url) as response:
            content_type = response.headers.get('content-type', '')
            match = re.search(r'charset=([^;]+)', content_type, re.I)
            charset = match.group(1) if match else 'utf-8'
            text = response.read().decode(charset, errors='replace')
    except URLError as exc:
        raise RuntimeError(f'Failed to fetch {url}: {exc.reason}') from exc
    return parse_m3u(text)


def _main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description='Parse an M3U playlist')
    parser.add_argument('source', help='Path or URL to M3U file')
    args = parser.parse_args(argv)

    if args.source.startswith(('http://', 'https://')):
        channels = parse_m3u_from_url(args.source)
    else:
        with open(args.source, 'r', encoding='utf-8', errors='replace') as f:
            channels = parse_m3u(f.read())

    for ch in channels:
        print(ch)
    print(f'Parsed {len(channels)} channels')
    return 0


if __name__ == '__main__':
    raise SystemExit(_main(sys.argv[1:]))
