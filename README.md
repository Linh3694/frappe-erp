# ERP App - Frappe Framework

[![Deploy to Production](https://github.com/Linh3694/frappe-erp/actions/workflows/deploy-production.yml/badge.svg)](https://github.com/Linh3694/frappe-erp/actions/workflows/deploy-production.yml)
[![CI](https://github.com/Linh3694/frappe-erp/actions/workflows/ci.yml/badge.svg)](https://github.com/Linh3694/frappe-erp/actions/workflows/ci.yml)

Ứng dụng ERP dành cho các ứng dụng nội bộ của WSHN được xây dựng trên Frappe Framework.

## 📋 Mục Lục

- [Giới Thiệu](#giới-thiệu)
- [Cài Đặt Development](#cài-đặt-development)
- [Auto Deployment](#auto-deployment)
- [GitHub Actions Workflows](#github-actions-workflows)
- [Production Deployment](#production-deployment)
- [Đóng Góp](#đóng-góp)

## 🚀 Giới Thiệu

App ERP này được thiết kế để quản lý các quy trình nội bộ của Wellspring Hanoi, bao gồm:

- Quản lý nhân sự
- Quản lý tài sản
- Quản lý quy trình làm việc
- Báo cáo và phân tích

## 💻 Cài Đặt Development

### Yêu Cầu Hệ Thống

- Python 3.10+
- Node.js 18+
- MariaDB/MySQL
- Redis
- Frappe Framework v15

### Cài Đặt Local

```bash
# 1. Clone repository
git clone https://github.com/Linh3694/frappe-erp.git
cd frappe-erp

# 2. Khởi tạo Frappe bench (nếu chưa có)
bench init frappe-bench --frappe-branch version-15
cd frappe-bench

# 3. Get app từ local path hoặc GitHub
bench get-app erp /path/to/frappe-erp

# 4. Tạo site mới
bench new-site development.localhost

# 5. Cài đặt app
bench install-app erp --site development.localhost

# 6. Chạy development server
bench start
```

### Development Workflow

```bash
# Tạo feature branch từ develop
git checkout develop
git pull origin develop
git checkout -b feature/your-feature-name

# Làm việc và commit thay đổi
git add .
git commit -m "feat: add your feature description"

# Push và tạo Pull Request
git push origin feature/your-feature-name
# Tạo PR từ feature branch vào develop
```

## 🔄 Auto Deployment

### Cách Hoạt Động

Hệ thống auto deployment được thiết lập với các bước sau:

1. **Development**: Làm việc trên branch `develop`
2. **Testing**: Tạo Pull Request vào `main` để trigger CI tests
3. **Production**: Merge vào `main` sẽ tự động deploy lên production

### Production Infrastructure

```
Internet → Load Balancer (42.96.40.246) → Backend Server (172.16.20.111)
                                            └── /srv/app/frappe-bench
```

### Deployment Process

Khi code được push vào branch `main`:

1. **GitHub Actions** tự động trigger
2. **CI Tests** chạy để đảm bảo code quality
3. **SSH** vào Load Balancer → Backend server
4. **Backup** site hiện tại
5. **Update** app từ GitHub
6. **Migrate** database
7. **Build** assets
8. **Restart** services
9. **Health check** và disable maintenance mode

## 🔧 GitHub Actions Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

Chạy khi:

- Push vào `develop` hoặc `main`
- Tạo Pull Request

Thực hiện:

- ✅ Code linting với Ruff
- ✅ Code formatting check
- ✅ Frappe app structure validation
- ✅ Security scan
- ✅ Python syntax check

### 2. Production Deployment (`.github/workflows/deploy-production.yml`)

Chạy khi:

- Push vào branch `main`
- Manual trigger từ GitHub Actions UI

Thực hiện:

- 🚀 Tự động deploy lên production server
- 💾 Backup trước khi deploy
- 🔄 Update app code
- 🏗️ Build assets
- 🔄 Restart services
- 📊 Health check

### 3. Required GitHub Secrets

Để setup auto deployment, cần cấu hình các secrets sau trong GitHub repository:

```bash
# SSH Private Key để kết nối server
SSH_PRIVATE_KEY

# Optional - nếu khác default
LB_HOST=42.96.40.246
BACKEND_HOST=172.16.20.111
SSH_USER=frappe
SITE_NAME=admin.sis.localhost
```

#### Cách Thêm SSH Key:

1. Tạo SSH key pair trên local machine:

```bash
ssh-keygen -t rsa -b 4096 -C "github-actions@your-domain.com"
```

2. Copy public key lên servers:

```bash
ssh-copy-id frappe@42.96.40.246
ssh-copy-id frappe@172.16.20.111
```

3. Thêm private key vào GitHub Secrets:
   - Vào `Settings` → `Secrets and variables` → `Actions`
   - Tạo secret `SSH_PRIVATE_KEY` với nội dung private key

## 🚀 Production Deployment

### Manual Deployment

Nếu cần deploy thủ công:

```bash
# SSH vào production server
ssh frappe@42.96.40.246
ssh frappe@172.16.20.111

# Chạy deployment script
cd /srv/app/frappe-bench
wget https://raw.githubusercontent.com/Linh3694/frappe-erp/main/scripts/deploy.sh
chmod +x deploy.sh
./deploy.sh admin.sis.localhost
```

### Monitoring & Logs

```bash
# Xem logs của deployment
cd /srv/app/frappe-bench
tail -f logs/web.log
tail -f logs/worker.log

# Kiểm tra status
bench --site admin.sis.localhost get-app-list
bench --site admin.sis.localhost migrate-status
```

### Rollback

Nếu deployment có vấn đề:

```bash
# Enable maintenance mode
bench --site admin.sis.localhost set-maintenance-mode on

# Restore từ backup
bench --site admin.sis.localhost restore [backup-file]

# Disable maintenance mode
bench --site admin.sis.localhost set-maintenance-mode off
```

## 🏗️ Cấu Trúc Dự Án

```
frappe-erp/
├── .github/
│   └── workflows/          # GitHub Actions workflows
│       ├── ci.yml         # CI/CD pipeline
│       └── deploy-production.yml
├── erp/                   # Main app directory
│   ├── __init__.py
│   ├── hooks.py          # App configuration
│   ├── modules.txt       # Frappe modules
│   └── erp/             # App modules
├── scripts/
│   └── deploy.sh         # Production deployment script
├── DEPLOYMENT.md         # Chi tiết hướng dẫn deployment
├── pyproject.toml        # Python project configuration
└── README.md
```

## 🤝 Đóng Góp

### Code Standards

- Sử dụng [Ruff](https://docs.astral.sh/ruff/) để linting và formatting
- Follow [Frappe Framework guidelines](https://frappeframework.com/docs/v14/user/en/basics)
- Commit messages theo [Conventional Commits](https://www.conventionalcommits.org/)

### Quy Trình Đóng Góp

1. Fork repository
2. Tạo feature branch từ `develop`
3. Implement changes với tests
4. Ensure CI passes
5. Tạo Pull Request với mô tả chi tiết
6. Code review và merge

### Testing

```bash
# Chạy linting
ruff check erp/
ruff format erp/ --check

# Chạy pre-commit hooks
pre-commit run --all-files

# Validate Frappe app structure
python -c "import erp; print('App structure valid')"
```

## 📞 Hỗ Trợ

- **Email**: linh.nguyenhai@wellspring.edu.vn
- **GitHub Issues**: [Create Issue](https://github.com/Linh3694/frappe-erp/issues)
- **Documentation**: [DEPLOYMENT.md](./DEPLOYMENT.md)

## 📄 License

MIT License - xem [LICENSE](./license.txt) để biết thêm chi tiết.

---

**Made with ❤️ by Wellspring Hanoi IT Team**
