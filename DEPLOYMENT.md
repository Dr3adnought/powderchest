# PowderChest Deployment Guide

## Prerequisites
- Docker and Docker Compose installed on Pi5
- Nginx configured (host or container) as reverse proxy
- GitHub access configured

## Deployment Steps

### 1. Pull Latest Code on Pi5
```bash
cd /path/to/powderchest
git pull origin main
```

### 2. Build and Start the Visitor API Container
```bash
# Build and start the container
docker-compose up -d --build

# Verify it's running
docker-compose ps
docker-compose logs visitor-api

# Test the health endpoint
curl http://localhost:5000/health
```

### 3. Configure Nginx on Pi4

Add the API proxy configuration to your Nginx site config:

```bash
# Edit your site configuration
sudo nano /etc/nginx/sites-available/powderchest.com

# Add the contents from nginx-api-config.conf inside your server block

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### 4. Test the Production Setup

```bash
# From Pi4 or any machine, test the health endpoint
curl https://powderchest.com/health

# Should return:
# {"service":"visitor-api","status":"healthy"}
```

### 5. Monitor the Container

```bash
# View logs
docker-compose logs -f visitor-api

# Check visitor data
cat data/visitors.json

# Restart if needed
docker-compose restart visitor-api
```

## Data Persistence

Visitor data is stored in `./data/visitors.json` on the host machine, which is mounted into the container at `/data/visitors.json`. This ensures data persists across container restarts.

## Troubleshooting

### Container won't start
```bash
docker-compose logs visitor-api
```

### API not responding
```bash
# Check if container is running
docker ps | grep visitor-api

# Check port binding
sudo netstat -tulpn | grep 5000

# Test locally on Pi5
curl http://localhost:5000/health
```

### Nginx proxy issues
```bash
# Check Nginx error logs on Pi4
sudo tail -f /var/log/nginx/error.log

# Test if Pi5 API is reachable from Pi4
curl http://<pi5-ip>:5000/health
```

## Web Root Mount (Current Production Layout)

Website files now live on the Pi host and are mounted into the Nginx container:

```text
/home/BATFE/indomitable-rapscallion/www  ->  /var/www/powderchest
```

This replaces the older host path `/var/www/html` workflow.

## Updating the API

```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose up -d --build

# Verify
docker-compose logs visitor-api
```

## Security Notes

- The visitor-api container listens on port 5000 for reverse-proxy access
- All external traffic goes through Nginx on Pi4 (reverse proxy)
- HTTPS is handled by Nginx/Cloudflare
- No sensitive data is stored; visitor IDs are browser fingerprint hashes

## Secrets Hygiene

- Do not commit plaintext credentials to the repository.
- Use environment variables (for example via an untracked `.env` file) for values such as Pi-hole `WEBPASSWORD`.
