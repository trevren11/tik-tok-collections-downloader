# Publishing to Unraid Community Applications

This guide explains how to publish and maintain the TikTok Collections Downloader template in Unraid Community Applications.

## Prerequisites

Before submitting to Community Applications, ensure:

- [x] Docker image is published to Docker Hub: `trevren11/tiktok-collections-downloader`
- [x] XML template is valid and tested on Unraid
- [x] Icon is publicly accessible on GitHub
- [x] README documentation is complete
- [x] GitHub repository has proper LICENSE file
- [ ] Support thread created on Unraid Forums
- [ ] Template tested by multiple users

## Submission Process

### Step 1: Create Support Thread

1. Go to [Unraid Forums - Docker Containers](https://forums.unraid.net/forum/48-docker-containers/)
2. Create new topic: **"[Support] TikTok Collections Downloader"**
3. Include:
   - Overview of what the container does
   - Installation instructions
   - Configuration guide
   - Known issues
   - Changelog
   - Link to GitHub repository

**Template for support thread:**
```
[Support] TikTok Collections Downloader - Automated TikTok Collection Sync

Overview:
Automatically monitor and download your TikTok saved videos and collections
to local storage with organized folder structure. Includes web viewer interface.

GitHub: https://github.com/trevren11/tik-tok-collections-downloader
Docker Hub: https://hub.docker.com/r/trevren11/tiktok-collections-downloader

Installation:
[Include installation instructions from unraid/README.md]

Configuration:
[Include configuration details]

Known Issues:
- TikTok session IDs may expire periodically (re-login required)

Changelog:
[Include version history]
```

### Step 2: Submit to Community Applications

#### Option A: Official Submission (Recommended for wide distribution)

1. Visit the [Community Applications Submission Form](https://forums.unraid.net/forum/48-docker-containers/)
2. Fill out the submission form with:
   - **Application Name**: TikTok Collections Downloader
   - **Category**: MediaApp:Video
   - **Template URL**: `https://raw.githubusercontent.com/trevren11/tik-tok-collections-downloader/main/unraid/tiktok-collections.xml`
   - **Support Thread**: [Link to your forum thread]
   - **Icon URL**: `https://raw.githubusercontent.com/trevren11/tik-tok-collections-downloader/main/icon.png`
   - **Description**: Brief description
   - **Repository**: `trevren11/tiktok-collections-downloader`

#### Option B: Template Request (Community-driven)

1. Go to https://github.com/selfhosters/unRAID-CA-templates
2. Create a new issue using "CA Template Request" template
3. Provide:
   - Docker image: `trevren11/tiktok-collections-downloader:latest`
   - Template XML: Link to the XML in this repo
   - Support thread URL
   - Brief description

#### Option C: Personal Template Repository (Immediate availability)

Users can add your repository directly as a template source:

1. Your template XML is hosted at:
   ```
   https://raw.githubusercontent.com/trevren11/tik-tok-collections-downloader/main/unraid/tiktok-collections.xml
   ```

2. Users add this URL in Unraid:
   - **Docker** tab → **Add Container**
   - Scroll to bottom → **Template repositories**
   - Add: `https://github.com/trevren11/tik-tok-collections-downloader`

## Template Maintenance

### Updating the Template

When making changes to the template:

1. **Test locally first**:
   ```bash
   # Copy to Unraid test system
   scp unraid/tiktok-collections.xml root@unraid-ip:/boot/config/plugins/dockerMan/templates-user/
   ```

2. **Validate XML syntax**:
   ```bash
   xmllint --noout unraid/tiktok-collections.xml
   ```

3. **Update version/changelog in XML if needed**

4. **Commit and push to GitHub**:
   ```bash
   git add unraid/tiktok-collections.xml
   git commit -m "Update Unraid template: [description of changes]"
   git push
   ```

5. **Notify in support thread** if changes are significant

### Docker Image Updates

When publishing new Docker images:

1. **Build and tag**:
   ```bash
   docker build -t trevren11/tiktok-collections-downloader:latest .
   docker tag trevren11/tiktok-collections-downloader:latest trevren11/tiktok-collections-downloader:v1.x.x
   ```

2. **Push to Docker Hub**:
   ```bash
   docker push trevren11/tiktok-collections-downloader:latest
   docker push trevren11/tiktok-collections-downloader:v1.x.x
   ```

3. **Update support thread** with changelog

4. **Community Applications auto-syncs** within 24-48 hours

## Template Requirements Checklist

Ensure your template meets Unraid standards:

- [x] **Name**: Descriptive and unique
- [x] **Repository**: Valid Docker Hub image
- [x] **Registry**: Docker Hub URL included
- [x] **Network**: Appropriate mode (bridge)
- [x] **Support**: Forum thread URL (to be added)
- [x] **Project**: GitHub URL
- [x] **Overview**: Clear, concise description
- [x] **Category**: Proper categorization
- [x] **Icon**: Publicly accessible, appropriate size
- [x] **WebUI**: Correct URL format with [IP]:[PORT] placeholders
- [x] **Config entries**: All properly documented
  - [x] Paths have descriptions and defaults
  - [x] Variables have descriptions and defaults
  - [x] Ports properly mapped
  - [x] Sensitive data uses `Mask="true"`
- [x] **Display attributes**: Appropriate (always/advanced)
- [x] **Required fields**: Properly marked

## Testing Before Submission

Test the complete installation flow:

1. **Clean install test**:
   - Remove any existing container
   - Install from template
   - Verify all config options appear correctly
   - Check that defaults are sensible

2. **Functionality test**:
   - Container starts without errors
   - WebUI is accessible
   - Configuration persists across restarts
   - Volumes are properly mounted

3. **Documentation test**:
   - All descriptions are clear
   - Defaults make sense
   - Links work (support, project, icon)

## Common Issues & Solutions

### Issue: Python SHA values showing as config
**Solution**: Ensure Docker image has proper OCI labels (added in Dockerfile)

### Issue: Template not appearing in search
**Solution**:
- Check XML syntax is valid
- Ensure template URL is publicly accessible
- Verify GitHub raw URL is correct
- Wait up to 24 hours for CA sync

### Issue: Icon not displaying
**Solution**:
- Icon must be publicly accessible
- Use GitHub raw URL format
- Ensure icon is reasonable size (< 500KB)
- PNG format recommended

## Resources

- **Unraid Documentation**: https://docs.unraid.net/unraid-os/manual/applications/
- **Template Guidelines**: https://selfhosters.net/docker/templating/templating/
- **Community Applications Plugin**: https://github.com/Squidly271/community.applications
- **Template Examples**: https://github.com/binhex/docker-templates
- **Unraid Forums**: https://forums.unraid.net/

## Community Applications Approval Timeline

After submission:
- **Review period**: 1-7 days (volunteer moderators)
- **Feedback**: May request changes to template
- **Approval**: Template becomes searchable in CA
- **Updates**: Auto-sync from GitHub within 24-48 hours

## Support

For questions about this template or submission process:
- Open an issue: https://github.com/trevren11/tik-tok-collections-downloader/issues
- Unraid Forums: [Support thread URL once created]
