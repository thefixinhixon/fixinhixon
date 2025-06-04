(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.parseM3U = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {
    function parseM3U(m3uText) {
        console.log("Starting M3U Parse...");
        const lines = m3uText.split('\n');
        const parsedChannels = [];
        let currentChannel = null;
        if (!lines[0] || !lines[0].trim().startsWith('#EXTM3U')) {
            console.warn("M3U file does not start with #EXTM3U.");
        }
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            if (line.startsWith('#EXTINF:')) {
                if (currentChannel && !currentChannel.url) {
                    console.warn(`Discarding previous channel "${currentChannel.name}" missing URL.`);
                }
                currentChannel = { name: '', tvgId: '', tvgName: '', logo: '', group: '', url: '', rawExtInf: line };
                const infoLine = line.substring(8).trim();
                const commaIndex = infoLine.lastIndexOf(',');
                if (commaIndex === -1) {
                    console.warn(`Skipping malformed #EXTINF (no comma): ${line}`);
                    currentChannel = null;
                    continue;
                }
                currentChannel.name = infoLine.substring(commaIndex + 1).trim();
                const attributesPart = infoLine.substring(0, commaIndex).trim();
                const attributeRegex = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
                let match;
                while ((match = attributeRegex.exec(attributesPart)) !== null) {
                    const key = match[1].toLowerCase();
                    const value = match[2];
                    switch (key) {
                        case 'tvg-id':
                            currentChannel.tvgId = value;
                            break;
                        case 'tvg-name':
                            currentChannel.tvgName = value;
                            break;
                        case 'tvg-logo':
                            currentChannel.logo = value;
                            break;
                        case 'group-title':
                            currentChannel.group = value;
                            break;
                    }
                }
                if ((!currentChannel.name || currentChannel.name.match(/^Channel\s*\d+$/i)) && currentChannel.tvgName) {
                    currentChannel.name = currentChannel.tvgName;
                }
                if (!currentChannel.name) {
                    currentChannel.name = `Unnamed Channel ${parsedChannels.length + 1}`;
                }
            } else if (currentChannel && line && !line.startsWith('#')) {
                currentChannel.url = line;
                delete currentChannel.rawExtInf;
                parsedChannels.push(currentChannel);
                currentChannel = null;
            } else if (line && !line.startsWith('#') && !currentChannel) {
                console.warn(`Found URL "${line}" without #EXTINF. Creating basic entry.`);
                parsedChannels.push({ name: `Channel ${parsedChannels.length + 1}`, url: line, tvgId: '', tvgName: '', logo: '', group: '' });
            } else if (line.startsWith('#') && line !== '#EXTM3U' && currentChannel && !currentChannel.url) {
                console.warn(`Found directive "${line}" before URL for "${currentChannel.name}". Discarding.`);
                currentChannel = null;
            }
        }
        if (currentChannel && !currentChannel.url) {
            console.warn(`Last channel "${currentChannel.rawExtInf}" missing URL at EOF.`);
        }
        console.log(`M3U Parsing complete. Parsed ${parsedChannels.length} channels.`);
        if (parsedChannels.length === 0 && lines.length > 1) {
            console.warn("Parsed 0 channels from non-empty M3U.");
        }
        return parsedChannels;
    }
    return parseM3U;
}));
