# Deploying NAS Book Search to your Synology DS920+

This guide assumes you have no Docker experience. It walks through every step.

---

## Step 1: Enable Docker on your NAS

1. Open **Package Center** on your Synology (the shopping bag icon on the desktop)
2. Search for **Container Manager** (on older DSM versions this is called "Docker")
3. Click **Install**
4. Wait for it to finish

---

## Step 2: Enable SSH access

You need SSH to copy files to the NAS and run commands.

1. Open **Control Panel** > **Terminal & SNMP**
2. Tick **Enable SSH service**
3. Leave the port as **22**
4. Click **Apply**

---

## Step 3: Copy the project files to your NAS

From your Mac terminal, run this command (replace `YOUR_NAS_IP` with your NAS's IP address, e.g. `192.168.1.50`):

```bash
rsync -av --exclude='.venv' --exclude='data' --exclude='__pycache__' \
  /Users/stephen/Projects/Nas_search/ \
  stephen@YOUR_NAS_IP:/volume1/docker/nas-search/
```

It will ask for your NAS password. Type it and press Enter (you won't see the characters as you type — that's normal).

> **How to find your NAS IP:** Open Synology DSM in your browser. The IP is in the address bar (e.g. `192.168.1.50`).

---

## Step 4: Configure your book folders

SSH into your NAS:

```bash
ssh stephen@YOUR_NAS_IP
```

Edit the docker-compose file to map your actual book folders:

```bash
cd /volume1/docker/nas-search
vi docker-compose.yml
```

> **If you're not comfortable with `vi`**: you can edit `docker-compose.yml` on your Mac before the rsync step instead.

Find the section that says `# ── NAS book volumes (read-only) ──` and add your folders. For example, if you have books in `/volume1/Books` and `/volume1/RPGs`:

```yaml
    volumes:
      - nas_search_data:/app/data
      - ./config.yml:/app/config.yml
      - /volume1/Books:/mnt/nas/Books:ro
      - /volume1/RPGs:/mnt/nas/RPGs:ro
```

The format is `NAS_PATH:CONTAINER_PATH:ro`
- Left side: the real path on your NAS
- Right side: where it appears inside the container (always use `/mnt/nas/...`)
- `ro` means read-only (the app never writes to your book folders)

> **Finding your folder paths:** In File Station, right-click a folder and choose **Properties**. The "Location" field shows the path (e.g. `/volume1/Books`).

---

## Step 5: Configure the indexed folders

Edit `config.yml` to tell the search app which folders to scan. The paths here must match the **right side** (container paths) from docker-compose.yml:

```yaml
indexed_folders:
  Books: /mnt/nas/Books
  RPGs: /mnt/nas/RPGs

extensions:
  - epub
  - pdf
```

The label (e.g. `Books`) is just a display name — call it whatever you like.

You can also change these later from the Settings page in the web UI.

---

## Step 6: Build and start the container

Still in your SSH session:

```bash
cd /volume1/docker/nas-search
sudo docker-compose up -d --build
```

This will:
1. Download the Python 3.11 base image (first time only, ~150MB)
2. Install the dependencies
3. Start the app in the background

It takes 1-2 minutes the first time. Subsequent starts are fast.

---

## Step 7: Open the web UI and trigger the first index

Open your browser and go to:

```
http://YOUR_NAS_IP:8080
```

You should see the NAS Book Search interface. The first time, there are no files indexed yet.

1. Click the **Settings** button (bottom right)
2. Verify your folders and extensions are correct
3. Click **Save**
4. Click the **Reindex** button (bottom right)

The status bar will show "(indexing...)" while it scans. For ~100k files, expect 1-3 minutes.

Once complete, you can start searching.

---

## How it works day-to-day

- **Searching**: Just type in the search box. Results appear as you type.
- **Filters**: Use the folder and extension dropdowns to narrow results.
- **Fuzzy search**: Tick the "Fuzzy" checkbox if you're unsure of exact spelling.
- **Open files**: Click "Open" to jump to that folder in File Station.
- **Pin folders**: Click "Pin" on a result to save that folder as a shortcut.
- **Nightly updates**: The index automatically refreshes at 02:00 each night.

---

## Common tasks

### View logs

```bash
ssh stephen@YOUR_NAS_IP
sudo docker logs nas-search
```

Add `-f` to follow logs in real-time:

```bash
sudo docker logs -f nas-search
```

### Restart the app

```bash
cd /volume1/docker/nas-search
sudo docker-compose restart
```

### Stop the app

```bash
cd /volume1/docker/nas-search
sudo docker-compose down
```

### Update the app after code changes

Copy the updated files from your Mac:

```bash
rsync -av --exclude='.venv' --exclude='data' --exclude='__pycache__' \
  /Users/stephen/Projects/Nas_search/ \
  stephen@YOUR_NAS_IP:/volume1/docker/nas-search/
```

Then rebuild on the NAS:

```bash
ssh stephen@YOUR_NAS_IP
cd /volume1/docker/nas-search
sudo docker-compose up -d --build
```

### Add a new book folder

1. Edit `docker-compose.yml` to add the volume mount
2. Edit `config.yml` to add the folder (or use the Settings page after restart)
3. Rebuild: `sudo docker-compose up -d --build`
4. Click **Reindex** in the web UI

### Change the nightly index time

Edit `config.yml`:

```yaml
schedule_hour: 3
schedule_minute: 30
```

Then restart: `sudo docker-compose restart`

---

## Troubleshooting

**"Connection refused" when opening the web UI**
- Check the container is running: `sudo docker ps`
- Check logs for errors: `sudo docker logs nas-search`
- Make sure port 8080 isn't used by another app on your NAS

**No search results after indexing**
- Check Settings — are the folder paths correct?
- Check extensions — are your file types listed?
- Check logs: `sudo docker logs nas-search | grep -i index`

**File Station "Open" link doesn't work**
- The link uses port 5000 (default DSM port). If you've changed your DSM port, the link URL will need adjusting in `app.js` (the `NAS_PORT` variable near the top).

**Indexing seems stuck**
- Check logs: `sudo docker logs -f nas-search`
- Large collections (500k+ files) may take 10-15 minutes on the first full scan

**Container won't start after NAS reboot**
- The `restart: unless-stopped` policy should handle this automatically
- If not: `cd /volume1/docker/nas-search && sudo docker-compose up -d`
