# Music Indie Backend

Private deployment source for the Music Indie Android QA service. Official YouTube search, authorized media conversion with FFmpeg and yt-dlp, authenticated temporary MP3 jobs. See main Music Indie project for Android source and tests.

See RENDER.md and render.yaml for the Render free QA deployment. No external service has been created yet.

Runtime: Python 3.12, Node 22, FFmpeg, one worker, persistent volume mounted at /data. Set YOUTUBE_API_KEY only in Railway service Variables. MEDIA_DATA_DIR=/data/media. No credentials are included in this repository.

GET /health reports whether YouTube search is configured. Without the API key, the service still starts and search returns a clear configuration error. Only Creative Commons or operator-authorized public video IDs may be converted.
