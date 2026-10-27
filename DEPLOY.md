# Deploying WeddingSnap on a DigitalOcean droplet

This guide takes you from nothing to a live site at `https://photos.yourdomain.com`, with HTTPS, photos in
Cloudflare R2, nightly database backups, and automatic restarts. It takes about an hour the first time.

You'll do steps 1–4 in web dashboards, step 5 on your Mac, and steps 6–9 on the server over SSH.

**What you need**
- A **DigitalOcean** account (digitalocean.com), with a card or PayPal added
- A **domain name** (e.g. from GoDaddy, Hostinger or Cloudflare, about ₹800/year). HTTPS needs one, and logins only
  work over HTTPS in production.
- A **Cloudflare** account for R2 (free to create)
- This project pushed to your GitHub repo

---

## 1. Cloudflare R2: buckets and keys

1. Cloudflare dashboard → **R2 Object Storage** → **Create bucket**
   - Name: `weddingsnap-prod`, Location: **Automatic** (or the Asia-Pacific hint). Leave **Public access off**.
2. Create a second bucket: `weddingsnap-backups` (for nightly database backups).
   - Bucket → Settings → **Object lifecycle rules** → add a rule *Delete objects 30 days after upload*.
3. In `weddingsnap-prod` → Settings → lifecycle rule *Abort incomplete multipart uploads after 1 day*.
4. R2 → **Manage API tokens** → **Create API token**
   - Permissions: **Object Read & Write**
   - Specify buckets: `weddingsnap-prod` **and** `weddingsnap-backups`
   - Create, then copy and keep safe: **Access Key ID**, **Secret Access Key** (shown only once), and your
     **Account ID** (shown on the R2 overview page).

## 2. DigitalOcean: SSH key, droplet, firewall

**a) SSH key.** This lets you log in to the droplet from your Mac. In Terminal on your Mac:
```bash
ls ~/.ssh/id_ed25519.pub
```
If that file doesn't exist, create one (press Enter at every question):
```bash
ssh-keygen -t ed25519
```
Show it and copy the whole line:
```bash
cat ~/.ssh/id_ed25519.pub
```

**b) Create the droplet.** DigitalOcean → **Create → Droplets**:

| Setting | Choose |
|---|---|
| Region | **Bangalore (BLR1)**, closest to Indian guests |
| Image | **Ubuntu 24.04 (LTS) x64** |
| Size | **Basic → Regular → 4 GB / 2 vCPU / 80 GB SSD ($24/mo)**, recommended. Pilot with a few photographers: 2 GB / 1 vCPU ($12/mo). Avoid the $4 / 512 MB size. |
| Authentication | **SSH Key → New SSH Key**, paste the line from (a), name it `my-mac` |
| Extras | Tick **Monitoring** (free graphs and alerts). **Backups** (weekly, +20%) recommended once you have paying customers. |
| Hostname | `weddingsnap-prod` |

Click **Create Droplet** and wait about a minute. Copy its **IPv4 address**, e.g. `203.0.113.25`.

**c) Firewall.** **Networking → Firewalls → Create Firewall**, name `weddingsnap-web`:
- Inbound rules: keep **SSH (22)**, add **HTTP (80)** and **HTTPS (443)** (sources: All IPv4, All IPv6).
- Outbound: leave the defaults (all allowed).
- **Apply to Droplets**: `weddingsnap-prod` → **Create Firewall**.

(The setup script also turns on Ubuntu's own firewall with the same three ports.)

**d) Optional: Reserved IP.** **Networking → Reserved IPs → assign to `weddingsnap-prod`**. It's free while
attached, and lets you replace the droplet later without changing DNS. If you use it, use that IP in the next steps.

## 3. Domain: point it at the server

At your domain provider's DNS settings, add an **A record**:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `photos` | your server IP | Auto / 300 |

