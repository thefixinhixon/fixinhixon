# FixInHixon IPTV

This repository contains a simple IPTV player web app. A new Python module
`parse_m3u.py` has been added to parse M3U playlists in Python. Unit tests for
this parser are located in `tests/test_parse_m3u.py` and can be run with
`python -m unittest`.

## Using the Python parser

Run `parse_m3u.py` with a file path or URL to output parsed channel
information:

```bash
python parse_m3u.py http://example.com/my.m3u
```
