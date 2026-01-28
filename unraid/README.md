# Unraid Community Applications Template

This folder contains the template for Unraid Community Applications.

## Files

- `tiktok-collections-downloader.xml` - CA template definition
- `icon.png` - Container icon (256x256 PNG recommended)

## Adding to Community Apps

To make this container discoverable in Unraid's Community Apps:

1. Fork the [Community Applications repository](https://github.com/Squidly271/community.applications)
2. Add `tiktok-collections-downloader.xml` to the appropriate folder
3. Submit a pull request

## Manual Installation (Alternative)

If not yet in Community Apps, users can add the template URL directly:

1. In Unraid, go to **Docker** tab
2. Click **Add Container**
3. Click **Template repositories** at the bottom
4. Add: `https://raw.githubusercontent.com/trevren11/tik-tok-collections-downloader/main/unraid/tiktok-collections-downloader.xml`
5. Click **Save**
6. The container will now appear in the template dropdown

## Icon

Add a 256x256 PNG icon named `icon.png` to this folder. The template references it from GitHub raw URL.
