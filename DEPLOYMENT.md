# Hướng Dẫn Deployment Production - ERP App

## Yêu Cầu Hệ Thống

### Server Requirements

- Ubuntu 20.04 LTS hoặc cao hơn
- Python 3.10+
- Node.js 18+
- MariaDB 10.6+ hoặc PostgreSQL 13+
- Redis 6+
- Nginx (cho reverse proxy)

### Minimum Hardware

- RAM: 4GB (khuyến nghị 8GB+)
- CPU: 2 cores (khuyến nghị 4 cores+)
- Storage: 20GB SSD (khuyến nghị 50GB+)

## Cài Đặt Production

### 1. Chuẩn bị Server

```bash
# Cập nhật hệ thống
sudo apt update && sudo apt upgrade -y

# Cài đặt dependencies
sudo apt install -y python3-dev python3-pip python3-venv \
    git build-essential libssl-dev libffi-dev \
    libmysqlclient-dev libpq-dev \
    redis-server nginx supervisor \
    curl software-properties-common

# Cài đặt Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Cài đặt yarn
npm install -g yarn
```

### 2. Cài Đặt MariaDB/MySQL

```bash
# Cài đặt MariaDB
sudo apt install -y mariadb-server mariadb-client

# Bảo mật MariaDB
sudo mysql_secure_installation

# Tạo database và user
sudo mysql -u root -p
```

```sql
CREATE DATABASE frappe_production;
CREATE USER 'frappe'@'localhost' IDENTIFIED BY 'strong_password_here';
GRANT ALL PRIVILEGES ON frappe_production.* TO 'frappe'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 3. Cài Đặt Frappe Bench

```bash
# Tạo user frappe
sudo adduser frappe
sudo usermod -aG sudo frappe
su - frappe

# Cài đặt Frappe Bench
git clone https://github.com/frappe/bench.git ~/.bench
pip3 install --user -e ~/.bench

# Thêm bench vào PATH
echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc
source ~/.bashrc
```

### 4. Tạo Frappe Site Production

```bash
# Khởi tạo bench
bench init frappe-bench --frappe-branch version-15
cd frappe-bench

# Tạo site production
bench new-site your-domain.com \
    --db-name frappe_production \
    --db-user frappe \
    --db-password strong_password_here

# Clone app ERP từ GitHub
bench get-app erp https://github.com/your-username/erp.git

# Cài đặt app
bench install-app erp --site your-domain.com
```

### 5. Cấu Hình Production

```bash
# Enable production mode
bench --site your-domain.com enable-scheduler
bench --site your-domain.com set-maintenance-mode off

# Setup production
sudo bench setup production frappe

# Setup nginx và supervisor
sudo bench setup nginx
sudo bench setup supervisor
```

### 6. SSL Certificate (Let's Encrypt)

```bash
# Cài đặt certbot
sudo apt install -y certbot python3-certbot-nginx

# Tạo SSL certificate
sudo certbot --nginx -d your-domain.com

# Thiết lập auto-renewal
sudo crontab -e
# Thêm dòng sau:
# 0 12 * * * /usr/bin/certbot renew --quiet
```

## Cấu Hình Môi Trường

### Environment Variables

Tạo file `sites/your-domain.com/site_config.json`:

```json
{
  "db_name": "frappe_production",
  "db_password": "strong_password_here",
  "encryption_key": "your-32-character-encryption-key",
  "host_name": "https://your-domain.com",
  "install_apps": ["erp"],
  "limits": {
    "posts": 100,
    "users": 1000
  },
  "maintenance_mode": 0,
  "pause_scheduler": 0,
  "redis_cache": "redis://localhost:13000",
  "redis_queue": "redis://localhost:11000",
  "redis_socketio": "redis://localhost:12000"
}
```

### Common Site Config

Tạo file `sites/common_site_config.json`:

```json
{
  "auto_update": false,
  "background_workers": 1,
  "file_watcher_port": 6787,
  "frappe_user": "frappe",
  "gunicorn_workers": 4,
  "live_reload": false,
  "rebase_on_pull": false,
  "redis_cache": "redis://localhost:13000",
  "redis_queue": "redis://localhost:11000",
  "redis_socketio": "redis://localhost:12000",
  "restart_supervisor_on_update": true,
  "serve_default_site": true,
  "socketio_port": 9000,
  "use_redis_auth": false,
  "webserver_port": 8000
}
```

## Backup và Monitoring

### Tự Động Backup

```bash
# Tạo script backup
sudo nano /home/frappe/backup.sh
```

```bash
#!/bin/bash
cd /home/frappe/frappe-bench
bench --site your-domain.com backup --with-files
```

```bash
# Phân quyền và tạo cron job
chmod +x /home/frappe/backup.sh
crontab -e
# Thêm dòng sau để backup hàng ngày lúc 2:00 AM:
# 0 2 * * * /home/frappe/backup.sh
```

### Log Monitoring

```bash
# Xem logs
tail -f logs/web.log
tail -f logs/worker.log
tail -f logs/schedule.log

# Supervisor status
sudo supervisorctl status
```

## Cập Nhật App

### Cập nhật từ GitHub

```bash
cd /home/frappe/frappe-bench

# Pull latest changes
bench get-app erp

# Migrate
bench --site your-domain.com migrate

# Restart services
sudo supervisorctl restart all
```

### Rolling Updates

```bash
# Backup trước khi update
bench --site your-domain.com backup

# Enable maintenance mode
bench --site your-domain.com set-maintenance-mode on

# Update app
git -C apps/erp pull origin main
bench --site your-domain.com migrate

# Disable maintenance mode
bench --site your-domain.com set-maintenance-mode off

# Restart services
sudo supervisorctl restart all
```

## Troubleshooting

### Common Issues

1. **Permission Issues**

```bash
sudo chown -R frappe:frappe /home/frappe/frappe-bench
sudo chmod -R 755 /home/frappe/frappe-bench
```

2. **Database Connection Issues**

```bash
# Check MariaDB status
sudo systemctl status mariadb

# Check Redis status
sudo systemctl status redis-server
```

3. **Nginx Issues**

```bash
# Test nginx config
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### Performance Tuning

1. **Gunicorn Workers**: Tăng số worker trong `common_site_config.json`
2. **Database Optimization**: Tối ưu MySQL/MariaDB configuration
3. **Redis Memory**: Tăng Redis memory limit
4. **Background Workers**: Tăng số background workers

## Security Checklist

- [ ] SSL certificate được cấu hình
- [ ] Firewall được thiết lập (chỉ mở port 80, 443, 22)
- [ ] Database password mạnh
- [ ] Regular security updates
- [ ] Backup strategy implemented
- [ ] Log monitoring setup
- [ ] User access control configured

## Support

Để được hỗ trợ, vui lòng tạo issue trên GitHub repository hoặc liên hệ:

- Email: linh.nguyenhai@wellspring.edu.vn
- GitHub: [Repository URL]
