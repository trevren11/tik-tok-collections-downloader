# Unraid Installation

## Option 1: Private Template (Recommended for Personal Use)

1. **Copy the config.json template to your Unraid server:**
   ```bash
   mkdir -p /mnt/user/appdata/tiktok-collections
   ```

2. **Create config.json on Unraid:**
   ```bash
   nano /mnt/user/appdata/tiktok-collections/config.json
   ```

   Add your TikTok session ID:
   ```json
   {
     "sessionid": "YOUR_SESSIONID_HERE",
     "download_dir": "/app/downloads"
   }
   ```

3. **Copy the XML template to Unraid:**
   - SSH into your Unraid server
   - Create the private templates directory:
     ```bash
     mkdir -p /boot/config/plugins/community.applications/private
     ```
   - Copy `tiktok-collections.xml` to that directory

4. **Install via Community Applications:**
   - Go to Apps tab in Unraid
   - Search for "tiktok-collections"
   - Click Install and configure paths

## Option 2: Community Applications (Public)

To publish publicly:

1. **Push Docker image to Docker Hub:**
   ```bash
   docker login
   docker build -t yourusername/tiktok-collections:latest .
   docker push yourusername/tiktok-collections:latest
   ```

2. **Create a template repository on GitHub:**
   - Create repo named `docker-templates` (or similar)
   - Add the XML file to it
   - Structure: `yourusername/docker-templates/tiktok-collections.xml`

3. **Add your template repo to Unraid:**
   - Docker tab → Add Container → Template Repositories
   - Add: `https://github.com/yourusername/docker-templates`

4. **For official CA inclusion:**
   - Fork [Community Applications](https://github.com/Squidly271/community.applications)
   - Add your template
   - Submit PR

## Configuration

| Setting | Description |
|---------|-------------|
| Config Directory | Where config.json is stored (contains session ID) |
| Downloads Directory | Where videos are saved |
| TikTok Session ID | Your `sessionid` cookie from TikTok (alternative to config.json) |
| Sync Interval | Minutes between sync checks (default: 120) |
| Download Limit | Limit downloads per sync cycle (e.g., set to 5 for testing, leave empty for unlimited) |
| Enable Viewer | Set to `true` to enable the web viewer for browsing downloaded videos |
| Viewer Port | Port for the web viewer (default: 8425). Change this if port 8425 is already in use |
| Viewer Web Port | The host port mapping - should match Viewer Port value |

## Getting Your TikTok Session ID

1. Open TikTok in your browser and log in
2. Open DevTools (F12) → Application → Cookies
3. Find `sessionid` cookie value
4. Either:
   - Put it in config.json, OR
   - Enter it in the Unraid template settings
