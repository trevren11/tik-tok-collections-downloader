# Unraid Template for TikTok Collections Downloader

This directory contains the Unraid Community Applications template for TikTok Collections Downloader.

## For Users: Installing on Unraid

### Method 1: Via Community Applications (Recommended - Coming Soon)
Once approved, search for "TikTok Collections" in Community Applications and click Install.

### Method 2: Manual Template URL
1. In Unraid, go to **Docker** tab
2. Click **Add Container**
3. In the **Template repositories** field at the bottom, add:
   ```
   https://github.com/trevren11/tik-tok-collections-downloader
   ```
4. Click **Save**
5. Search for "TikTok Collections" in the template dropdown

### Method 3: Direct XML Import
1. Download [tiktok-collections.xml](tiktok-collections.xml)
2. Place it in `/boot/config/plugins/dockerMan/templates-user/`
3. Refresh the Docker page

## Configuration

### Required:
- **TIKTOK_SESSION_ID**: Your TikTok session cookie (see setup guide below)
- **Config Directory**: `/mnt/user/appdata/tiktok-collections`
- **Downloads Directory**: `/mnt/user/downloads/tiktok` (or your preferred location)
- **WebUI Port**: `2507` (or any available port)

### Optional:
- **SYNC_INTERVAL**: Check frequency in minutes (default: 120)
- **MAX_PARALLEL**: Parallel downloads (default: 3)
- **DOWNLOAD_LIMIT**: Limit per sync (empty = unlimited)
- **FULL_SYNC**: Full collection sync (default: false)

## Getting Your TikTok Session ID

1. Open TikTok in your browser and log in
2. Press **F12** to open DevTools
3. Go to **Application** → **Cookies** → `https://www.tiktok.com`
4. Find the `sessionid` cookie and copy its **Value**
5. Paste this value into the **TIKTOK_SESSION_ID** field in Unraid

⚠️ **Important**: Keep your session ID private. It provides access to your TikTok account.

## Accessing the Web Viewer

Once the container is running, access the viewer at:
```
http://[YOUR-UNRAID-IP]:[PORT]/viewer.html
```

Example: `http://192.168.1.100:8425/viewer.html`

## Troubleshooting

### Container won't start
- Check logs: Click the container icon → **Logs**
- Verify `TIKTOK_SESSION_ID` is set correctly
- Ensure directories have proper permissions

### No videos downloading
- Check if your session ID is still valid (may expire)
- Look for errors in container logs
- Verify you have saved/favorited videos in TikTok

### Web viewer not accessible
- Confirm port mapping is correct (default: 2507)
- Check firewall settings
- Ensure container is running

## Support

- **GitHub Issues**: https://github.com/trevren11/tik-tok-collections-downloader/issues
- **Unraid Forums**: [Coming soon - will be created upon CA submission]

## Template Specification

- **Template Version**: 2
- **Network Mode**: Bridge
- **Privileged**: No
- **WebUI**: Yes (port 8425 internal, 2507 default external)
- **Icon**: [icon.png](https://raw.githubusercontent.com/trevren11/tik-tok-collections-downloader/main/icon.png)

---

## For Developers: Contributing

See [UNRAID_PUBLISHING.md](UNRAID_PUBLISHING.md) for information about template maintenance and Community Applications submission process.