This gives you `photos.yourdomain.com`. (You can also manage DNS in DigitalOcean under **Networking → Domains**,
but that means changing your domain's nameservers; adding the A record at your registrar is simpler.) If your domain is on Cloudflare, set the record to **DNS only** (grey
cloud). Check it from your Mac after a few minutes (it should print your server IP):
```bash
dig +short photos.yourdomain.com
```

## 4. Log in to the droplet once

DigitalOcean droplets log in as `root`:
```bash
ssh root@203.0.113.25
```
Type `yes` the first time. If you get in, type `exit` to come back to your Mac. (If SSH doesn't work, the droplet's
page has **Access → Launch Droplet Console** in the browser.)

## 5. Push the code and clone it on the droplet

On your Mac, make sure everything is pushed:
```bash
cd "/Users/anshumannautiyal/Documents/image detection" && git add -A && git commit -m "Deploy" && git push
```

On the droplet (`ssh root@203.0.113.25`), give it read-only access to your private repo with a **deploy key**:
```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```
GitHub → your repo → **Settings → Deploy keys → Add deploy key**: paste the line, leave *Allow write access*
unticked. Then check access (type `yes`):
```bash
ssh -T git@github.com
```
Clone into `/srv/weddingsnap`. The app can't run from inside `/root`; if you already cloned there, move it with
`mv /root/eventsnap /srv/weddingsnap` instead.
```bash
git clone git@github.com:AnshumanNautiyal15/eventsnap.git /srv/weddingsnap
cd /srv/weddingsnap
```

## 6. First deploy run

```bash
sudo bash deploy/deploy.sh photos.yourdomain.com you@youremail.com
```
The first run installs packages (Python, Node for building the app screens, nginx), adds a 2 GB swap file, and
creates `/srv/weddingsnap/.env` with your domain and **freshly generated secret keys**. Then it stops so you can add
the R2 details.

## 7. Add your R2 details and deploy

```bash
sudo nano /srv/weddingsnap/.env
```
Fill in `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` from step 1, and check `R2_BUCKET` /
`BACKUP_R2_BUCKET` match your bucket names. Save with **Ctrl+O, Enter**, exit with **Ctrl+X**.

Run it again. This time it does everything:
- installs the Python packages (`requirements.txt`) and builds the app screens
- sets up the database
- starts the **gunicorn** service (settings in `gunicorn.conf.py`) and the nightly backup timer
- configures nginx, the firewall and the HTTPS certificate
```bash
sudo bash deploy/deploy.sh photos.yourdomain.com you@youremail.com
```
It ends with `gunicorn is running. Site: https://photos.yourdomain.com`.

## 8. Create your admin login

```bash
sudo -u weddingsnap /srv/weddingsnap/.venv/bin/python /srv/weddingsnap/manage.py createsuperuser
```
Choose a username and a strong password. This is **your** login for `/admin/`.

## 9. Check that it all works

1. Open `https://photos.yourdomain.com/admin/`, log in, and go to **Photographers → Add photographer**. Create a
   test photographer and set their storage.
2. Open `https://photos.yourdomain.com` in a private window and log in as that photographer.
   - Create an event, upload a few photos, press **Index photos**.
3. Scan the event's QR code with your phone, take a selfie, and check that your photos appear and download.
4. Check the server is backing up (should list a file uploaded to `weddingsnap-backups`):
   ```bash
   sudo -u weddingsnap /srv/weddingsnap/.venv/bin/python /srv/weddingsnap/manage.py backup_db
   ```
5. Free uptime alerts: at uptimerobot.com add an HTTP monitor for `https://photos.yourdomain.com/healthz`.

You're live. 🎉

---

## Updating to a new version

Push from your Mac:
```bash
cd "/Users/anshumannautiyal/Documents/image detection" && git add -A && git commit -m "Describe your change" && git push
```
Then on the droplet:
```bash
cd /srv/weddingsnap && sudo bash deploy/deploy.sh update
```
It backs up the database, runs `git pull`, installs packages, rebuilds the app screens, migrates and restarts
gunicorn. Guests may notice a few seconds' pause.

## Everyday commands (on the server)

| What | Command |
|---|---|
| Is the app running? | `systemctl status weddingsnap` |
| Live app logs | `journalctl -u weddingsnap -f` |
| Restart the app (gunicorn) | `sudo systemctl restart weddingsnap` |
| gunicorn settings | edit `/srv/weddingsnap/gunicorn.conf.py`, then restart |
| Index all waiting photos | `sudo -u weddingsnap /srv/weddingsnap/.venv/bin/python /srv/weddingsnap/manage.py index_photos` |
| Backup now | `sudo -u weddingsnap /srv/weddingsnap/.venv/bin/python /srv/weddingsnap/manage.py backup_db` |
| When is the next backup? | `systemctl list-timers weddingsnap-backup` |
| Memory / disk | `free -h` · `df -h /` |
| HTTPS certificate | Renews automatically; check with `sudo certbot renew --dry-run` |

## Restoring the database from a backup

Backups are in `/srv/weddingsnap/backups/` (last 14) and in the `weddingsnap-backups` R2 bucket (30 days).
```bash
sudo systemctl stop weddingsnap
cd /srv/weddingsnap && sudo -u weddingsnap cp db.sqlite3 db.sqlite3.before-restore
sudo -u weddingsnap sh -c 'gunzip -c backups/weddingsnap-YYYY-MM-DD-HHMMSS.sqlite3.gz > db.sqlite3'
sudo rm -f db.sqlite3-wal db.sqlite3-shm
sudo systemctl start weddingsnap
```
(For a backup that's only in R2, download it from the Cloudflare dashboard and copy it up with `scp` first.)

## Troubleshooting

| Problem | Fix |
|---|---|
| `deploy.sh` stops at the HTTPS step | The domain doesn't point at the server yet (check step 3 with `dig`), or ports 80/443 aren't open in the DigitalOcean Cloud Firewall. Wait for DNS, then re-run `deploy.sh` with your domain and email. |
| **502 Bad Gateway** | The app isn't running: `journalctl -u weddingsnap -n 50`. Often a typo in `.env`; fix it, then `sudo systemctl restart weddingsnap`. |
| "Cloudflare R2 is partly configured" in the logs | One of the `R2_*` values in `.env` is empty. |
| Login doesn't stick / CSRF error | Open the site via `https://` and the exact domain in `DJANGO_ALLOWED_HOSTS` / `PUBLIC_BASE_URL`. |
| **413** on upload | Batch too large for nginx: raise `client_max_body_size` in `/etc/nginx/sites-available/weddingsnap`, then `sudo systemctl reload nginx`. |
| Indexing slow | Expected on 2 vCPUs (~1–2 photos/s). Resize in DigitalOcean (droplet → **Resize** → CPU and RAM only, so you can size down later) to 8 GB / 4 vCPU; the app uses the extra cores automatically after it restarts. |
| Can't SSH | Check the Cloud Firewall still allows port 22; use **Launch Droplet Console** from the droplet page meanwhile. |

## Costs to expect (approximate)

| Item | Monthly |
|---|---|
| Droplet 4 GB / 2 vCPU / 80 GB, Bangalore | $24 (~₹2,100) · pilot size 2 GB: $12 |
| Weekly droplet backups (optional) | +20% (~₹420) |
| Cloudflare R2 | first 10 GB free, then ~₹1.3 per GB; downloads free |
| Domain | ~₹70 |

## Other providers (AceCloud, etc.)

The scripts work on any **Ubuntu 22.04/24.04** server. Only step 2 changes: create the server in that provider's
console, with an SSH key, a firewall/security group opening ports 22, 80 and 443, and a public IP. Their default
login is often `ubuntu` instead of `root`. Everything from step 3 on is the same.
